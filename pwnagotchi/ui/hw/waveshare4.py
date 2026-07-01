import logging
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.hw.base import DisplayImpl
from PIL import Image

class WaveshareV4(DisplayImpl):
    def __init__(self, config):
        super(WaveshareV4, self).__init__(config, 'waveshare_4')
        self._display = None
        self._render_count = 0
        self.bg_color = 0xFF
        try:
            if config['ui']['display']['color'].lower() == 'white':
                self.bg_color = 0x00
        except Exception:
            pass

    def layout(self):
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
        logging.info("initializing waveshare v4 display")
        from pwnagotchi.ui.hw.libs.waveshare.v4.epd2in13_V4 import EPD
        self._display = EPD()
        self._display.init()
        self._display.Clear(self.bg_color)
        try:
            # width=122, height=250 -- PIL Image.new takes (width, height)
            new_image = Image.new('1', (self._display.width, self._display.height), 255)
            buf = self._display.getbuffer(new_image)
            self._display.displayPartBaseImage(buf)
        except Exception as e:
            logging.warning(f"waveshare v4 base image init failed: {e}")
        logging.info("initializing waveshare v4 display done")

    def render(self, canvas):
        self._render_count += 1

        # Canvas arrives as 250x122 landscape -- rotate 270 to get
        # 122x250 portrait which is what the hardware buffer expects
        image = canvas.rotate(270, expand=True).convert('1')
        buf = self._display.getbuffer(image)

        if self._render_count % 1000 == 0:
            # Full hardware refresh every 1000 renders -- clears ghosting
            logging.info("Performing full screen refresh...")
            self._display.init()
            self._display.display(buf)
            self._display.displayPartBaseImage(buf)
        else:
            self._display.displayPartial(buf)

    def clear(self):
        self._display.Clear(self.bg_color)
