#!/bin/bash
set -e

# ==============================================================================
# PHASE 1: INITIAL ENVIRONMENT SETUP
# ==============================================================================
VERSION=$1
HOSTNAME=$2
NEW_USER="pwn"
OUTPUT_IMG="dist/pwnagotchi-${VERSION}-64bit-kali.img"
TARBALL="dist/pwnagotchi-${VERSION}.tar.gz"

if [ -z "$VERSION" ] || [ -z "$HOSTNAME" ]; then
    echo " [!] ERROR: Usage: $0 <version> <hostname>"
    exit 1
fi

echo " [*] Step 1: Installing Host Toolchain..."
apt-get update && apt-get install -y file wget xz-utils parted kpartx qemu-user-static curl unzip e2fsprogs fdisk

# ==============================================================================
# PHASE 2: KALI LINUX IMAGE PROVISIONING
# ==============================================================================
mkdir -p dist

if [ ! -f "dist/base_kali.img" ]; then
    echo " [*] Step 2: Fetching Kali Linux ARM64..."
    wget -q --show-progress "https://kali.download/arm-images/kali-2026.1/kali-linux-2026.1-raspberry-pi-arm64.img.xz" -O base_kali.img.xz
    unxz -c base_kali.img.xz > dist/base_kali.img
    rm base_kali.img.xz
fi

cp dist/base_kali.img "$OUTPUT_IMG"
# Reduced from 4GB to 1GB to prevent massive image bloat
dd if=/dev/zero bs=1M count=1024 >> "$OUTPUT_IMG"
parted "$OUTPUT_IMG" resizepart 2 100%

loop_dev=$(losetup -fP --show "$OUTPUT_IMG")
sleep 2
e2fsck -f "${loop_dev}p2" || true
resize2fs "${loop_dev}p2"

mkdir -p /mnt/boot/firmware
mount "${loop_dev}p2" /mnt
mount "${loop_dev}p1" /mnt/boot/firmware

for dir in /dev /dev/pts /proc /sys /run; do
    mount --bind $dir /mnt$dir
done

# ==============================================================================
# PHASE 3: PRE-CHROOT INJECTION
# ==============================================================================
echo " [*] Step 3: Injecting QEMU and Config..."
cp /usr/bin/qemu-aarch64-static /mnt/usr/bin/
echo "dtparam=spi=on" >> /mnt/boot/firmware/config.txt
echo "dtparam=i2c_arm=on" >> /mnt/boot/firmware/config.txt
echo "dtoverlay=i2c-rtc,ds3231" >> /mnt/boot/firmware/config.txt
touch /mnt/boot/firmware/ssh

# DNS Fix for Chroot
mv /mnt/etc/resolv.conf /mnt/etc/resolv.conf.bak
echo "nameserver 8.8.8.8" > /mnt/etc/resolv.conf

echo " [*] Step 3.5: Injecting Pwnagotchi source and assets..."
cp "$TARBALL" /mnt/tmp/
cp -r builder/assets/bettercap /mnt/tmp/bettercap_assets
cp -r builder/assets/networkmanager /mnt/tmp/networkmanager

# ==============================================================================
# PHASE 4: KALI CHROOT ENVIRONMENT
# ==============================================================================
chroot /mnt /bin/bash <<EOF
set -e
export DEBIAN_FRONTEND=noninteractive

echo "  -> [Chroot] Updating repositories..."
apt-get update -y

echo "  -> [Chroot] Stripping desktop and heavy metapackages..."
apt-get purge -y --allow-remove-essential kali-desktop-core kali-desktop-xfce kali-linux-default x11-common kali-linux-headless

echo "  -> [Chroot] Reclaiming disk space..."
apt-get autoremove --purge -y

echo "  -> [Chroot] Installing required core packages..."
apt-get install -y aircrack-ng tcpdump bettercap bettercap-ui bluez-tools jq dphys-swapfile

echo "  -> [Chroot] Installing Python build dependencies..."
apt-get install -y python3-pip python3-dev build-essential libpcap-dev libssl-dev libffi-dev fonts-dejavu libglib2.0-dev libdbus-1-dev

echo "  -> [Chroot] Injecting NetworkManager scripts..."
cp /tmp/networkmanager/98-bt-gateway /etc/NetworkManager/dispatcher.d/98-bt-gateway
cp /tmp/networkmanager/99-rtc-sync /etc/NetworkManager/dispatcher.d/99-rtc-sync
chmod +x /etc/NetworkManager/dispatcher.d/98-bt-gateway
chmod +x /etc/NetworkManager/dispatcher.d/99-rtc-sync

