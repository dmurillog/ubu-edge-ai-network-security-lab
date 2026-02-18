#!/usr/bin/env python3
"""
Ingesta de tráfico de red hacia Supabase desde tshark.

Modos:
1) posterior: lee un .pcap/.pcapng (modo file)
2) tiempo real: escucha una interfaz en vivo (modo live)

Tabla destino esperada: public.network_packets
Campos mínimos enviados:
- timestamp, src_ip, dst_ip, src_port, dst_port, protocol, payload, payload_size, metadata

Variables requeridas:
- SUPABASE_URL (ej: http://ubuserver:8000)
- SUPABASE_API_KEY (anon o service role)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import requests
except ImportError:
    print("[ERROR] Falta dependencia 'requests'. Instala con: pip install requests")
    sys.exit(1)


STOP = False


def _handle_sigterm(sig: int, frame: Any) -> None:
    del sig, frame
    global STOP
    STOP = True


signal.signal(signal.SIGINT, _handle_sigterm)
signal.signal(signal.SIGTERM, _handle_sigterm)


@dataclass
class IngestConfig:
    supabase_url: str
    supabase_api_key: str
    table: str
    batch_size: int
    mode: str
    iface: Optional[str]
    pcap: Optional[Path]
    limit: Optional[int]
    dry_run: bool


def require_tshark() -> None:
    if shutil.which("tshark") is None:
        print("[ERROR] tshark no encontrado. Instala wireshark/tshark.")
        sys.exit(1)


def load_dotenv_if_exists() -> None:
    """Carga variables desde .env sin dependencias externas.

    Orden de búsqueda:
    1) .env en cwd y sus padres
    2) .env junto a este script y sus padres
    """
    candidates: List[Path] = []

    # cwd + padres
    cwd = Path.cwd().resolve()
    candidates.append(cwd / ".env")
    candidates.extend(parent / ".env" for parent in cwd.parents)

    # script dir + padres
    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / ".env")
    candidates.extend(parent / ".env" for parent in script_dir.parents)

    # elimina duplicados preservando orden
    seen = set()
    unique_candidates: List[Path] = []
    for c in candidates:
        s = str(c)
        if s not in seen:
            seen.add(s)
            unique_candidates.append(c)

    for env_path in unique_candidates:
        if not env_path.exists() or not env_path.is_file():
            continue

        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            if line.startswith("export "):
                line = line[len("export "):].strip()
                if "=" not in line:
                    continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            # No pisa variables ya exportadas en entorno
            if key and key not in os.environ:
                os.environ[key] = value

        print(f"[INFO] Variables cargadas desde {env_path}")
        return


def build_tshark_cmd(cfg: IngestConfig) -> List[str]:
    base = [
        "tshark",
        "-n",  # no DNS reverse
        "-l",  # line-buffered (importante para live)
        "-T",
        "fields",
        "-E",
        "separator=\t",
        "-E",
        "quote=n",
        "-E",
        "occurrence=f",
        "-e",
        "frame.time_epoch",
        "-e",
        "ip.src",
        "-e",
        "ip.dst",
        "-e",
        "tcp.srcport",
        "-e",
        "udp.srcport",
        "-e",
        "tcp.dstport",
        "-e",
        "udp.dstport",
        "-e",
        "_ws.col.Protocol",
        "-e",
        "frame.len",
        "-e",
        "data.text",
        "-e",
        "frame.number",
    ]

    if cfg.mode == "live":
        if not cfg.iface:
            print("[ERROR] --iface es requerido en modo live")
            sys.exit(1)
        return base + ["-i", cfg.iface]

    if not cfg.pcap:
        print("[ERROR] --pcap es requerido en modo file")
        sys.exit(1)
    return base + ["-r", str(cfg.pcap)]


def epoch_to_iso8601(epoch_text: str) -> str:
    val = float(epoch_text)
    t = dt.datetime.fromtimestamp(val, tz=dt.timezone.utc)
    return t.isoformat()


def choose_port(tcp_port: str, udp_port: str) -> Optional[int]:
    p = first_scalar(tcp_port) or first_scalar(udp_port)
    if not p:
        return None
    try:
        return int(p)
    except ValueError:
        return None


def first_scalar(value: str) -> str:
    """Devuelve el primer valor cuando tshark entrega listas separadas por coma."""
    v = value.strip()
    if not v:
        return ""
    # tshark en -T fields puede devolver "a,b" cuando hay múltiples ocurrencias
    return v.split(",", 1)[0].strip()


def to_record(parts: List[str], source: str) -> Optional[Dict[str, Any]]:
    # Esperamos 11 columnas según build_tshark_cmd
    if len(parts) < 11:
        return None

    ts, src_ip, dst_ip, tcp_sp, udp_sp, tcp_dp, udp_dp, proto, frame_len, data_text, frame_number = parts[:11]

    src_ip = first_scalar(src_ip)
    dst_ip = first_scalar(dst_ip)
    if not src_ip or not dst_ip:
        return None  # network_packets exige src/dst no nulos

    protocol = (proto.strip() or "UNKNOWN")[:20]
    payload_size = int(frame_len) if frame_len.strip().isdigit() else 0
    payload = data_text.strip() if data_text.strip() else None

    try:
        timestamp = epoch_to_iso8601(ts.strip()) if ts.strip() else dt.datetime.now(tz=dt.timezone.utc).isoformat()
    except Exception:
        timestamp = dt.datetime.now(tz=dt.timezone.utc).isoformat()

    record = {
        "timestamp": timestamp,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": choose_port(tcp_sp, udp_sp),
        "dst_port": choose_port(tcp_dp, udp_dp),
        "protocol": protocol,
        "payload": payload,
        "payload_size": payload_size,
        "metadata": {
            "source": source,
            "frame_number": int(frame_number) if frame_number.strip().isdigit() else None,
        },
    }
    return record


def post_batch(cfg: IngestConfig, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return

    if cfg.dry_run:
        print(f"[DRY-RUN] Enviaría lote de {len(rows)} filas")
        return

    url = f"{cfg.supabase_url.rstrip('/')}/rest/v1/{cfg.table}"
    headers = {
        "apikey": cfg.supabase_api_key,
        "Authorization": f"Bearer {cfg.supabase_api_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    resp = requests.post(url, headers=headers, data=json.dumps(rows), timeout=30)
    if resp.status_code >= 300:
        print(f"[ERROR] Supabase POST {resp.status_code}: {resp.text[:500]}")
        raise RuntimeError("Error insertando en Supabase")


def stream_lines(proc: subprocess.Popen[str]) -> Iterable[str]:
    assert proc.stdout is not None
    while not STOP:
        line = proc.stdout.readline()
        if not line:
            break
        yield line


def run_ingest(cfg: IngestConfig) -> None:
    cmd = build_tshark_cmd(cfg)
    print("$ " + " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    source = f"tshark:{cfg.mode}:{cfg.iface or cfg.pcap}"
    sent = 0
    batch: List[Dict[str, Any]] = []

    try:
        for line in stream_lines(proc):
            parts = line.rstrip("\n").split("\t")
            row = to_record(parts, source=source)
            if not row:
                continue
            batch.append(row)

            if cfg.limit and (sent + len(batch)) >= cfg.limit:
                # ajusta al límite exacto
                keep = cfg.limit - sent
                batch = batch[:keep]

            if len(batch) >= cfg.batch_size or (cfg.limit and (sent + len(batch)) >= cfg.limit):
                post_batch(cfg, batch)
                sent += len(batch)
                print(f"[OK] Filas enviadas acumuladas: {sent}")
                batch = []

            if cfg.limit and sent >= cfg.limit:
                break

        if batch:
            post_batch(cfg, batch)
            sent += len(batch)
            print(f"[OK] Filas enviadas acumuladas: {sent}")

    finally:
        if STOP and proc.poll() is None:
            proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate()

        if stderr:
            # Tshark suele escribir mensajes informativos en stderr
            tail = "\n".join(stderr.splitlines()[-5:])
            if tail.strip():
                print(f"[INFO] tshark stderr (últimas líneas):\n{tail}")

    print("[OK] Ingesta finalizada")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingesta tshark -> Supabase (network_packets)")
    p.add_argument("--mode", choices=["file", "live"], required=True)
    p.add_argument("--iface", help="Interfaz para modo live (ej: wlx90de8047828f)")
    p.add_argument("--pcap", help="Archivo pcap para modo file")
    p.add_argument("--table", default="network_packets")
    p.add_argument("--batch-size", type=int, default=200)
    p.add_argument("--limit", type=int, help="Máximo de filas a enviar (útil para pruebas)")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def build_config(args: argparse.Namespace) -> IngestConfig:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_API_KEY")

    if not supabase_url or not supabase_key:
        print("[ERROR] Define SUPABASE_URL y SUPABASE_API_KEY en el entorno")
        sys.exit(1)

    pcap = Path(args.pcap).expanduser().resolve() if args.pcap else None
    if args.mode == "file":
        if not pcap or not pcap.exists():
            print("[ERROR] --pcap no existe o no fue indicado")
            sys.exit(1)

    if args.batch_size < 1:
        print("[ERROR] --batch-size debe ser >= 1")
        sys.exit(1)

    return IngestConfig(
        supabase_url=supabase_url,
        supabase_api_key=supabase_key,
        table=args.table,
        batch_size=args.batch_size,
        mode=args.mode,
        iface=args.iface,
        pcap=pcap,
        limit=args.limit,
        dry_run=args.dry_run,
    )


def main() -> None:
    load_dotenv_if_exists()
    args = parse_args()
    require_tshark()
    cfg = build_config(args)
    run_ingest(cfg)


if __name__ == "__main__":
    main()
