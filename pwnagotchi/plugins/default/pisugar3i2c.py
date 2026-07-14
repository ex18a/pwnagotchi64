import logging
import smbus
import time
import pwnagotchi
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK

# PiSugar 3's own firmware capacity estimate (register 0x2A) is voltage-
# based but not calibrated for this device's actual load -- confirmed via a
# full logged 100%->0% discharge (builder/data/usr/bin/pwnagotchi-battery-
# curve-log): it spent 224 of the run's 285 total minutes (79%) reporting
# 100-60%, then collapsed through the remaining 60%-0% in the last 61
# minutes. Real remaining runtime is nowhere near proportional to that
# reported percentage. Built directly from that same logged run: percent is
# assigned by *elapsed test time* rather than trusting the chip's own
# capacity register, then binned by voltage and isotonic-regressed to force
# monotonicity, giving a curve where percent actually tracks remaining
# runtime under this device's real load instead of the chip's raw voltage
# curve. Re-derive this table if the load profile changes significantly
# (e.g. a different HAT/battery, or major power-draw changes).
#
# Top breakpoint deliberately set to 4180mV, not the true observed peak
# (~4350mV) -- confirmed on-device a fully-charged/plugged-in battery's
# instantaneous voltage reading is noisy and regularly dips as low as
# ~4150-4180mV even while genuinely full, which flickered the displayed
# percentage between 99/100 with a higher cutoff. 4180mV sits comfortably
# below that noise floor, so once actually full it reads a stable 100%.
VOLTAGE_TO_PERCENT = [
    (3100, 0), (3150, 0), (3200, 0), (3250, 1), (3300, 1), (3350, 2),
    (3400, 3), (3450, 4), (3500, 5), (3550, 7), (3600, 10), (3650, 14),
    (3700, 21), (3750, 31), (3800, 45), (3850, 55), (3900, 63), (3950, 69),
    (4000, 77), (4050, 81), (4100, 87), (4150, 95), (4180, 100),
]

# Built the same way as VOLTAGE_TO_PERCENT (elapsed-time-based percent,
# binned by voltage, isotonic-regressed for monotonicity), but from a
# logged charge cycle instead of a discharge one -- confirmed on-device
# charging voltage rises much faster than actual stored charge (CC/CV
# charging behavior + internal resistance), so applying the discharge
# curve while plugged in overshoots badly. Only covers the clean initial
# climb-to-full segment of that log (the following ~16h plugged in
# afterward wasn't a clean reference: pwnagotchi/bettercap load competing
# with trickle-charge input caused it to repeatedly dip and reclimb, since
# the charging bit reflects "USB power present", not "net gaining charge").
# 3720-3960mV is a straight-line interpolation, not directly measured --
# the logger's 30s sample interval happened to land in a gap there during
# the fast constant-current phase. Re-derive if the charger/battery changes.
CHARGING_VOLTAGE_TO_PERCENT = [
    (3560, 0), (3600, 1), (3680, 2), (3700, 2), (3720, 4), (3740, 8),
    (3760, 11), (3780, 14), (3800, 18), (3820, 21), (3840, 24), (3860, 28),
    (3880, 31), (3900, 34), (3920, 38), (3940, 41), (3960, 45), (3980, 48),
    (4000, 53), (4040, 57), (4060, 61), (4080, 65), (4100, 69), (4120, 73),
    (4140, 80), (4160, 90), (4180, 100),
]

def _interp_table(table, mv):
    if mv <= table[0][0]:
        return table[0][1]
    if mv >= table[-1][0]:
        return table[-1][1]
    for (mv0, p0), (mv1, p1) in zip(table, table[1:]):
        if mv0 <= mv <= mv1:
            frac = (mv - mv0) / (mv1 - mv0)
            return p0 + frac * (p1 - p0)

def _voltage_to_percent(mv, is_charging):
    return _interp_table(CHARGING_VOLTAGE_TO_PERCENT if is_charging else VOLTAGE_TO_PERCENT, mv)

