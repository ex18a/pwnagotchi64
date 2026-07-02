import logging
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts

class PortraitMode(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '2.0.1'
    __license__ = 'GPL3'
    __description__ = 'Repositions plugin UI elements for portrait mode. Core layout owned by waveshare_4_portrait driver.'

    # Portrait coordinates for all shipped plugin elements
    PORTRAIT_POSITIONS = {
        'ip1':              (0, 140),
        'lifetime_trained': (5, 187),
        'memtemp_header':   (16, 157),
        'memtemp_data':     (16, 167),
        'sugar_lbl':        (70, 3),
        'sugar_val':        (90, 3),
    }

    def __init__(self):
        self.ready = False

    def on_loaded(self):
        logging.info("[Portrait Mode] Plugin loaded!")

    def on_ui_setup(self, ui):
        # Only activate if the driver is actually portrait
        if ui._implementation.name != 'waveshare_4_portrait':
            return
        self.ready = True
        logging.info("[Portrait Mode] Portrait driver detected, plugin element repositioning active.")

    def on_ui_update(self, ui):
        if not self.ready:
            return
        if ui._implementation.name != 'waveshare_4_portrait':
            return

        elements = ui._state._state
        for key, pos in self.PORTRAIT_POSITIONS.items():
            if key in elements:
                if list(elements[key].xy) != list(pos):
                    elements[key].xy = pos

    def on_unload(self, ui):
        self.ready = False
        logging.info("[Portrait Mode] Plugin unloaded.")
