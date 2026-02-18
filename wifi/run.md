# Comandos de operación (AP + tshark)

## 1) Detener capturas `tshark`

```bash
# Ver procesos activos
pgrep -fa "tshark -i wlx90de8047828f"

# Detener capturas en esa interfaz
sudo pkill -f "tshark -i wlx90de8047828f"

# Confirmar que no quedan procesos
pgrep -fa "tshark -i wlx90de8047828f"
```

## 2) Iniciar AP + `tshark`

```bash
cd /home/ubu/Documentos/github/ubu-edge-ai-network-security-lab
sudo python3 setting-ap.py --ssid UBU-Edge-AI-Lab --passphrase 'Best12345678'
```

## 3) Monitorear estado y capturas

```bash
# Estado de servicios AP
sudo systemctl status hostapd dnsmasq --no-pager

# Ver proceso tshark
pgrep -fa "tshark -i wlx90de8047828f"

# Ver archivos PCAP generados
ls -lah /home/ubu/Documentos/github/ubu-edge-ai-network-security-lab/pcaps

# Ver log de tshark en tiempo real
sudo tail -f /home/ubu/Documentos/github/ubu-edge-ai-network-security-lab/pcaps/tshark-wlx90de8047828f.log
```

## 4) Monitoreo de clientes conectados al AP (opcional)

```bash
# Eventos de autenticación/asociación en hostapd
sudo journalctl -u hostapd -f

# Eventos DHCP en dnsmasq
sudo journalctl -u dnsmasq -f
```

## 5) Enviar tráfico a Supabase (posterior y tiempo real)

```bash
cd /home/ubu/Documentos/github/ubu-edge-ai-network-security-lab/wifi

# Variables de conexión (ajusta según tu entorno)
export SUPABASE_URL="http://ubuserver:8000"
export SUPABASE_API_KEY="<TU_SUPABASE_KEY>"
```

### 5.1) Modo posterior (desde PCAP ya capturado)

```bash
python3 supabase_tshark_ingest.py \
	--mode file \
	--pcap /home/ubu/Documentos/github/ubu-edge-ai-network-security-lab/wifi/pcaps/ap-capture-wlx90de8047828f-20260218-110953_00002_20260218111454.pcapng \
	--batch-size 200
```

### 5.2) Modo tiempo real (mientras captura en vivo)

```bash
python3 supabase_tshark_ingest.py \
	--mode live \
	--iface wlx90de8047828f \
	--batch-size 200
```

### 5.3) Prueba corta (sin insertar en BD)

```bash
python3 supabase_tshark_ingest.py \
	--mode file \
	--pcap /home/ubu/Documentos/github/ubu-edge-ai-network-security-lab/wifi/pcaps/ap-capture-wlx90de8047828f-20260218-110953_00002_20260218111454.pcapng \
	--limit 50 \
	--dry-run
```