class PiSugar3i2c(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.7'
    __description__ = 'Direct I2C PiSugar 3 Plugin with Smoothing'

    def __init__(self):
        self._bus = None
        self._history = [] # Buffer for the 20-second moving average
        self._shutdown_triggered = False

    def on_loaded(self):
        try:
            # Open I2C bus 1
            self._bus = smbus.SMBus(1)
            logging.info("[PiSugar3i2c] Direct I2C connection established.")
        except Exception as e:
            logging.error(f"[PiSugar3i2c] Could not open I2C bus: {e}")

    def on_ui_setup(self, ui):
        ui.add_element(
            "sugar_lbl",
            LabeledValue(
                color=BLACK,
                label="",
                value="BAT",
                position=(ui.width() / 2 + 5, 0),
                label_font=fonts.Bold,
                text_font=fonts.Bold,
            ),
        )
        ui.add_element(
            "sugar_val",
            LabeledValue(
                color=BLACK,
                label="",
                value="0%",
                position=(ui.width() / 2 + 25, 0),
                label_font=fonts.Bold,
                text_font=fonts.Medium,
            ),
        )

    def on_ui_update(self, ui):
        if 'sugar_lbl' not in ui._state._state or self._bus is None:
            return

        try:
            # PiSugar 3 Address: 0x57
            # Voltage Registers: 0x22 (high byte) / 0x23 (low byte)
            # Status Register: 0x02 (Bit 7 is charging)
            vh = self._bus.read_byte_data(0x57, 0x22)
            vl = self._bus.read_byte_data(0x57, 0x23)
            status = self._bus.read_byte_data(0x57, 0x02)

            millivolts = (vh << 8) | vl
            is_charging = (status & 0x80) != 0
            capacity_raw = _voltage_to_percent(millivolts, is_charging)

            # --- 20-SECOND MOVING AVERAGE LOGIC ---
            current_time = time.time()
            self._history.append((current_time, capacity_raw))

            # Prune readings older than 20 seconds
            self._history = [reading for reading in self._history if current_time - reading[0] <= 20]

            # Calculate the average capacity
            avg_capacity = sum(reading[1] for reading in self._history) / len(self._history)
            capacity = int(round(avg_capacity))
            # --------------------------------------

            ui.set('sugar_lbl', "CHG" if is_charging else "BAT")
            ui.set('sugar_val', f"{capacity}%")

            # --- SAFE SHUTDOWN LOGIC ---
            # Actually cutting PiSugar's own output power happens separately,
            # via a systemd system-shutdown hook (builder/data/lib/systemd/
            # system-shutdown/pisugar-poweroff.sh) -- that's the only point
            # where it reliably works: it runs at the true last moment of a
            # genuine poweroff (after everything is unmounted), and systemd
            # tells shutdown apart from reboot natively. Doing the I2C cut
            # from here, while the Pi is still fully alive, doesn't stick --
            # confirmed on-device that PiSugar's output stayed on across a
            # full clean shutdown, most likely because PiSugar auto-restores
            # output if it sees the Pi still actively talking to it over I2C
            # after output was disabled. So this just needs to trigger a
            # normal OS shutdown; the hook takes care of the rest.
            shutdown_pct = self.options.get('low_battery_shutdown_pct', 10)
            if capacity <= shutdown_pct and not is_charging and not self._shutdown_triggered:
                self._shutdown_triggered = True
                logging.warning(f"[PiSugar3i2c] Battery at {capacity}% (threshold {shutdown_pct}%). Triggering safe shutdown...")

                # Trigger the "Good Night" face
                from pwnagotchi.ui import view
                if view.ROOT:
                    view.ROOT.on_shutdown()

                # Extra sleep so you can see the face before shutdown starts
                time.sleep(10)

                pwnagotchi.shutdown()
            # ----------------------------------

        except Exception as e:
            logging.debug(f"[PiSugar3i2c] I2C Read Error: {e}")

    def on_unload(self, ui):
        with ui._lock:
            for element in ["bat", "bat_lbl", "bat_val", "sugar_lbl", "sugar_val"]:
                try:
                    ui.remove_element(element)
                except:
                    pass
