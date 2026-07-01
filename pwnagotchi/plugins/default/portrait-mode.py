import logging
from PIL import Image
import pwnagotchi
import pwnagotchi.plugins as plugins

class PortraitMode(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '2.0.0'
    __license__ = 'GPL3'
    __description__ = 'Switches to a native portrait driver. No coordinate fighting.'

    def __init__(self):
        self.ready = False
        self._original_impl = None
        self._original_layout = None
        self._original_width = None
        self._original_height = None

    def on_loaded(self):
        logging.info("[Portrait Mode] Plugin loaded! Hijacking canvas dimensions...")

    def _apply_layout(self, ui, layout):
        """Reposition all state elements to match a new layout."""
        elements = ui._state._state
        for key, pos in layout.items():
            if key in ('width', 'height', 'status'):
                continue
            if key in elements and isinstance(pos, (tuple, list)):
                elements[key].xy = tuple(pos)
        if 'status' in elements and 'status' in layout:
            elements['status'].xy = layout['status']['pos']
            elements['status'].font = layout['status']['font']

    def on_ui_setup(self, ui):
        try:
            from pwnagotchi.ui.hw.waveshare4portrait import WaveshareV4Portrait

            # Save original state
            self._original_impl = ui._implementation
            self._original_layout = ui._layout
            self._original_width = ui._width
            self._original_height = ui._height

            # Build portrait driver
            portrait = WaveshareV4Portrait(pwnagotchi.config)
            portrait.initialize()
            new_layout = portrait.layout()

            # Swap implementation and canvas dimensions
            ui._implementation = portrait
            ui._layout = new_layout
            ui._width = new_layout['width']
            ui._height = new_layout['height']
            ui._canvas = Image.new('1', (ui._width, ui._height), 0xff)

            # Reposition all elements
            self._apply_layout(ui, new_layout)

            self.ready = True
            logging.info("[Portrait Mode] Core and Plugin overrides applied successfully.")

        except Exception as e:
            logging.error(f"[Portrait Mode] Failed to apply layout: {e}")

    def on_unload(self, ui):
        if not self.ready:
            return
        try:
            logging.info("[Portrait Mode] Plugin disabled. Reverting to Landscape...")

            from pwnagotchi.ui.hw.waveshare4 import WaveshareV4

            # Build a fresh landscape driver
            landscape = WaveshareV4(pwnagotchi.config)
            landscape.initialize()
            landscape_layout = landscape.layout()

            # Restore implementation and canvas dimensions
            ui._implementation = landscape
            ui._layout = landscape_layout
            ui._width = landscape_layout['width']
            ui._height = landscape_layout['height']
            ui._canvas = Image.new('1', (ui._width, ui._height), 0xff)

            # Reposition all elements back
            self._apply_layout(ui, landscape_layout)

            self.ready = False
            logging.info("[Portrait Mode] Restored perfect landscape layout.")

        except Exception as e:
            logging.error(f"[Portrait Mode] Failed to revert layout: {e}")