echo "  -> [Chroot] Locking NetworkManager to ignore WiFi interfaces..."
mkdir -p /etc/NetworkManager/conf.d/
cat << 'NM_EOF' > /etc/NetworkManager/conf.d/99-unmanaged.conf
[keyfile]
unmanaged-devices=type:wifi;interface-name:wlan*;interface-name:mon*;interface-name:usb*
NM_EOF

echo "  -> [Chroot] Installing Bluetooth Tethering Wizard..."
cat << 'BT_EOF' > /usr/local/bin/bt-wizard
#!/bin/bash

GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "\${CYAN}==========================================\${NC}"
echo -e "\${CYAN}   Pwnagotchi Bluetooth Tethering Wizard  \${NC}"
echo -e "\${CYAN}==========================================\${NC}"

if [ "\$EUID" -ne 0 ]; then
  echo -e "\${RED}[!] Please run this script with sudo:\${NC} sudo \$0"
  exit 1
fi

read -p "Enter your phones bluetooth name for this connection (e.g., MyPhone): " BT_NAME
if [ -z "\$BT_NAME" ]; then
    echo -e "\${RED}[!] Connection name cannot be empty. Exiting.\${NC}"
    exit 1
fi

read -p "Enter your phone's Bluetooth MAC Address (e.g., AA:BB:CC:DD:EE:FF): " RAW_MAC
if [ -z "\$RAW_MAC" ]; then
    echo -e "\${RED}[!] MAC Address cannot be empty. Exiting.\${NC}"
    exit 1
fi

BT_MAC=\$(echo "\$RAW_MAC" | tr 'a-z' 'A-Z')

echo -e "\n\${YELLOW}[*] Configuring connection '\${BT_NAME}' for MAC: \${BT_MAC}...\${NC}"

echo -e "\${YELLOW}[*] Adding NetworkManager profile...\${NC}"
nmcli connection add con-name "\$BT_NAME" \
  ifname "*" \
  type bluetooth bt-type panu \
  bluetooth.bdaddr "\$BT_MAC" \
  connection.autoconnect yes \
  connection.autoconnect-retries 0 \
  ipv4.method auto \
  ipv4.dns "8.8.8.8 1.1.1.1" \
  ipv4.route-metric 200 > /dev/null

echo -e "\${YELLOW}[*] Creating bt-agent systemd service...\${NC}"
cat << 'SERVICE_EOF' > /etc/systemd/system/bt-agent.service
[Unit]
Description=Bluetooth Agent (NoInputNoOutput)
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStartPre=/usr/bin/bluetoothctl power on
ExecStartPre=/usr/bin/bluetoothctl discoverable on
ExecStartPre=/usr/bin/bluetoothctl pairable on
ExecStart=/usr/bin/bt-agent -c NoInputNoOutput
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_EOF

echo -e "\${YELLOW}[*] Starting Bluetooth agent service...\${NC}"
systemctl daemon-reload
systemctl enable bt-agent > /dev/null 2>&1
systemctl start bt-agent

echo -e "\${YELLOW}[*] Trusting MAC address \${BT_MAC} in bluetoothctl...\${NC}"
bluetoothctl trust "\$BT_MAC" > /dev/null

echo -e "\n\${GREEN}[+] Setup Complete!\${NC}"
echo -e "\${CYAN}==========================================\${NC}"
echo -e "To finish the connection:"
echo -e "  1. Open Bluetooth settings on your phone."
echo -e "  2. Find 'Pwnagotchi' and tap to Pair (it will succeed automatically)."
echo -e "  3. Turn on 'Bluetooth Tethering' / 'Personal Hotspot' on your phone."
echo -e "  4. Ensure the Pi has permission to use your phone's internet."
echo -e "\${CYAN}==========================================\${NC}"
BT_EOF

chmod +x /usr/local/bin/bt-wizard

sed -i 's|^ExecStart=/usr/lib/bluetooth/bluetoothd$|ExecStart=/usr/lib/bluetooth/bluetoothd --noplugin=sap|' /lib/systemd/system/bluetooth.service

echo "  -> [Chroot] Unpacking application core..."
mkdir -p /tmp/pwn_source
tar -xzf /tmp/pwnagotchi-${VERSION}.tar.gz -C /tmp/pwn_source --strip-components=1

