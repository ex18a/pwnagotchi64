import logging

import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.hw.base import DisplayImpl


class I2COled(DisplayImpl):
    def __init__(self, config):
        super(I2COled, self).__init__(config, 'i2coled')

    def layout(self):
        fonts.setup(8, 8, 8, 10, 10, 8)
        width = self.config['width'] if 'width' in self.config else 128
        height = self.config['height'] if 'height' in self.config else 64
        self._layout['width'] = width
        self._layout['height'] = height
        self._layout['face'] = (0, 30)
        self._layout['name'] = (0, 10)
        self._layout['channel'] = (72, 10)
        self._layout['aps'] = (0, 0)
        self._layout['uptime'] = (87, 0)
        self._layout['line1'] = [0, 9, width, 9]
        self._layout['line2'] = [0, 54, width, 54]
        self._layout['friend_face'] = (0, 41)
        self._layout['friend_name'] = (40, 43)
        self._layout['shakes'] = (0, 55)
        self._layout['mode'] = (107, 10)
        self._layout['status'] = {
            'pos': (37, 19),
            'font': fonts.status_font(fonts.Small),
            'max': 18
        }
        return self._layout

    def initialize(self):
        i2c_addr = self.config['i2c_addr'] if 'i2c_addr' in self.config else 0x3C
        width = self.config['width'] if 'width' in self.config else 128
        height = self.config['height'] if 'height' in self.config else 64
        logging.info("initializing SSD1306 %dx%d I2C OLED display on address 0x%X" % (width, height, i2c_addr))

        from pwnagotchi.ui.hw.libs.i2coled.oled import OLED
        self._display = OLED(address=i2c_addr, width=width, height=height)
        self._display.Init()
        self._display.Clear()

    def render(self, canvas):
        self._display.display(canvas)

    def clear(self):
        self._display.Clear()
