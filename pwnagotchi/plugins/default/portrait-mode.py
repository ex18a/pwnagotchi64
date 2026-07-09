import logging
import time
import tomlkit
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
    CONFIG_PATH = '/etc/pwnagotchi/config.toml'

    # landscape display type -> (module, class) for both the landscape driver
    # itself and its portrait counterpart
    DISPLAY_IMPL = {
        'waveshare_3':          ('pwnagotchi.ui.hw.waveshare3', 'WaveshareV3'),
        'waveshare_3_portrait': ('pwnagotchi.ui.hw.waveshare3portrait', 'WaveshareV3Portrait'),
        'waveshare_4':          ('pwnagotchi.ui.hw.waveshare4', 'WaveshareV4'),
        'waveshare_4_portrait': ('pwnagotchi.ui.hw.waveshare4portrait', 'WaveshareV4Portrait'),
    }
    PORTRAIT_FOR = {'waveshare_3': 'waveshare_3_portrait', 'waveshare_4': 'waveshare_4_portrait'}
    LANDSCAPE_FOR = {v: k for k, v in PORTRAIT_FOR.items()}
    SUPPORTED_DISPLAYS = tuple(DISPLAY_IMPL.keys())

    PORTRAIT_POSITIONS = {
        'ip1':              (0, 19),    # between the top line (y=17) and name (y=30)
        'lifetime_trained': (5, 196),   # just above the channel/aps row (y=207)
        'memtemp_header':   (16, 157),
        'memtemp_data':     (16, 167),
        'sugar_lbl':        (70, 3),
        'sugar_val':        (90, 3),
    }

    def __init__(self):
        self.ready = False
        self._did_swap = False
        self._pending_swap = False
        self._swap_after = None
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

    def _write_display_type(self, display_type):
        try:
            with open(self.CONFIG_PATH, 'r') as f:
                doc = tomlkit.parse(f.read())
            if 'ui' not in doc:
                doc['ui'] = tomlkit.table()
            if 'display' not in doc['ui']:
                doc['ui']['display'] = tomlkit.table()
            doc['ui']['display']['type'] = display_type
            with open(self.CONFIG_PATH, 'w') as f:
                f.write(tomlkit.dumps(doc))
            logging.info(f"[Portrait Mode] Written display type '{display_type}' to config.")
        except Exception as e:
            logging.error(f"[Portrait Mode] Failed to write config: {e}")

    def _safety_check(self):
        display_type = pwnagotchi.config.get('ui', {}).get('display', {}).get('type', '')
        if display_type not in self.SUPPORTED_DISPLAYS:
            logging.error(f"[Portrait Mode] Unsupported display '{display_type}' -- only {', '.join(self.PORTRAIT_FOR.keys())} are supported. Plugin will not activate.")
            return False
        return True

    def _impl_class(self, display_type):
        import importlib
        module_name, class_name = self.DISPLAY_IMPL[display_type]
        module = importlib.import_module(module_name)
        return getattr(module, class_name)

    def _apply_portrait(self, ui):
        try:
            self._load_fonts()

            current_name = ui._implementation.name

            # Already portrait -- booted with portrait driver
            # just apply fonts and positions, no driver swap needed
            if current_name in self.LANDSCAPE_FOR:
                logging.info("[Portrait Mode] Portrait driver already active, applying fonts and positions.")
                self._did_swap = False
                elements = ui._state._state
                new_layout = ui._implementation.layout()
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
                return

            # Booted in landscape -- save state and swap to the matching portrait driver
            portrait_type = self.PORTRAIT_FOR.get(current_name)
            if portrait_type is None:
                logging.error(f"[Portrait Mode] No portrait driver mapped for '{current_name}'.")
                return

            self._original_impl = ui._implementation
            self._original_layout = ui._layout
            self._original_width = ui._width
            self._original_height = ui._height

            portrait_cls = self._impl_class(portrait_type)
            portrait = portrait_cls(pwnagotchi.config)
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

            # Write portrait driver to config for clean next boot
            self._write_display_type(portrait_type)

            self._did_swap = True
            self.ready = True
            logging.info(f"[Portrait Mode] Switched to {portrait_type} driver.")

        except Exception as e:
            logging.error(f"[Portrait Mode] Failed: {e}")

    def on_loaded(self):
        logging.info("[Portrait Mode] Plugin loaded!")

    def on_ui_setup(self, ui):
        if not self._safety_check():
            return

        # Already portrait -- apply immediately, no delay needed
        if ui._implementation.name in self.LANDSCAPE_FOR:
            self._apply_portrait(ui)
            return

        # Landscape -- schedule swap after 5 seconds so landscape
        # has time to fully initialise before we take over
        self._pending_swap = True
        self._swap_after = time.time() + 5
        logging.info("[Portrait Mode] Landscape detected, portrait swap scheduled in 5 seconds.")

    def on_ui_update(self, ui):
        # Handle pending delayed swap
        if self._pending_swap and time.time() >= self._swap_after:
            self._pending_swap = False
            self._apply_portrait(ui)
            return

        if not self.ready:
            return

        # Reposition and refont plugin elements
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
            if self._did_swap:
                # Booted in landscape, swapped this session -- restore saved state
                landscape_type = self._original_impl.name
                logging.info(f"[Portrait Mode] Reverting to {landscape_type} (restoring saved state)...")

                landscape_cls = self._impl_class(landscape_type)
                landscape = landscape_cls(pwnagotchi.config)
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

                self._write_display_type(landscape_type)

            else:
                # Booted in portrait -- write landscape to config and restart cleanly
                landscape_type = self.LANDSCAPE_FOR.get(ui._implementation.name, 'waveshare_4')
                logging.info(f"[Portrait Mode] Booted in portrait, writing {landscape_type} to config and restarting...")
                self._write_display_type(landscape_type)
                import os
                os.system('systemctl restart pwnagotchi')
                return

            self._original_fonts.clear()
            self._original_plugin_positions.clear()
            self._original_plugin_fonts.clear()
            self._did_swap = False
            self.ready = False
            logging.info("[Portrait Mode] Reverted to landscape.")

        except Exception as e:
            logging.error(f"[Portrait Mode] Failed to revert: {e}")
