#!/bin/bash

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
