import time
import logging
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.hw.base import DisplayImpl
from PIL import Image

# safety net for manual mode only: channel never becomes '*' there, so
# _epoch_started() never fires and the screen would otherwise never get a
# full refresh at all. Auto/ai keep using the epoch-count trigger untouched.
FULL_REFRESH_INTERVAL = 15 * 60

class WaveshareV4Portrait(DisplayImpl):
    def __init__(self, config):
        super(WaveshareV4Portrait, self).__init__(config, 'waveshare_4_portrait')
        self._display = None
        self._last_channel = None
        self._epoch_count = 0
        self._did_first_refresh = False
        self._last_full_refresh = time.time()
        self.bg_color = 0xFF
        try:
            if config['ui']['display']['color'].lower() == 'white':
                self.bg_color = 0x00
        except Exception:
            pass

    def layout(self):
        fonts.setup(10, 8, 10, 35, 25, 9)
        self._layout['width'] = 122
        self._layout['height'] = 250
        self._layout['face'] = (0, 90)
        self._layout['name'] = (4, 25)   # aligned with status's x so the two columns line up
        self._layout['channel'] = (0, 207)
        self._layout['aps'] = (40, 207)
        self._layout['uptime'] = (3, 3)
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

    def _epoch_started(self):
        try:
            import pwnagotchi.ui.view as view_module
            root = view_module.ROOT
            if root is None:
                return False
            current_channel = root.get('channel')
        except Exception:
            return False

        started = current_channel == '*' and self._last_channel != '*'
        self._last_channel = current_channel

        if started:
            self._epoch_count += 1

        # Full refresh every 3rd epoch
        return started and self._epoch_count % 3 == 0

    def _is_manual_mode(self):
        try:
            import pwnagotchi.ui.view as view_module
            root = view_module.ROOT
            if root is None:
                return False
            return root.get('mode') == 'MANU'
        except Exception:
            return False

    def render(self, canvas):
        buf = self._display.getbuffer(canvas)
        # call unconditionally so its epoch-tracking side effects stay in sync,
        # but the very first render always gets a full refresh regardless of what
        # it returns -- otherwise the base image partial refreshes diff against
        # is never properly set, and the screen stays washed out/ghosted until
        # the epoch-count condition eventually triggers a real one
        epoch_wants_refresh = self._epoch_started()

        # manual mode never sets channel to '*', so _epoch_started() can never
        # fire there -- fall back to a time-based refresh, but only in manual
        # mode; auto/ai keep relying on the epoch-count trigger exactly as before
        manual_wants_refresh = (
            self._is_manual_mode()
            and time.time() - self._last_full_refresh >= FULL_REFRESH_INTERVAL
        )

        if not self._did_first_refresh or epoch_wants_refresh or manual_wants_refresh:
            self._did_first_refresh = True
            self._last_full_refresh = time.time()
            logging.info("Performing full screen refresh...")
            self._display.init()
            self._display.display(buf)
            self._display.displayPartBaseImage(buf)
        else:
            self._display.displayPartial(buf)

    def clear(self):
        self._display.Clear(self.bg_color)
