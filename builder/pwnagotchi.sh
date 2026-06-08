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
touch /mnt/boot/firmware/ssh

# DNS Fix for Chroot
mv /mnt/etc/resolv.conf /mnt/etc/resolv.conf.bak
echo "nameserver 8.8.8.8" > /mnt/etc/resolv.conf

echo " [*] Step 3.5: Injecting Pwnagotchi source and assets..."
cp "$TARBALL" /mnt/tmp/
cp -r builder/assets/bettercap /mnt/tmp/bettercap_assets

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
apt-get install -y aircrack-ng tcpdump bettercap bettercap-ui

echo "  -> [Chroot] Installing Python build dependencies..."
apt-get install -y python3-pip python3-dev build-essential libpcap-dev libssl-dev libffi-dev fonts-dejavu libglib2.0-dev libdbus-1-dev

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
