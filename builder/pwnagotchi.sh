#!/bin/bash
set -e

# ==============================================================================
# PHASE 1: INITIAL ENVIRONMENT SETUP
# ==============================================================================
VERSION=$1
HOSTNAME=pwnagotchi
NEW_USER="pwn"
OUTPUT_IMG="dist/pwnagotchi64-${VERSION}.img"
TARBALL="dist/pwnagotchi64-${VERSION}.tar.gz"

if [ -z "$VERSION" ]; then
    echo " [!] ERROR: Usage: $0 <version>"
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
# increase image size by 1GB
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

touch /mnt/boot/firmware/ssh

# DNS Fix for Chroot
mv /mnt/etc/resolv.conf /mnt/etc/resolv.conf.bak
echo "nameserver 8.8.8.8" > /mnt/etc/resolv.conf

echo " [*] Step 3.5: Injecting Pwnagotchi source and assets..."
cp "$TARBALL" /mnt/tmp/
cp -r builder/assets/bettercap /mnt/tmp/bettercap_assets
cp -r builder/assets/networkmanager /mnt/tmp/networkmanager
cp -r builder/assets/bluetooth /mnt/tmp/bluetooth
cp -r builder/assets/system /mnt/tmp/system
cp builder/assets/boot/config.txt /mnt/boot/firmware/config.txt

# ==============================================================================
# PHASE 4: KALI CHROOT ENVIRONMENT
# ==============================================================================
chroot /mnt /bin/bash <<EOF
set -e
export DEBIAN_FRONTEND=noninteractive

echo "  -> [Chroot] Enabling QEMU high-speed I/O..."
echo "force-unsafe-io" > /etc/dpkg/dpkg.cfg.d/force-unsafe-io

echo "  -> [Chroot] PHASE 4.1: Aggressive Base System Purge..."
apt-get purge -y --allow-remove-essential \
    kali-desktop-core kali-desktop-xfce kali-linux-default x11-common kali-linux-headless \
    metasploit-framework firefox-esr openjdk-21-jre-headless postgresql-* mariadb-* \
    llvm-21* llvm-18* gcc-mingw-w64-* mingw-w64-* \
    firmware-nvidia-graphics firmware-amd-graphics firmware-marvell-prestera firmware-iwlwifi firmware-mediatek

echo "  -> [Chroot] PHASE 4.2: Sweeping up orphaned dependencies..."
apt-get autoremove --purge -y
apt-get clean

echo "  -> [Chroot] PHASE 4.3: Updating lean repository list..."
apt-get update -y

echo "  -> [Chroot] PHASE 4.4: Installing core packages..."
apt-get install -y \
    aircrack-ng tcpdump bettercap bettercap-ui bluez-tools jq dphys-swapfile hcxtools \
    python3-pip python3-dev build-essential libpcap-dev libssl-dev libffi-dev fonts-dejavu libglib2.0-dev libdbus-1-dev python3-rpi.gpio python3-smbus \
    python3-torch python3-numpy python3-pandas

echo "  -> [Chroot] Downloading and installing 64-bit Pwngrid engine..."
wget -q "https://github.com/jayofelony/pwngrid/releases/download/v1.11.1/pwngrid-1.11.1-aarch64.zip" -O /tmp/pwngrid_engine.zip
unzip -q /tmp/pwngrid_engine.zip -d /tmp/engine_extract
mv /tmp/engine_extract/pwngrid /usr/bin/pwngrid
chmod +x /usr/bin/pwngrid
rm -rf /tmp/pwngrid_engine.zip /tmp/engine_extract

echo "  -> [Chroot] Enabling I2C hardware modules..."
echo -e "i2c-dev\nbnep" >> /etc/modules

echo "  -> [Chroot] Forcing Kernel Wi-Fi Regulatory Domain to BO (Max TX Power)..."
echo "options cfg80211 ieee80211_regdom=BO" > /etc/modprobe.d/cfg80211_regdomain.conf

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
cp /tmp/bluetooth/bt-wizard /usr/local/bin/bt-wizard
chmod +x /usr/local/bin/bt-wizard

