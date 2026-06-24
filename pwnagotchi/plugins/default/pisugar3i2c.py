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
    __version__ = '1.0.3'
    __description__ = 'Direct I2C PiSugar 3 Plugin with Smoothing'

    def __init__(self):
        self._bus = None
        self._history = [] # Buffer for the 20-second moving average

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
            if capacity <= 10 and not is_charging:
                logging.warning(f"[PiSugar3i2c] Battery at {capacity}%. Triggering safe shutdown...")

                # 1. Tell PiSugar hardware to cut power in 60 seconds
                # This is a safety window; it usually cuts as soon as the Pi halts.
                self._bus.write_byte_data(0x57, 0x0B, 0x29) # Disable write protection
                self._bus.write_byte_data(0x57, 0x09, 60)   # 60 second safety window
                val = self._bus.read_byte_data(0x57, 0x02)
                self._bus.write_byte_data(0x57, 0x02, val & 0b11011111)
                self._bus.write_byte_data(0x57, 0x0B, 0x00) # Re-enable protection

                # 2. Trigger the "Good Night" face
                from pwnagotchi.ui import view
                if view.ROOT:
                    view.ROOT.on_shutdown()

                # 3. Extra sleep so you can see the face before shutdown starts
                time.sleep(10) 

                # 4. Trigger the core software shutdown
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
