#!/usr/bin/env python3
"""
Configuración de Access Point (AP) + captura con tshark para laboratorio.

Qué hace:
1) Detecta interfaz Wi-Fi (priorizando USB)
2) Genera configuración de hostapd y dnsmasq
3) Configura IP estática en la interfaz AP
4) Activa forwarding + NAT hacia la interfaz de salida
5) Inicia/activa servicios (hostapd/dnsmasq)
6) Lanza tshark en background para guardar PCAPs rotativos

Uso ejemplo:
	sudo python3 setting-ap.py --ssid UBU-LAB-AP --passphrase 'ClaveSegura123'

Nota: diseñado para Debian/Ubuntu/Raspberry Pi OS en entorno controlado.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


HOSTAPD_CONF = Path("/etc/hostapd/hostapd.conf")
HOSTAPD_DEFAULT = Path("/etc/default/hostapd")
DNSMASQ_AP_CONF = Path("/etc/dnsmasq.d/ap.conf")
SYSCTL_AP_CONF = Path("/etc/sysctl.d/99-ap-forward.conf")
DEFAULT_CAPTURE_DIR = Path("/home/ubu/Documentos/github/ubu-edge-ai-network-security-lab/pcaps")


@dataclass
class APConfig:
	iface: str
	uplink_iface: str
	ssid: str
	passphrase: str
	channel: int
	country: str
	ap_ip_cidr: str
	dhcp_start: str
	dhcp_end: str
	dhcp_lease: str
	capture_dir: Path
	capture_prefix: str
	capture_duration_sec: int
	capture_filesize_kb: int
	capture_files: int
	dry_run: bool
	no_services: bool


def run_cmd(cmd: List[str], dry_run: bool = False, check: bool = True) -> subprocess.CompletedProcess:
	pretty = " ".join(cmd)
	print(f"$ {pretty}")
	if dry_run:
		return subprocess.CompletedProcess(cmd, 0, "", "")
	return subprocess.run(cmd, check=check, text=True, capture_output=True)


def require_root(dry_run: bool) -> None:
	if dry_run:
		return
	if os.geteuid() != 0:
		print("[ERROR] Debes ejecutar este script con sudo/root.")
		sys.exit(1)


def require_binaries(names: List[str], dry_run: bool) -> None:
	missing = [n for n in names if shutil.which(n) is None]
	if missing and not dry_run:
		print("[ERROR] Faltan binarios requeridos:", ", ".join(missing))
		print("Instala paquetes: hostapd dnsmasq tshark iw iproute2 iptables")
		sys.exit(1)


def get_wireless_interfaces() -> List[str]:
	ifaces: List[str] = []
	iw = shutil.which("iw")
	if iw:
		try:
			out = subprocess.run([iw, "dev"], check=True, text=True, capture_output=True).stdout
			for line in out.splitlines():
				line = line.strip()
				if line.startswith("Interface "):
					ifaces.append(line.split()[1])
		except subprocess.CalledProcessError:
			pass

	if ifaces:
		return sorted(set(ifaces))

	net_path = Path("/sys/class/net")
	fallback = []
	for p in net_path.iterdir():
		if (p / "wireless").exists():
			fallback.append(p.name)
	return sorted(set(fallback))


def is_usb_interface(iface: str) -> bool:
	dev_link = Path(f"/sys/class/net/{iface}/device")
	if not dev_link.exists():
		return False
	try:
		resolved = dev_link.resolve()
		return "usb" in str(resolved).lower()
	except OSError:
		return False


def autodetect_ap_iface(preferred: Optional[str]) -> str:
	if preferred:
		return preferred

	wifi_ifaces = get_wireless_interfaces()
	if not wifi_ifaces:
		print("[ERROR] No se detectó ninguna interfaz Wi-Fi.")
		sys.exit(1)

	usb_ifaces = [i for i in wifi_ifaces if is_usb_interface(i)]
	selected = usb_ifaces[0] if usb_ifaces else wifi_ifaces[0]
	print(f"[INFO] Interfaz AP seleccionada: {selected} (USB: {'sí' if selected in usb_ifaces else 'no'})")
	return selected


def autodetect_uplink_iface(preferred: Optional[str], ap_iface: str) -> str:
	if preferred:
		return preferred

	ip = shutil.which("ip")
	if not ip:
		print("[ERROR] No se encontró el comando 'ip'.")
		sys.exit(1)

	try:
		out = subprocess.run([ip, "route", "show", "default"], check=True, text=True, capture_output=True).stdout
		for line in out.splitlines():
			parts = line.split()
			if "dev" in parts:
				dev = parts[parts.index("dev") + 1]
				if dev != ap_iface:
					print(f"[INFO] Interfaz uplink detectada: {dev}")
					return dev
	except subprocess.CalledProcessError:
		pass

	print("[ERROR] No se pudo detectar interfaz uplink. Usa --uplink.")
	sys.exit(1)


def backup_file(path: Path) -> None:
	if path.exists():
		stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
		backup = path.with_suffix(path.suffix + f".bak.{stamp}")
		shutil.copy2(path, backup)
		print(f"[INFO] Backup creado: {backup}")


def write_hostapd(cfg: APConfig) -> None:
	content = f"""interface={cfg.iface}