echo "  -> [Chroot] Patching SAP plugin crash in bluetoothd..."
sed -i 's|^ExecStart=.*bluetoothd.*|ExecStart=/usr/libexec/bluetooth/bluetoothd --noplugin=sap|' /lib/systemd/system/bluetooth.service

echo "  -> [Chroot] Unpacking application core..."
mkdir -p /tmp/pwn_source
tar -xzf /tmp/pwnagotchi64-${VERSION}.tar.gz -C /tmp/pwn_source --strip-components=1

echo "  -> [Chroot] Bypassing Debian RECORD conflicts..."
python3 -m pip install --break-system-packages --no-cache-dir --ignore-installed mpmath sympy

echo "  -> [Chroot] Installing unified Python dependencies & Modern AI Environment..."
python3 -m pip install --break-system-packages --no-cache-dir -r /tmp/pwn_source/requirements.txt

echo "  -> [Chroot] Installing Pwnagotchi core..."
python3 -m pip install --break-system-packages --no-deps /tmp/pwnagotchi64-${VERSION}.tar.gz

echo "  -> [Chroot] Configuring Bettercap caplets..."
mkdir -p /usr/share/bettercap/caplets
cp /tmp/bettercap_assets/pwnagotchi-manual.cap /usr/share/bettercap/caplets/
cp /tmp/bettercap_assets/pwnagotchi-auto.cap /usr/share/bettercap/caplets/

chmod +x /usr/bin/pwnagotchi-launcher /usr/bin/bettercap-launcher /usr/bin/monstart /usr/bin/monstop

echo "  -> [Chroot] Pre-creating Pwnagotchi system directories..."
mkdir -p /etc/pwnagotchi/
chmod 755 /etc/pwnagotchi/
echo "  -> [Chroot] Seeding initial config.toml..."
cp /tmp/pwn_source/pwnagotchi/defaults.toml /etc/pwnagotchi/config.toml

echo "  -> [Chroot] Registering systemd network unit configurations..."
systemctl enable bettercap.service
systemctl enable pwnagotchi.service
systemctl enable pwngrid-peer.service

if ! id "$NEW_USER" &>/dev/null; then
    useradd -m -G sudo,video,input,netdev,plugdev -s /bin/bash "$NEW_USER"
fi
echo "$NEW_USER:raspberry" | chpasswd
echo "$NEW_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/010_pwn-nopasswd

echo "# The standard live feed" >> /home/$NEW_USER/.bashrc
echo "alias pwnlog='tail -f -n300 /var/log/pwnagotchi.log | sed --unbuffered \"s/,[[:digit:]]\\\\{3\\\\}\\\\]//g\" | cut -d \" \" -f 2-'" >> /home/$NEW_USER/.bashrc

echo "# crash reader (No formatting destruction)" >> /home/$NEW_USER/.bashrc
echo "alias crashlog='cat /var/log/pwnagotchi_crashes.log'" >> /home/$NEW_USER/.bashrc
echo "alias crashwatch='tail -f /var/log/pwnagotchi_crashes.log'" >> /home/$NEW_USER/.bashrc
chown $NEW_USER:$NEW_USER /home/$NEW_USER/.bashrc

echo "  -> [Chroot] Generating MOTD..."
bash /tmp/system/motd-gen.sh "$HOSTNAME"

echo "  -> [Chroot] Configuring 512MB Swap Space..."
sed -i 's/^CONF_SWAPSIZE=.*$/CONF_SWAPSIZE=512/' /etc/dphys-swapfile
systemctl enable dphys-swapfile.service

echo "  -> [Chroot] Injecting USB Ethernet Gadget modules into cmdline.txt..."
sed -i 's/$/ modules-load=dwc2,g_ether/' /boot/firmware/cmdline.txt

echo "$HOSTNAME" > /etc/hostname
sed -i "s/127.0.1.1.*/127.0.1.1 $HOSTNAME/" /etc/hosts

# Remove the kali motd
sed -i '/if \[ -e \/usr\/bin\/kali-motd \]; then/,/fi/s/^/#/' /etc/profile.d/kali.sh

echo "  -> [Chroot] Final cleanup..."
rm -f /etc/dpkg/dpkg.cfg.d/force-unsafe-io
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
echo " [+] SUCCESS: PWNAGOTCHI64 IMAGE COMPILED "
echo "========================================================================"