echo "  -> [Chroot] Installing Python dependencies..."
# Use --break-system-packages to bypass PEP 668 on this dedicated appliance image
python3 -m pip install --break-system-packages -r /tmp/pwn_source/requirements.txt
python3 -m pip install --break-system-packages --no-deps /tmp/pwnagotchi-${VERSION}.tar.gz

echo "  -> [Chroot] Configuring Bettercap caplets..."
mkdir -p /usr/local/share/bettercap/caplets
cp /tmp/bettercap_assets/pwnagotchi-manual.cap /usr/local/share/bettercap/caplets/
cp /tmp/bettercap_assets/pwnagotchi-auto.cap /usr/local/share/bettercap/caplets/

# Ensure launcher scripts are executable
chmod +x /usr/bin/pwnagotchi-launcher /usr/bin/bettercap-launcher /usr/bin/monstart /usr/bin/monstop

echo "  -> [Chroot] Pre-creating Pwnagotchi system directories..."
mkdir -p /etc/pwnagotchi/
chmod 755 /etc/pwnagotchi/

echo "  -> [Chroot] Registering systemd network unit configurations..."
systemctl enable bettercap.service
systemctl enable pwnagotchi.service

# Custom User
if ! id "$NEW_USER" &>/dev/null; then
    useradd -m -G sudo,video,input,netdev,plugdev -s /bin/bash "$NEW_USER"
fi
echo "$NEW_USER:raspberry" | chpasswd
echo "$NEW_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/010_pwn-nopasswd

echo "alias pwnlog='tail -f -n300 /var/log/pwna*.log | sed --unbuffered \"s/,[[:digit:]]\\\\{3\\\\}\\\\]//g\" | cut -d \" \" -f 2-'" >> /home/$NEW_USER/.bashrc
chown $NEW_USER:$NEW_USER /home/$NEW_USER/.bashrc

echo "  -> [Chroot] MOTD..."
GREEN=\$(printf '\033[0;32m')
NC=\$(printf '\033[0m')
cat <<MOTD_EOF > /etc/motd
\${GREEN}        (◕‿‿◕) $HOSTNAME

        Hi! I'm a pwnagotchi, please take good care of me!
        Here are some basic things you need to know to raise me properly!

        If you want to change my configuration, use /etc/pwnagotchi/config.toml

        All the configuration options can be found on /etc/pwnagotchi/default.toml,
        but don't change this file because I will recreate it every time I'm restarted!

        you can set up bluetooth connection, use sudo bt-wizard

        I'm managed by systemd. Here are some basic commands.

        If you want to know what I'm doing, you can check my logs with the command
        tail -f /var/log/pwnagotchi.log

        If you want to know if I'm running, you can use
        systemctl status pwnagotchi

        You can restart me using
        systemctl restart pwnagotchi

        But be aware I will go into MANUAL mode when restarted!
        You can put me back into AUTO mode using
        touch /root/.pwnagotchi-auto && systemctl restart pwnagotchi
        \${NC}
MOTD_EOF
sed -i 's/#PrintMotd yes/PrintMotd yes/' /etc/ssh/sshd_config
sed -i 's/PrintMotd no/PrintMotd yes/' /etc/ssh/sshd_config

echo "  -> [Chroot] Configuring 512MB Swap Space..."
sed -i 's/^CONF_SWAPSIZE=.*$/CONF_SWAPSIZE=512/' /etc/dphys-swapfile
systemctl enable dphys-swapfile.service

# Hostname
echo "$HOSTNAME" > /etc/hostname
echo "127.0.1.1 $HOSTNAME" >> /etc/hosts

# Cleanup
echo "  -> [Chroot] Final cache cleanup..."
apt-get clean
rm -rf /tmp/* /var/lib/apt/lists/*
EOF

# Restore DNS
mv /mnt/etc/resolv.conf.bak /mnt/etc/resolv.conf

# ==============================================================================
# PHASE 5: CLEANUP
# ==============================================================================
for dir in /run /sys /proc /dev/pts /dev; do
    umount -l /mnt$dir
done
umount /mnt/boot/firmware
umount /mnt
losetup -d "$loop_dev"

echo "========================================================================"
echo " [+] SUCCESS: KALI-BASED LITE PWNAGOTCHI IMAGE COMPILED "
echo "========================================================================"
