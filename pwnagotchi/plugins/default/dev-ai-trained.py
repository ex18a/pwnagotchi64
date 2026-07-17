import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
import pwnagotchi.ui.view as view
# NOT "from pwnagotchi.ui.view import BLACK" -- that grabs a static
# snapshot of BLACK at plugin-import time, before View.__init__'s
# ui.display.color-based inversion has run, so it never reflects the
# swap. view.BLACK is looked up fresh every time it's actually used
# below, by which point the inversion has happened.
import json
import os
import logging

class DevAiTrained(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.1.0'
    __description__ = 'Displays lifetime completed training epochs from brain.json'

    def __init__(self):
        self.trained_count = 0

    def on_loaded(self):
        logging.info("dev-ai-trained plugin loaded.")

    def get_completed_epochs(self):
        # Path to the brain file where lifetime stats are stored
        brain_path = '/root/brain.json'
        if os.path.exists(brain_path):
            try:
                with open(brain_path, 'r') as f:
                    data = json.load(f)
                    return data.get('epochs_trained', 0)
            except Exception as e:
                logging.error(f"[dev-ai-trained] Error reading brain.json: {e}")
        return 0

    def on_ui_setup(self, ui):
        # 1. Fetch the initial count once on boot
        self.trained_count = self.get_completed_epochs()

        # 2. Setup the element and push the initial value immediately
        ui.add_element('lifetime_trained', LabeledValue(color=view.BLACK, label='AGE', value=str(self.trained_count),
                                                       position=(110, 90),
                                                       label_font=fonts.Bold, text_font=fonts.Medium))

    def on_epoch(self, agent, epoch, epoch_data):
        # 1. The AI just finished an epoch. Check the new count.
        new_count = self.get_completed_epochs()

        # 2. Only push an update to the screen if the number actually went up
        if new_count != self.trained_count:
            self.trained_count = new_count
            # Ask the agent to directly update the UI state
            agent.view().set('lifetime_trained', str(self.trained_count))

    def on_unload(self, ui):
        with ui._lock:
            try:
                ui.remove_element('lifetime_trained')
            except Exception:
                pass
