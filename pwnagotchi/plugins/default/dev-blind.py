import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK
import subprocess
import logging

class BlindCount(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.5'
    __description__ = 'Pulls blind count from log lines containing blind='

    def on_loaded(self):
        self._blind = "0"
        logging.info("[BlindCount] Watcher loaded.")

    def on_ui_setup(self, ui):
        ui.add_element('blind_val', LabeledValue(color=BLACK, label='BLIND ', value='0',
                                                 position=(110, 80),
                                                 label_font=fonts.Bold, text_font=fonts.Medium))

    def on_ui_update(self, ui):
        try:
            # This looks for 'blind=' then grabs the digits immediately following it
            command = "tail -n 25 /var/log/pwnagotchi.log | grep -oP 'blind=\\K\\d+' | tail -n 1"
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, error = process.communicate()

            if output:
                new_val = output.decode('utf-8').strip()
                if new_val:
                    self._blind = new_val

            ui.set('blind_val', str(self._blind))
        except Exception as e:
            logging.debug(f"[BlindCount] Log Read Error: {e}")

    def on_unload(self, ui):
        with ui._lock:
            try:
                ui.remove_element('blind_val')
            except Exception:
                pass
