import logging
import smbus
import time
import pwnagotchi
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK

class PiSugar3i2c(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.4'
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
            # Capacity Register: 0x2a
            # Status Register: 0x02 (Bit 7 is charging)
            capacity_raw = self._bus.read_byte_data(0x57, 0x2a)
            status = self._bus.read_byte_data(0x57, 0x02)

            # --- 20-SECOND MOVING AVERAGE LOGIC ---
            current_time = time.time()
            self._history.append((current_time, capacity_raw))

            # Prune readings older than 20 seconds
            self._history = [reading for reading in self._history if current_time - reading[0] <= 20]

            # Calculate the average capacity
            avg_capacity = sum(reading[1] for reading in self._history) / len(self._history)
            capacity = int(round(avg_capacity))
            # --------------------------------------

            # Check if charging bit is high
            is_charging = (status & 0x80) != 0

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