driver=nl80211
ssid={cfg.ssid}
hw_mode=g
channel={cfg.channel}
ieee80211n=1
wmm_enabled=1
country_code={cfg.country}
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
rsn_pairwise=CCMP
wpa_passphrase={cfg.passphrase}
"""

	if not cfg.dry_run:
		backup_file(HOSTAPD_CONF)
		HOSTAPD_CONF.parent.mkdir(parents=True, exist_ok=True)
		HOSTAPD_CONF.write_text(content, encoding="utf-8")
		print(f"[OK] hostapd config: {HOSTAPD_CONF}")
	else:
		print(f"[DRY-RUN] Escribir {HOSTAPD_CONF}")

	if HOSTAPD_DEFAULT.exists():
		line = f'DAEMON_CONF="{HOSTAPD_CONF}"\n'
		if not cfg.dry_run:
			backup_file(HOSTAPD_DEFAULT)
			text = HOSTAPD_DEFAULT.read_text(encoding="utf-8", errors="ignore")
			lines = text.splitlines()
			replaced = False
			for i, l in enumerate(lines):
				if l.strip().startswith("DAEMON_CONF="):
					lines[i] = line.strip()
					replaced = True
					break
			if not replaced:
				lines.append(line.strip())
			HOSTAPD_DEFAULT.write_text("\n".join(lines) + "\n", encoding="utf-8")
			print(f"[OK] hostapd default: {HOSTAPD_DEFAULT}")
		else:
			print(f"[DRY-RUN] Actualizar {HOSTAPD_DEFAULT}")


def write_dnsmasq(cfg: APConfig) -> None:
	# Extrae red base del CIDR esperado (ej. 192.168.50.1/24 -> 192.168.50.0)
	ip_base = cfg.ap_ip_cidr.split("/")[0].split(".")
	network = f"{ip_base[0]}.{ip_base[1]}.{ip_base[2]}.0"

	content = f"""interface={cfg.iface}
