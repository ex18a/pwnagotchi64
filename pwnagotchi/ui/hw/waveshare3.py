import logging

import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.hw.base import DisplayImpl

# how many partial refreshes to allow before forcing a full one, if not set
# via config -- see ui.display.full_refresh_every
DEFAULT_FULL_REFRESH_EVERY = 300


class WaveshareV3(DisplayImpl):
    def __init__(self, config):
        super(WaveshareV3, self).__init__(config, 'waveshare_3')
        self._display = None
        self._did_first_refresh = False
        self._partial_refresh_count = 0
        try:
            self.full_refresh_every = int(config['ui']['display']['full_refresh_every'])
        except Exception:
            self.full_refresh_every = DEFAULT_FULL_REFRESH_EVERY

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
        logging.info("initializing waveshare v3 display")
        from pwnagotchi.ui.hw.libs.waveshare.v3.epd2in13_V3 import EPD
        self._display = EPD()
        self._display.init()
        self._display.Clear(0xFF)

    def _full_refresh(self, buf):
        self._did_first_refresh = True
        self._partial_refresh_count = 0
        logging.info("Performing full screen refresh...")
        self._display.init()
        self._display.display(buf)
        self._display.displayPartBaseImage(buf)

    def render(self, canvas):
        buf = self._display.getbuffer(canvas)
        # same fade-prevention logic as the portrait drivers (see
        # waveshare3portrait.py for the full explanation) -- this driver
        # used to just partial-refresh forever with no base image ever set
        # and no periodic reset, so it was just as prone to ghosting/grey
        # fade as portrait was before that got fixed, just never addressed
        if not self._did_first_refresh or self._partial_refresh_count >= self.full_refresh_every:
            self._full_refresh(buf)
        else:
            self._partial_refresh_count += 1
            self._display.displayPartial(buf)

    def clear(self):
        #pass
        self._display.Clear(0xFF)
