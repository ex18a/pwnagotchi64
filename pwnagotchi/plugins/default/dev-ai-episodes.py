import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK
import json
import os
import logging

class DevAiEpisodes(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.2'
    __description__ = 'Displays lifetime completed training episodes from brain.json'

    def __init__(self):
        self.ep_count = 0

    def on_loaded(self):
        logging.info("dev-ai-episodes plugin loaded.")

    def get_completed_episodes(self):
        # Path to the brain file where lifetime stats are stored
        brain_path = '/root/brain.json'
        if os.path.exists(brain_path):
            try:
                with open(brain_path, 'r') as f:
                    data = json.load(f)
                    return data.get('episodes_completed', 0)
            except Exception as e:
                logging.error(f"[dev-ai-episodes] Error reading brain.json: {e}")
        return 0

    def on_ui_setup(self, ui):
        # 1. Fetch the initial count once on boot
        self.ep_count = self.get_completed_episodes()
        
        # 2. Setup the element and push the initial value immediately
        ui.add_element('lifetime_episodes', LabeledValue(color=BLACK, label='EPS', value=str(self.ep_count),
                                                       position=(110, 90),
                                                       label_font=fonts.Bold, text_font=fonts.Small))

    def on_epoch(self, agent, epoch, epoch_data):
        # 1. The AI just finished an epoch. Check the new count.
        new_count = self.get_completed_episodes()
        
        # 2. Only push an update to the screen if the episode number actually went up
        if new_count != self.ep_count:
            self.ep_count = new_count
            # Ask the agent to directly update the UI state
            agent.view().set('lifetime_episodes', str(self.ep_count))

    def on_unload(self, ui):
        with ui._lock:
            try:
                ui.remove_element('lifetime_episodes')
            except Exception:
                pass
