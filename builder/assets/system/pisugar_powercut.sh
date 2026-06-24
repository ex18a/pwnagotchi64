#!/bin/bash
# PiSugar 3 Non-Interactive Setup Script for Chroot

# 1. Create the power-cut utility script
cat << 'EOF' > /usr/local/bin/pisugar_powercut.sh
#!/bin/bash
EXPECTED_ID="0x0f"
# Check if device exists at 0x57
if i2cdetect -y 1 | grep -q "57"; then
    CURRENT_ID=$(i2cget -y 1 0x57 0x01)
    if [ "$CURRENT_ID" = "$EXPECTED_ID" ]; then
        # Disable write protection and arm power cut
        i2cset -y 1 0x57 0x0B 0x29
        i2cset -y 1 0x57 0x09 60
        STATUS=$(i2cget -y 1 0x57 0x02)
        NEW_STATUS=$((STATUS & 0xDF))
        i2cset -y 1 0x57 0x02 $NEW_STATUS
        i2cset -y 1 0x57 0x0B 0x00
        logger "[PiSugar] Hardware shutdown armed."
    fi
fi
EOF

# Set permissions
chmod +x /usr/local/bin/pisugar_powercut.sh

# 2. Create the Systemd service file
cat << 'SERVICE_EOF' > /etc/systemd/system/pisugar-powercut.service
[Unit]
Description=Cut PiSugar power on shutdown
DefaultDependencies=no
Before=shutdown.target poweroff.target reboot.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/pisugar_powercut.sh

[Install]
WantedBy=shutdown.target poweroff.target reboot.target
SERVICE_EOF

# 3. Enable the service
systemctl daemon-reload
systemctl enable pisugar-powercut.service
