import logging
from PIL import Image, ImageFont
import pwnagotchi
import pwnagotchi.plugins as plugins

class PortraitMode(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '2.0.1'
    __license__ = 'GPL3'
    __description__ = 'Switches to portrait driver and repositions plugin elements.'

    FONT_REGULAR = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
    FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'

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
        self._original_fonts = {}
        self._portrait_fonts = {}
        self._original_plugin_positions = {}
        self._original_plugin_fonts = {}

    def _load_fonts(self):
        self._portrait_fonts = {
            'face':             ImageFont.truetype(self.FONT_BOLD, 35),
            'name':             ImageFont.truetype(self.FONT_BOLD, 14),
            'channel':          ImageFont.truetype(self.FONT_REGULAR, 10),
            'aps':              ImageFont.truetype(self.FONT_REGULAR, 10),
            'uptime':           ImageFont.truetype(self.FONT_REGULAR, 10),
            'friend_name':      ImageFont.truetype(self.FONT_REGULAR, 9),
            'shakes':           ImageFont.truetype(self.FONT_REGULAR, 11),
            'mode':             ImageFont.truetype(self.FONT_BOLD, 11),
            'status':           ImageFont.truetype(self.FONT_REGULAR, 10),
            'ip1':              ImageFont.truetype(self.FONT_REGULAR, 10),
            'lifetime_trained': ImageFont.truetype(self.FONT_REGULAR, 10),
            'memtemp_header':   ImageFont.truetype(self.FONT_REGULAR, 10),
            'memtemp_data':     ImageFont.truetype(self.FONT_REGULAR, 10),
            'sugar_lbl':        ImageFont.truetype(self.FONT_REGULAR, 10),
            'sugar_val':        ImageFont.truetype(self.FONT_REGULAR, 10),
        }

    def on_loaded(self):
        logging.info("[Portrait Mode] Plugin loaded!")

    def on_ui_setup(self, ui):
        try:
            from pwnagotchi.ui.hw.waveshare4portrait import WaveshareV4Portrait

            self._load_fonts()

            self._original_impl = ui._implementation
            self._original_layout = ui._layout
            self._original_width = ui._width
            self._original_height = ui._height

            portrait = WaveshareV4Portrait(pwnagotchi.config)
            portrait.initialize()
            new_layout = portrait.layout()

            ui._implementation = portrait
            ui._layout = new_layout
            ui._width = new_layout['width']
            ui._height = new_layout['height']
            ui._canvas = Image.new('1', (ui._width, ui._height), 0xff)

            elements = ui._state._state
            for key, pos in new_layout.items():
                if key in ('width', 'height', 'status'):
                    continue
                if key in elements and isinstance(pos, (tuple, list)):
                    elements[key].xy = tuple(pos)
                    if key in self._portrait_fonts:
                        self._original_fonts[key] = getattr(elements[key], 'font', None)
                        elements[key].font = self._portrait_fonts[key]

            if 'status' in elements:
                elements['status'].xy = new_layout['status']['pos']
                self._original_fonts['status'] = getattr(elements['status'], 'font', None)
                elements['status'].font = self._portrait_fonts['status']

            self.ready = True
            logging.info("[Portrait Mode] Switched to portrait driver.")

        except Exception as e:
            logging.error(f"[Portrait Mode] Failed: {e}")

    def on_ui_update(self, ui):
        if not self.ready:
            return

        elements = ui._state._state
        for key, pos in self.PORTRAIT_POSITIONS.items():
            if key in elements:
                if key not in self._original_plugin_positions:
                    self._original_plugin_positions[key] = tuple(elements[key].xy)
                    self._original_plugin_fonts[key] = getattr(elements[key], 'font', None)

                if list(elements[key].xy) != list(pos):
                    elements[key].xy = pos
                if key in self._portrait_fonts:
                    elements[key].font = self._portrait_fonts[key]

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
                    if key in self._original_fonts and self._original_fonts[key] is not None:
                        elements[key].font = self._original_fonts[key]

            if 'status' in elements:
                elements['status'].xy = landscape_layout['status']['pos']
                if 'status' in self._original_fonts and self._original_fonts['status'] is not None:
                    elements['status'].font = self._original_fonts['status']

            for key, pos in self._original_plugin_positions.items():
                if key in elements:
                    elements[key].xy = pos
                    if key in self._original_plugin_fonts and self._original_plugin_fonts[key] is not None:
                        elements[key].font = self._original_plugin_fonts[key]

            self._original_fonts.clear()
            self._original_plugin_positions.clear()
            self._original_plugin_fonts.clear()
            self.ready = False
            logging.info("[Portrait Mode] Reverted to landscape.")

        except Exception as e:
            logging.error(f"[Portrait Mode] Failed to revert: {e}")
