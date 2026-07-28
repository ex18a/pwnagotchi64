#!/bin/bash
case "$1" in
    poweroff|halt)
        ;;
    *)
        exit 0
        ;;
esac

I2C_BUS=1
I2C_ADDR=0x57

i2cset -y "$I2C_BUS" "$I2C_ADDR" 0x0B 0x29 2>/dev/null || exit 0

ctrl1=$(i2cget -y "$I2C_BUS" "$I2C_ADDR" 0x02 2>/dev/null)
if [ -n "$ctrl1" ]; then
    new_ctrl1=$(( ctrl1 & 0xDF ))
    i2cset -y "$I2C_BUS" "$I2C_ADDR" 0x02 "$new_ctrl1" 2>/dev/null
fi

i2cset -y "$I2C_BUS" "$I2C_ADDR" 0x0B 0x00 2>/dev/null

exit 0
