import logging
from PIL import Image
import pwnagotchi
import pwnagotchi.plugins as plugins

class PortraitMode(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '2.0.1'
    __license__ = 'GPL3'
    __description__ = 'Switches to portrait driver and repositions plugin elements.'

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
        self._original_impl = None
        self._original_layout = None
        self._original_width = None
        self._original_height = None

    def on_loaded(self):
        logging.info("[Portrait Mode] Plugin loaded!")

    def on_ui_setup(self, ui):
        try:
            from pwnagotchi.ui.hw.waveshare4portrait import WaveshareV4Portrait

            # Save original state
            self._original_impl = ui._implementation
            self._original_layout = ui._layout
            self._original_width = ui._width
            self._original_height = ui._height

            # Build and initialise portrait driver
            portrait = WaveshareV4Portrait(pwnagotchi.config)
            portrait.initialize()
            new_layout = portrait.layout()

            # Swap driver and canvas dimensions
            ui._implementation = portrait
            ui._layout = new_layout
            ui._width = new_layout['width']
            ui._height = new_layout['height']
            ui._canvas = Image.new('1', (ui._width, ui._height), 0xff)

            # Reposition core elements
            elements = ui._state._state
            for key, pos in new_layout.items():
                if key in ('width', 'height', 'status'):
                    continue
                if key in elements and isinstance(pos, (tuple, list)):
                    elements[key].xy = tuple(pos)

            if 'status' in elements:
                elements['status'].xy = new_layout['status']['pos']
                elements['status'].font = new_layout['status']['font']

            self.ready = True
            logging.info("[Portrait Mode] Switched to portrait driver.")

        except Exception as e:
            logging.error(f"[Portrait Mode] Failed: {e}")

    def on_ui_update(self, ui):
        if not self.ready:
            return

        # Reposition plugin elements whenever they appear
        elements = ui._state._state
        for key, pos in self.PORTRAIT_POSITIONS.items():
            if key in elements:
                if list(elements[key].xy) != list(pos):
                    elements[key].xy = pos

    def on_unload(self, ui):
        if not self.ready:
            return
        try:
            logging.info("[Portrait Mode] Reverting to landscape...")

            from pwnagotchi.ui.hw.waveshare4 import WaveshareV4

            landscape = WaveshareV4(pwnagotchi.config)
            landscape.initialize()
            landscape_layout = landscape.layout()

            ui._implementation = landscape
            ui._layout = landscape_layout
            ui._width = landscape_layout['width']
            ui._height = landscape_layout['height']
            ui._canvas = Image.new('1', (ui._width, ui._height), 0xff)

            elements = ui._state._state
            for key, pos in landscape_layout.items():
                if key in ('width', 'height', 'status'):
                    continue
                if key in elements and isinstance(pos, (tuple, list)):
                    elements[key].xy = tuple(pos)

            if 'status' in elements:
                elements['status'].xy = landscape_layout['status']['pos']
                elements['status'].font = landscape_layout['status']['font']

            self.ready = False
            logging.info("[Portrait Mode] Reverted to landscape.")

        except Exception as e:
            logging.error(f"[Portrait Mode] Failed to revert: {e}")