bind-interfaces
domain-needed
bogus-priv
dhcp-range={cfg.dhcp_start},{cfg.dhcp_end},{cfg.dhcp_lease}
dhcp-option=3,{cfg.ap_ip_cidr.split('/')[0]}
dhcp-option=6,{cfg.ap_ip_cidr.split('/')[0]}
address=/gw.local/{cfg.ap_ip_cidr.split('/')[0]}
"""

	if not cfg.dry_run:
		backup_file(DNSMASQ_AP_CONF)
		DNSMASQ_AP_CONF.parent.mkdir(parents=True, exist_ok=True)
		DNSMASQ_AP_CONF.write_text(content, encoding="utf-8")
		print(f"[OK] dnsmasq config: {DNSMASQ_AP_CONF} ({network}/24)")
	else:
		print(f"[DRY-RUN] Escribir {DNSMASQ_AP_CONF}")


def configure_interface_ip(cfg: APConfig) -> None:
	run_cmd(["ip", "link", "set", cfg.iface, "down"], cfg.dry_run)
	run_cmd(["ip", "addr", "flush", "dev", cfg.iface], cfg.dry_run)
	run_cmd(["ip", "addr", "add", cfg.ap_ip_cidr, "dev", cfg.iface], cfg.dry_run)
	run_cmd(["ip", "link", "set", cfg.iface, "up"], cfg.dry_run)


def enable_ip_forward(cfg: APConfig) -> None:
	run_cmd(["sysctl", "-w", "net.ipv4.ip_forward=1"], cfg.dry_run)
	if not cfg.dry_run:
		backup_file(SYSCTL_AP_CONF)
		SYSCTL_AP_CONF.write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
		print(f"[OK] sysctl persistente: {SYSCTL_AP_CONF}")
	else:
		print(f"[DRY-RUN] Escribir {SYSCTL_AP_CONF}")


def ensure_iptables_rule(base_cmd: List[str], add_cmd: List[str], dry_run: bool) -> None:
	if dry_run:
		print(f"$ {' '.join(add_cmd)}")
		return
	check = subprocess.run(base_cmd, text=True, capture_output=True)
	if check.returncode != 0:
		subprocess.run(add_cmd, check=True, text=True, capture_output=True)


def configure_nat(cfg: APConfig) -> None:
	ensure_iptables_rule(
		["iptables", "-t", "nat", "-C", "POSTROUTING", "-o", cfg.uplink_iface, "-j", "MASQUERADE"],
		["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", cfg.uplink_iface, "-j", "MASQUERADE"],
		cfg.dry_run,
	)

	ensure_iptables_rule(
		["iptables", "-C", "FORWARD", "-i", cfg.uplink_iface, "-o", cfg.iface, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
		["iptables", "-A", "FORWARD", "-i", cfg.uplink_iface, "-o", cfg.iface, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
		cfg.dry_run,
	)

	ensure_iptables_rule(
		["iptables", "-C", "FORWARD", "-i", cfg.iface, "-o", cfg.uplink_iface, "-j", "ACCEPT"],
		["iptables", "-A", "FORWARD", "-i", cfg.iface, "-o", cfg.uplink_iface, "-j", "ACCEPT"],
		cfg.dry_run,
	)
	print("[OK] NAT/forward configurado con iptables")


def start_services(cfg: APConfig) -> None:
	if cfg.no_services:
		print("[INFO] Se omitió arranque de servicios (--no-services).")
		return
	run_cmd(["systemctl", "unmask", "hostapd"], cfg.dry_run)
	run_cmd(["systemctl", "enable", "hostapd", "dnsmasq"], cfg.dry_run)
	run_cmd(["systemctl", "restart", "hostapd", "dnsmasq"], cfg.dry_run)


def start_tshark_capture(cfg: APConfig) -> None:
	timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	pcap_file = cfg.capture_dir / f"{cfg.capture_prefix}-{cfg.iface}-{timestamp}.pcapng"
	base_cmd = [
		"tshark",
		"-i",
		cfg.iface,
		"-w",
		str(pcap_file),
		"-b",
		f"duration:{cfg.capture_duration_sec}",
		"-b",
		f"filesize:{cfg.capture_filesize_kb}",
		"-b",
		f"files:{cfg.capture_files}",
	]
	sudo_user = os.environ.get("SUDO_USER")
	cmd = base_cmd
	if not cfg.dry_run and os.geteuid() == 0 and sudo_user and sudo_user != "root":
		cmd = ["sudo", "-u", sudo_user] + base_cmd

	if cfg.dry_run:
		print("$ " + " ".join(cmd))
		return

	cfg.capture_dir.mkdir(parents=True, exist_ok=True)
	if sudo_user:
		run_cmd(["chown", f"{sudo_user}:{sudo_user}", str(cfg.capture_dir)], dry_run=False, check=False)
		run_cmd(["chmod", "775", str(cfg.capture_dir)], dry_run=False, check=False)
	log_file = cfg.capture_dir / f"tshark-{cfg.iface}.log"
	with log_file.open("ab") as log:
		proc = subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)
	print(f"[OK] tshark en background (PID {proc.pid})")
	print(f"[OK] PCAP base: {pcap_file}")
	print(f"[OK] Log tshark: {log_file}")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Configura un AP Wi-Fi USB y captura tráfico con tshark")
	parser.add_argument("--iface", help="Interfaz Wi-Fi para AP (auto si se omite)")
	parser.add_argument("--uplink", help="Interfaz de salida a Internet (auto si se omite)")
	parser.add_argument("--ssid", default="UBU-Edge-AI-Lab")
	parser.add_argument("--passphrase", default="EdgeAI-Lab-2026", help="WPA2 PSK (8-63 chars)")
	parser.add_argument("--channel", type=int, default=6)
	parser.add_argument("--country", default="ES")
	parser.add_argument("--ap-ip", default="192.168.50.1/24", help="IP/CIDR para interfaz AP")
	parser.add_argument("--dhcp-start", default="192.168.50.20")
	parser.add_argument("--dhcp-end", default="192.168.50.200")
	parser.add_argument("--dhcp-lease", default="12h")
	parser.add_argument("--capture-dir", default=str(DEFAULT_CAPTURE_DIR))
	parser.add_argument("--capture-prefix", default="ap-capture")
	parser.add_argument("--capture-duration", type=int, default=300, help="Rotación por duración (s)")
	parser.add_argument("--capture-filesize", type=int, default=102400, help="Rotación por tamaño (KB)")
	parser.add_argument("--capture-files", type=int, default=20, help="Número de ficheros en anillo")
	parser.add_argument("--no-services", action="store_true", help="No iniciar hostapd/dnsmasq")
	parser.add_argument("--dry-run", action="store_true", help="Muestra comandos sin aplicar cambios")
	return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
	if not (8 <= len(args.passphrase) <= 63):
		print("[ERROR] --passphrase debe tener entre 8 y 63 caracteres.")
		sys.exit(1)
	if args.channel < 1 or args.channel > 165:
		print("[ERROR] --channel fuera de rango válido (1-165).")
		sys.exit(1)


def main() -> None:
	args = parse_args()
	validate_args(args)

	require_root(args.dry_run)
	require_binaries(["ip", "iw", "iptables", "systemctl", "hostapd", "dnsmasq", "tshark", "sysctl"], args.dry_run)

	ap_iface = autodetect_ap_iface(args.iface)
	uplink = autodetect_uplink_iface(args.uplink, ap_iface)

	cfg = APConfig(
		iface=ap_iface,
		uplink_iface=uplink,
		ssid=args.ssid,
		passphrase=args.passphrase,
		channel=args.channel,
		country=args.country,
		ap_ip_cidr=args.ap_ip,
		dhcp_start=args.dhcp_start,
		dhcp_end=args.dhcp_end,
		dhcp_lease=args.dhcp_lease,
		capture_dir=Path(args.capture_dir).expanduser().resolve(),
		capture_prefix=args.capture_prefix,
		capture_duration_sec=args.capture_duration,
		capture_filesize_kb=args.capture_filesize,
		capture_files=args.capture_files,
		dry_run=args.dry_run,
		no_services=args.no_services,
	)

	print("[INFO] Iniciando configuración AP...")
	write_hostapd(cfg)
	write_dnsmasq(cfg)
	configure_interface_ip(cfg)
	enable_ip_forward(cfg)
	configure_nat(cfg)
	start_services(cfg)
	start_tshark_capture(cfg)

	print("\n[OK] Configuración completada.")
	print(f"[INFO] AP interface: {cfg.iface}")
	print(f"[INFO] Uplink interface: {cfg.uplink_iface}")
	print(f"[INFO] SSID: {cfg.ssid}")


if __name__ == "__main__":
	main()
