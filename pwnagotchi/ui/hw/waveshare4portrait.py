import logging
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.hw.base import DisplayImpl
from PIL import Image

# how many partial refreshes to allow before forcing a full one, if not set
# via config -- see ui.display.full_refresh_every
DEFAULT_FULL_REFRESH_EVERY = 50

class WaveshareV4Portrait(DisplayImpl):
    def __init__(self, config):
        super(WaveshareV4Portrait, self).__init__(config, 'waveshare_4_portrait')
        self._display = None
        self._did_first_refresh = False
        self._partial_refresh_count = 0
        self.bg_color = 0xFF
        try:
            if config['ui']['display']['color'].lower() == 'white':
                self.bg_color = 0x00
        except Exception:
            pass
        try:
            self.full_refresh_every = int(config['ui']['display']['full_refresh_every'])
        except Exception:
            self.full_refresh_every = DEFAULT_FULL_REFRESH_EVERY

    def layout(self):
        fonts.setup(10, 8, 10, 35, 25, 9)
        self._layout['width'] = 122
        self._layout['height'] = 250
        self._layout['face'] = (0, 90)
        self._layout['name'] = (4, 25)   # aligned with status's x so the two columns line up
        self._layout['channel'] = (0, 207)
        self._layout['aps'] = (40, 207)
        self._layout['uptime'] = (0, 3)
        self._layout['line1'] = [0, 17, 125, 17]
        self._layout['line2'] = [0, 221, 125, 221]
        self._layout['friend_face'] = (85, 128)
        self._layout['friend_name'] = (4, 130)
        self._layout['shakes'] = (0, 223)
        self._layout['last_pwnd_name'] = (0, 233)
        self._layout['mode'] = (93, 223)
        self._layout['status'] = {
            'pos': (4, 45),
            'font': fonts.status_font(fonts.Medium),
            'max': 20,
            'lines': 3   # face starts at y=90, only ~45px below status -- cap so long text can't grow into it
        }
        return self._layout

    def initialize(self):
        logging.info("initializing waveshare v4 portrait driver")
        from pwnagotchi.ui.hw.libs.waveshare.v4.epd2in13_V4 import EPD
        self._display = EPD()
        self._display.init()
        self._display.Clear(self.bg_color)
        logging.info("initializing waveshare v4 portrait driver done")

    def _full_refresh(self, buf):
        self._did_first_refresh = True
        self._partial_refresh_count = 0
        logging.info("Performing full screen refresh...")
        self._display.init()
        self._display.display(buf)
        self._display.displayPartBaseImage(buf)

    def render(self, canvas):
        buf = self._display.getbuffer(canvas)
        # the very first render always gets a full refresh -- otherwise the
        # base image partial refreshes diff against is never properly set,
        # and the screen stays washed out/ghosted from the start. After
        # that, partial refresh is fine on its own for a while, but its
        # waveform only strongly drives pixels the controller thinks
        # changed since the base image -- static content (face, name, etc.)
        # gets no reinforcement and gradually fades toward grey over many
        # cycles, so periodically force a real refresh to reset it. Counting
        # actual partial refreshes (rather than epochs, which vary wildly in
        # duration and don't track manual mode at all) ties this directly to
        # how much fade has likely accumulated, regardless of mode.
        if not self._did_first_refresh or self._partial_refresh_count >= self.full_refresh_every:
            self._full_refresh(buf)
        else:
            self._partial_refresh_count += 1
            self._display.displayPartial(buf)

    def clear(self):
        self._display.Clear(self.bg_color)
