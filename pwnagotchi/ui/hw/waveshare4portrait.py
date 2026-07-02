import logging
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.hw.base import DisplayImpl
from PIL import Image

class WaveshareV4Portrait(DisplayImpl):
    def __init__(self, config):
        super(WaveshareV4Portrait, self).__init__(config, 'waveshare_4_portrait')
        self._display = None
        self._render_count = 0
        self.bg_color = 0xFF
        try:
            if config['ui']['display']['color'].lower() == 'white':
                self.bg_color = 0x00
        except Exception:
            pass

    def layout(self):
        fonts.setup(10, 8, 10, 35, 14, 9)
        self._layout['width'] = 122
        self._layout['height'] = 250
        self._layout['face'] = (0, 85)
        self._layout['name'] = (13, 25)
        self._layout['channel'] = (5, 207)
        self._layout['aps'] = (40, 207)
        self._layout['uptime'] = (3, 3)
        self._layout['line1'] = [0, 17, 125, 17]
        self._layout['line2'] = [0, 221, 125, 221]
        self._layout['friend_face'] = (85, 128)
        self._layout['friend_name'] = (4, 130)
        self._layout['shakes'] = (3, 223)
        self._layout['mode'] = (93, 223)
        self._layout['status'] = {
            'pos': (4, 45),
            'font': fonts.status_font(fonts.Medium),
            'max': 20
        }
        return self._layout

    def initialize(self):
        logging.info("initializing waveshare v4 portrait driver")
        from pwnagotchi.ui.hw.libs.waveshare.v4.epd2in13_V4 import EPD
        self._display = EPD()
        self._display.init()
        self._display.Clear(self.bg_color)
        logging.info("initializing waveshare v4 portrait driver done")

    def render(self, canvas):
        self._render_count += 1
        buf = self._display.getbuffer(canvas)

        if self._render_count % 1000 == 0:
            logging.info("Performing full screen refresh...")
            self._display.init()
            self._display.display(buf)
            self._display.displayPartBaseImage(buf)
        else:
            self._display.displayPartial(buf)

    def clear(self):
        self._display.Clear(self.bg_color)
