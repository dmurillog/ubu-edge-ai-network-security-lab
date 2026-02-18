Listo. Ya te dejé un script completo en setting-ap.py que:

Detecta automáticamente la interfaz Wi‑Fi, priorizando la USB.
Detecta interfaz de salida (uplink) por ruta por defecto.
Configura AP con hostapd (SSID, canal, país, WPA2).
Configura DHCP con dnsmasq.
Asigna IP estática al AP.
Activa ip_forward y NAT con iptables.
Arranca hostapd y dnsmasq.
Lanza tshark en background con rotación de PCAPs (duración, tamaño y número de archivos).
Uso recomendado:

Prueba sin aplicar cambios:

sudo python3 [setting-ap.py](http://_vscodecontentref_/1) --dry-run
Ejecución real:

sudo python3 [setting-ap.py](http://_vscodecontentref_/2) --ssid UBU-LAB-AP --passphrase 'TuClaveSegura123'
Si quieres forzar interfaces:

sudo python3 [setting-ap.py](http://_vscodecontentref_/3) --iface wlan1 --uplink eth0
Si quieres, en el siguiente paso te preparo una versión con archivo .env/YAML para no pasar parámetros por consola y dejarlo listo para integración posterior con InfluxDB.



ubu@ubuserver:~/Documentos/github/ubu-edge-ai-network-security-lab$ sudo systemctl status hostapd dnsmasq --no-pager
● hostapd.service - Access point and authentication server for Wi-Fi and Ethernet
     Loaded: loaded (/usr/lib/systemd/system/hostapd.service; enabled; preset: enabled)
     Active: active (running) since Wed 2026-02-18 10:18:20 CET; 1min 41s ago
       Docs: man:hostapd(8)
    Process: 132011 ExecStart=/usr/sbin/hostapd -B -P /run/hostapd.pid $DAEMON_OPTS ${DAEMON_CONF} (code=exited, status=0/SUCCESS)
   Main PID: 132043 (hostapd)
      Tasks: 1 (limit: 18674)
     Memory: 1.0M (peak: 1.7M)
        CPU: 21ms
     CGroup: /system.slice/hostapd.service
             └─132043 /usr/sbin/hostapd -B -P /run/hostapd.pid /etc/hostapd/hostapd.conf

feb 18 10:18:20 ubuserver systemd[1]: Starting hostapd.service - Access point and authentication server for Wi-Fi and Ethernet...
feb 18 10:18:20 ubuserver (hostapd)[132011]: hostapd.service: Referenced but unset environment variable evaluates to an empty string:…AEMON_OPTS
feb 18 10:18:20 ubuserver hostapd[132011]: wlx90de8047828f: interface state UNINITIALIZED->COUNTRY_UPDATE
feb 18 10:18:20 ubuserver hostapd[132011]: wlx90de8047828f: interface state COUNTRY_UPDATE->ENABLED
feb 18 10:18:20 ubuserver hostapd[132011]: wlx90de8047828f: AP-ENABLED
feb 18 10:18:20 ubuserver systemd[1]: Started hostapd.service - Access point and authentication server for Wi-Fi and Ethernet.
feb 18 10:19:26 ubuserver hostapd[132043]: wlx90de8047828f: STA 78:c5:f8:cd:4f:90 IEEE 802.11: authenticated
feb 18 10:19:27 ubuserver hostapd[132043]: wlx90de8047828f: STA 78:c5:f8:cd:4f:90 IEEE 802.11: associated (aid 1)
feb 18 10:19:27 ubuserver hostapd[132043]: wlx90de8047828f: STA 78:c5:f8:cd:4f:90 RADIUS: starting accounting session 24E136EC4ACFE84F
feb 18 10:19:27 ubuserver hostapd[132043]: wlx90de8047828f: STA 78:c5:f8:cd:4f:90 WPA: pairwise key handshake completed (RSN)

● dnsmasq.service - dnsmasq - A lightweight DHCP and caching DNS server
     Loaded: loaded (/usr/lib/systemd/system/dnsmasq.service; enabled; preset: enabled)
     Active: active (running) since Wed 2026-02-18 10:18:20 CET; 1min 41s ago
    Process: 132020 ExecStartPre=/usr/share/dnsmasq/systemd-helper checkconfig (code=exited, status=0/SUCCESS)
    Process: 132025 ExecStart=/usr/share/dnsmasq/systemd-helper exec (code=exited, status=0/SUCCESS)
    Process: 132033 ExecStartPost=/usr/share/dnsmasq/systemd-helper start-resolvconf (code=exited, status=0/SUCCESS)
   Main PID: 132031 (dnsmasq)
      Tasks: 1 (limit: 18674)
     Memory: 1012.0K (peak: 4.5M)
        CPU: 68ms
     CGroup: /system.slice/dnsmasq.service
             └─132031 /usr/sbin/dnsmasq -x /run/dnsmasq/dnsmasq.pid -u dnsmasq -r /run/dnsmasq/resolv.conf -7 /etc/dnsmasq.d,.dpkg-dist,.dpkg-o…

feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: Ignoring duplicate dhcp-option 6
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: Ignoring duplicate dhcp-option 3
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: DHCPDISCOVER(wlx90de8047828f) 78:c5:f8:cd:4f:90
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: DHCPOFFER(wlx90de8047828f) 192.168.50.95 78:c5:f8:cd:4f:90
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: Ignoring duplicate dhcp-option 6
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: Ignoring duplicate dhcp-option 3
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: DHCPREQUEST(wlx90de8047828f) 192.168.50.95 78:c5:f8:cd:4f:90
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: DHCPACK(wlx90de8047828f) 192.168.50.95 78:c5:f8:cd:4f:90 HUAWEI_P30_lite-cf117b625
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: Ignoring duplicate dhcp-option 6
feb 18 10:19:30 ubuserver dnsmasq-dhcp[132031]: Ignoring duplicate dhcp-option 3
Hint: Some lines were ellipsized, use -l to show in full.
ubu@ubuserver:~/Documentos/github/ubu-edge-ai-network-security-lab$ 