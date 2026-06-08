import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK
import json
import os
import logging

class DevAiCount(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.1'
    __description__ = 'Displays lifetime epochs trained from brain.json'

    def on_loaded(self):
        logging.info("dev-ai-count plugin loaded.")

    def get_lifetime_epochs(self):
        # Path to the brain file where lifetime stats are stored
        brain_path = '/root/brain.json'
        if os.path.exists(brain_path):
            try:
                with open(brain_path, 'r') as f:
                    data = json.load(f)
                    # Returns the total number of epochs where learning actually occurred
                    return data.get('epochs_trained', 0)
            except Exception as e:
                logging.error(f"[dev-ai-count] Error reading brain.json: {e}")
                return 0
        return 0

    def on_ui_setup(self, ui):
        # Positioned near the bottom, adjust (x, y) as needed for your screen
        ui.add_element('lifetime_train', LabeledValue(color=BLACK, label='AGE', value='0',
                                                       position=(110, 90),
                                                       label_font=fonts.Bold, text_font=fonts.Small))

    def on_ui_update(self, ui):
        # Refresh the count from the file every time the UI updates
        lt_count = self.get_lifetime_epochs()
        ui.set('lifetime_train', str(lt_count))

    def on_unload(self, ui):
        with ui._lock:
            try:
                ui.remove_element('lifetime_train')
            except Exception:
                pass
