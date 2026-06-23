import logging
from PIL import Image, ImageFont, ImageDraw
import pwnagotchi.ui.fonts as fonts
import pwnagotchi.plugins as plugins

class FaceOnly(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.0'
    __license__ = 'GPL3'
    __description__ = 'A minimal Landscape HUD with a massive centered face.'

    def __init__(self):
        self.ready = False
        self.font_bold = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
        self.original_state = {}
        self.face_layout = {}
        self.needs_setup = False

    def on_loaded(self):
        logging.info("[Face Only] Plugin loaded! Preparing UI hijack...")

    def _apply_face_only(self, ui):
        try:
            ui._width = 250
            ui._height = 122
            ui._image = Image.new('1', (250, 122), 255)
            ui._draw = ImageDraw.Draw(ui._image)

            # massive face fontsize
            massive_face = ImageFont.truetype(self.font_bold, 70)

            # THE BANISHMENT DICTIONARY
            # moves uwanted ui elements off the screen to hide them
            self.face_layout = {
                'face': {'xy': (0, 15), 'font': massive_face},
                'name': {'xy': (999, 999)},
                'friend_face': {'xy': (999, 999)},
                'friend_name': {'xy': (999, 999)},
                'status': {'xy': (999, 999)},
                'memtemp_header': {'xy': (999, 999)},
                'memtemp_data': {'xy': (999, 999)},
                'lifetime_trained': {'xy': (999, 999)},
                'blind_val': {'xy': (999, 999)},
                'ip1': {'xy': (999, 999)}
            }

            elements = ui._state._state

            # SWAP AND BANISH
            for key, styling in self.face_layout.items():
                if key in elements:
                    if key not in self.original_state:
                        self.original_state[key] = {
                            'xy': elements[key].xy,
                            'font': getattr(elements[key], 'font', None)
                        }

                    if 'xy' in styling:
                        elements[key].xy = styling['xy']
                    if 'font' in styling:
                        elements[key].font = styling['font']

            logging.info("[Face Only] UI cleared and Face centered successfully.")
            self.needs_setup = False

        except Exception as e:
            logging.error(f"[Face Only] Failed to apply layout: {e}")

    def on_ui_setup(self, ui):
        if ui._width == 122:
            logging.warning("[Face Only] Portrait Mode is active! Waiting in the background until it is disabled...")
            self.needs_setup = True
            return

        self._apply_face_only(ui)

    # ====================================================================
    # THE ENFORCER & STALKER LOOP
    # ====================================================================
    def on_ui_update(self, ui):
        if self.needs_setup:
            if ui._width == 250:
                logging.info("[Face Only] Coast is clear. Portrait Mode is dead. Applying Face layout now!")
                self._apply_face_only(ui)
            return

        if not self.face_layout:
            return

        try:
            elements = ui._state._state
            for key, styling in self.face_layout.items():
                if key in elements:
                    current_xy = list(elements[key].xy)
                    target_xy = list(styling['xy'])

                    if current_xy != target_xy:
                        if key not in self.original_state:
                            self.original_state[key] = {
                                'xy': elements[key].xy,
                                'font': getattr(elements[key], 'font', None)
                            }

                        elements[key].xy = styling['xy']
                        if 'font' in styling:
                            elements[key].font = styling['font']
        except Exception:
            pass
    # ====================================================================

    def on_unload(self, ui):
        if self.needs_setup:
            return

        try:
            logging.info("[Face Only] Plugin disabled. Restoring UI elements...")

            ui._width = 250
            ui._height = 122
            ui._image = Image.new('1', (250, 122), 255)
            ui._draw = ImageDraw.Draw(ui._image)

            elements = ui._state._state

            # RESTORE FROM THE VAULT
            for key, original in self.original_state.items():
                if key in elements:
                    elements[key].xy = original['xy']
                    if original['font'] is not None:
                        elements[key].font = original['font']

            self.original_state.clear()
            self.face_layout.clear()

            logging.info("[Face Only] Restored perfect landscape layout.")

        except Exception as e:
            logging.error(f"[Face Only] Failed to revert layout: {e}")
