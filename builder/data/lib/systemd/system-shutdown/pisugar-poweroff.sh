#!/bin/bash
# Cuts PiSugar 3's own battery output power, but only on a genuine
# poweroff/halt -- never on reboot/kexec. systemd runs every executable
# file in this directory at the true last moment of shutdown (after
# every filesystem is unmounted), passing which kind of shutdown is
# actually happening as $1 -- see systemd-shutdown(8). This is the only
# point where cutting PiSugar's output reliably works: doing it earlier,
# while the Pi is still alive and communicating over I2C (e.g. from
# inside pwnagotchi itself before calling `pwnagotchi.shutdown()`),
# doesn't stick -- confirmed on-device that PiSugar's output stayed on
# across a full clean shutdown, most likely because PiSugar auto-restores
# output if it sees the Pi still actively talking to it after output was
# disabled.
#
# Register reference (PiSugar's own official implementation):
# https://github.com/PiSugar/pisugar-power-manager-rs/blob/master/pisugar-core/src/pisugar3.rs
#   0x0B = write-protect: write 0x29 to unlock, 0x00 to re-lock
#   0x02 bit 5 = output enable (1 = 5V output on, 0 = off)

case "$1" in
    poweroff|halt)
        ;;
    *)
        # reboot, kexec, or anything else -- leave PiSugar's output alone
        exit 0
        ;;
esac

I2C_BUS=1
I2C_ADDR=0x57

# unlock write protection
i2cset -y "$I2C_BUS" "$I2C_ADDR" 0x0B 0x29 2>/dev/null || exit 0

# read current ctrl1 (register 0x02), clear bit 5 (output enable), write back
ctrl1=$(i2cget -y "$I2C_BUS" "$I2C_ADDR" 0x02 2>/dev/null)
if [ -n "$ctrl1" ]; then
    new_ctrl1=$(( ctrl1 & 0xDF ))  # clear bit 5 -- 0b11011111
    i2cset -y "$I2C_BUS" "$I2C_ADDR" 0x02 "$new_ctrl1" 2>/dev/null
fi

# re-lock write protection
i2cset -y "$I2C_BUS" "$I2C_ADDR" 0x0B 0x00 2>/dev/null

exit 0
