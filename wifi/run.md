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

