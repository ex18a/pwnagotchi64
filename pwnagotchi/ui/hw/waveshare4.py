import logging
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.hw.base import DisplayImpl
from PIL import Image

class WaveshareV4(DisplayImpl):
    def __init__(self, config):
        super(WaveshareV4, self).__init__(config, 'waveshare_4')
        self._display = None
        self._render_count = 0
        self._last_width = None # Tracks the canvas size to auto-detect toggles!

    def layout(self):
        # BASELINE: Standard Landscape (180). 
        fonts.setup(10, 8, 10, 35, 25, 9)
        self._layout['width'] = 250
        self._layout['height'] = 122
        
        self._layout['face'] = (0, 40)
        self._layout['name'] = (5, 20)
        self._layout['channel'] = (0, 0)
        self._layout['aps'] = (28, 0)
        self._layout['uptime'] = (185, 0)
        self._layout['line1'] = [0, 14, 250, 14]
        self._layout['line2'] = [0, 108, 250, 108]
        self._layout['friend_face'] = (0, 92)
        self._layout['friend_name'] = (40, 94)
        self._layout['shakes'] = (0, 109)
        self._layout['mode'] = (225, 109)
        self._layout['status'] = {
            'pos': (125, 20),
            'font': fonts.status_font(fonts.Medium),
            'max': 20
        }
        return self._layout

    def initialize(self):
        logging.info("initializing waveshare v4 autonomous custom driver")
        from pwnagotchi.ui.hw.libs.waveshare.v4.epd2in13_V4 import EPD
        self._display = EPD()
        self._display.init()
        self._display.Clear(0xFF)

        # Base hardware frame buffer remains anchored at 122x250 portrait bytes
        self._display.displayPartBaseImage(self._display.getbuffer(Image.new('1', (122, 250), 0xFF)))

    def render(self, canvas):
        self._render_count += 1
        width, height = canvas.size
        
        # --- AUTO-DETECT LIVE TOGGLE & FORCE SCREEN WIPE ---
        if self._last_width is not None and self._last_width != width:
            logging.info(f"Driver detected canvas change from {self._last_width} to {width}. Forcing hardware wipe...")
            self._display.Clear(0xFF)
            self._render_count = 1000 # Forces the modulo below to trigger an instant full refresh!
            
        self._last_width = width

        # --- AUTONOMOUS ROTATION MATH ---
        if width == 122:
            # Canvas is already Portrait (Plugin is ON). Pass straight through!
            image = canvas.convert('1')
        else:
            # Canvas is Landscape (Plugin is OFF). Rotate 270 to package into hardware!
            image = canvas.rotate(270, expand=True).convert('1')
            
        buf = self._display.getbuffer(image)

        if self._render_count % 1000 == 0:
            logging.info("Performing full screen refresh...")
            self._display.init()
            self._display.display(buf)
            self._display.displayPartBaseImage(buf) 
        else:
            self._display.displayPartial(buf)

    def clear(self):
        self._display.Clear(0xFF)

