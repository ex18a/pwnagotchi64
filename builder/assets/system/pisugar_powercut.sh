#!/bin/bash
# PiSugar 3 Non-Interactive Setup Script for Chroot

# 1. Create the power-cut utility
cat << 'EOF' > /usr/local/bin/pisugar_powercut.sh
#!/bin/bash
EXPECTED_ID="0x0f"
# Check if device exists at 0x57
if i2cdetect -y 1 | grep -q "57"; then
    CURRENT_ID=$(i2cget -y 1 0x57 0x01)
    if [ "$CURRENT_ID" = "$EXPECTED_ID" ]; then
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
systemctl enable pisugar-powercut.service#!/bin/bash

GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}    PiSugar 3 Power Management    ${NC}"
echo -e "${CYAN}==========================================${NC}"

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[!] Please run this script with sudo:${NC} sudo $0"
  exit 1
fi

echo -e "\n${YELLOW}[*] Phase 1: Creating Power-Cut Script...${NC}"
cat << 'EOF' > /usr/local/bin/pisugar_powercut.sh
#!/bin/bash
EXPECTED_ID="0x0f"
if i2cdetect -y 1 | grep -q "57"; then
    CURRENT_ID=$(i2cget -y 1 0x57 0x01)
    if [ "$CURRENT_ID" = "$EXPECTED_ID" ]; then
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

chmod +x /usr/local/bin/pisugar_powercut.sh

echo -e "${YELLOW}[*] Phase 2: Installing Systemd Service...${NC}"
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

echo -e "${YELLOW}[*] Phase 3: Enabling Service...${NC}"
systemctl daemon-reload
systemctl enable pisugar-powercut.service > /dev/null 2>&1
systemctl start pisugar-powercut.service > /dev/null 2>&1

echo -e "\n${GREEN}[+] PiSugar Power Management Installed!${NC}"
echo -e "${CYAN}------------------------------------------${NC}"
echo -e "Service Status: $(systemctl is-active pisugar-powercut.service)"
echo -e "${CYAN}------------------------------------------${NC}"#!/bin/bash

# Define the expected ID for a PiSugar 3
EXPECTED_ID="0x0f"

# Check if a device exists at 0x57
if i2cdetect -y 1 | grep -q "57"; then
    # Verify the device identity
    CURRENT_ID=$(i2cget -y 1 0x57 0x01)
    
    if [ "$CURRENT_ID" = "$EXPECTED_ID" ]; then
        # It's definitely a PiSugar 3, arm the power cut
        i2cset -y 1 0x57 0x0B 0x29
        i2cset -y 1 0x57 0x09 60
        
        STATUS=$(i2cget -y 1 0x57 0x02)
        NEW_STATUS=$((STATUS & 0xDF))
        i2cset -y 1 0x57 0x02 $NEW_STATUS
        
        i2cset -y 1 0x57 0x0B 0x00
        logger "[PiSugar] Hardware shutdown armed."
    fi
fi
