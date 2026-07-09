import _thread
import logging
import random
import time
from threading import Lock

from PIL import ImageDraw

import pwnagotchi
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.faces as faces
import pwnagotchi.ui.fonts as fonts
import pwnagotchi.ui.web as web
import pwnagotchi.utils as utils
from pwnagotchi.ui.components import *
from pwnagotchi.ui.state import State
from pwnagotchi.voice import Voice

WHITE = 0xff
BLACK = 0x00
ROOT = None


class View(object):
    def __init__(self, config, impl, state=None):
        global ROOT
        global WHITE, BLACK

        # --- DYNAMIC INVERSION MOD ---
        # Checks the config file to see if we should invert the canvas and text colors
        try:
            if config['ui']['display']['color'].lower() == 'white':
                WHITE = 0x00  # Canvas background becomes Black
                BLACK = 0xff  # Text and lines become White
            else:
                WHITE = 0xff  # Canvas background becomes White
                BLACK = 0x00  # Text and lines become Black
        except Exception:
            pass # Fallback to defaults if the config key is missing
        # -----------------------------

        # setup faces from the configuration in case the user customized them
        faces.load_from_config(config['ui']['faces'])

        self._agent = None
        self._render_cbs = []
        self._config = config
        self._canvas = None
        self._frozen = False
        self._pinned_keys = set()
        self._lock = Lock()
        self._voice = Voice(lang=config['main']['lang'])
        self._implementation = impl
        self._layout = impl.layout()
        self._width = self._layout['width']
        self._height = self._layout['height']
        self._state = State(state={
            'channel': LabeledValue(color=BLACK, label='CH', value='00', position=self._layout['channel'],
                                    label_font=fonts.Bold,
                                    text_font=fonts.Medium),
            'aps': LabeledValue(color=BLACK, label='APS', value='0 (00)', position=self._layout['aps'],
                                label_font=fonts.Bold,
                                text_font=fonts.Medium),

            'uptime': LabeledValue(color=BLACK, label='UP', value='00:00:00', position=self._layout['uptime'],
                                   label_font=fonts.Bold,
                                   text_font=fonts.Medium),

            'line1': Line(self._layout['line1'], color=BLACK),
            'line2': Line(self._layout['line2'], color=BLACK),

            'face': Text(value=faces.SLEEP, position=self._layout['face'], color=BLACK, font=fonts.Huge),

            'friend_face': Text(value=None, position=self._layout['friend_face'], font=fonts.Bold, color=BLACK),
            'friend_name': Text(value=None, position=self._layout['friend_name'], font=fonts.BoldSmall,
                                color=BLACK),

            'name': Text(value='pwnagotchi', position=self._layout['name'], color=BLACK, font=fonts.Bold),

            'status': Text(value=self._voice.default(),
                           position=self._layout['status']['pos'],
                           color=BLACK,
                           font=self._layout['status']['font'],
                           wrap=True,
                           max_length=self._layout['status']['max'],
                           max_lines=self._layout['status'].get('lines', 0)),

            'shakes': LabeledValue(label='PWND ', value='0 (00)', color=BLACK,
                                   position=self._layout['shakes'], label_font=fonts.Bold,
                                   text_font=fonts.Medium),

            'last_pwnd_name': Text(value='', color=BLACK,
                                   position=(self._layout['shakes'][0], self._layout['shakes'][1]),
                                   font=fonts.Medium),

            'mode': Text(value='AUTO', position=self._layout['mode'],
                         font=fonts.Bold, color=BLACK),
        })

        if state:
            for key, value in state.items():
                self._state.set(key, value)

        plugins.on('ui_setup', self)

        if config['ui']['fps'] > 0.0:
            self._ignore_changes = ()
        else:
            logging.warning("ui.fps is 0, the display will only update for major changes")
            self._ignore_changes = ('uptime', 'name')

        # the blinking name cursor used to only run as a side effect of the
        # fps-based refresh loop, which forced e-ink users to raise fps (bad
        # for the display) just to get it. It's its own config now, and
        # forces its own redraw each tick so it works regardless of fps.
        # _ignore_changes must already be set before this starts, since the
        # thread can begin running before __init__ finishes otherwise.
        if config['ui'].get('cursor', True):
            _thread.start_new_thread(self._refresh_handler, ())
        else:
            logging.warning("ui.cursor is disabled, the name cursor will not blink")

        ROOT = self

    def set_agent(self, agent):
        self._agent = agent

    def has_element(self, key):
        self._state.has_element(key)

    def add_element(self, key, elem):
        self._state.add_element(key, elem)

    def remove_element(self, key):
        self._state.remove_element(key)

    def width(self):
        return self._width

    def height(self):
        return self._height

    def on_state_change(self, key, cb):
        self._state.add_listener(key, cb)

    def on_render(self, cb):
        if cb not in self._render_cbs:
            self._render_cbs.append(cb)

    def _name_cursor_frame(self, base_name, cursor_on):
        # Portrait: center the name and pin the cursor to the screen's
        # rightmost character column instead of just trailing the name, so
        # neither one moves as the name/cursor change. The cursor is drawn
        # in its own, smaller font -- the full block glyph is much taller/
        # denser than the surrounding text at the same size, and an e-ink
        # partial refresh visibly kicks back into the row when that much
        # ink toggles right next to it, making the name appear to jitter
        # up/down each time the cursor blinks.
        name_elem = self._state._state.get('name')
        if self._width == 122 and name_elem is not None:
            try:
                # measure the *actual* font currently on the element, not an
                # assumed pixel-per-char constant -- portrait-mode.py swaps
                # this element's font out for its own size after layout()
                # runs, so a hardcoded assumption here silently goes stale
                main_font = name_elem.font
                main_char_px = main_font.getlength('0')
                if main_char_px <= 0:
                    raise ValueError("non-positive char width")
                cursor_font = fonts.BoldSmall
                cursor_px = cursor_font.getlength('█')

                name_x = self._layout['name'][0]
                avail_px = self._width - name_x
                # reserve room for the (smaller) cursor glyph itself, plus a
                # couple spare pixels for its ink bleed, then fit as many
                # main-font columns as remain for the name
                name_avail_px = max(0, avail_px - cursor_px - 2)
                total_cols = max(1, int(name_avail_px // main_char_px))
                pad = max(0, total_cols - len(base_name))
                left = pad // 2
                right = pad - left

                name_elem.suffix_font = cursor_font
                name_elem.suffix = '█' if cursor_on else ''
                return (' ' * left) + base_name + (' ' * right)
            except Exception:
                pass  # fall through to the simple landscape-style framing below

        # landscape (or portrait if measuring the fonts above failed): cursor
        # baked directly into the string, same font as the name, as before
        if name_elem is not None:
            name_elem.suffix = ''
        return (base_name + ' █') if cursor_on else base_name

    def _refresh_handler(self):
        # cursor blink rate is its own setting, independent of fps
        delay = self._config['ui'].get('cursor_interval', 3)
        cursor_on = False
        while True:
            try:
                cursor_on = not cursor_on
                # recover the real name fresh each tick (strip any cursor
                # char and centering padding from last tick) so padding can
                # never compound across iterations
                base_name = self._state.get('name').replace('█', '').strip()
                self.set('name', self._name_cursor_frame(base_name, cursor_on))
                # force=True: bypasses ignore_changes, which normally skips
                # redraws for 'name' alone when fps is 0 -- that's what made
                # the cursor invisible without raising fps in the first place
                self.update(force=True)
            except Exception as e:
                logging.warning("non fatal error while updating view: %s" % e)
            time.sleep(delay)

    def set(self, key, value, force=False):
        if not force and key in self._pinned_keys:
            # something (e.g. a long-running plugin flow) has pinned this key
            # against ordinary writers -- only a force=True write gets through
            return
        if key == 'status':
            if not hasattr(self, '_last_logged_status') or self._last_logged_status != value:
                import logging
                # Flatten multi-line strings so the Web UI log parser doesn't eat the first words!
                safe_log = value.strip().replace('\n', ' | ')
                logging.info(f"[STATUS] {safe_log}")
                self._last_logged_status = value
        self._state.set(key, value)

    def get(self, key):
        return self._state.get(key)

    def pin(self, keys=('face', 'status')):
        # blocks ordinary set() writers from touching these keys until unpin() --
        # meant for a plugin driving a long multi-step flow (e.g. an install) that
        # needs its own status/face sequence to not get stomped by whatever else
        # is happening in the meantime. Callers that need to write while pinned
        # (the thing that pinned it) pass force=True to set().
        self._pinned_keys = set(keys)

    def unpin(self):
        self._pinned_keys = set()

    def on_starting(self):
        self.set('status', self._voice.on_starting() + ("\n(v%s)" % pwnagotchi.display_version()))
        self.set('face', faces.AWAKE)
        self.update()

    def on_ai_ready(self):
        self.set('mode', '  AI')
        self.set('face', faces.HAPPY)
        self.set('status', self._voice.on_ai_ready())
        self.update()

    def on_manual_mode(self, last_session):
        self.set('mode', 'MANU')
        self.set('face', faces.SLEEP if (last_session.epochs > 3 and last_session.handshakes == 0) else faces.HAPPY)
        self.set('status', self._voice.on_last_session_data(last_session))
        self.set('epoch', "%04d" % last_session.epochs)
        self.set('uptime', last_session.duration)
        self.set('channel', '-')
        self.set('aps', "%d" % last_session.associated)
        self.set('shakes', '%d (%s)' % (last_session.handshakes, \
                                        utils.total_unique_handshakes(self._config['bettercap']['handshakes'])))
        self.set_closest_peer(last_session.last_peer, last_session.peers)
        self.update()

    def is_normal(self):
        return self._state.get('face') not in (
            faces.INTENSE,
            faces.COOL,
            faces.BORED,
            faces.HAPPY,
            faces.EXCITED,
            faces.MOTIVATED,
            faces.DEMOTIVATED,
            faces.SMART,
            faces.SAD,
            faces.LONELY)

    def on_keys_generation(self):
        self.set('face', faces.AWAKE)
        self.set('status', self._voice.on_keys_generation())
        self.update()

    def on_normal(self):
        self.set('face', faces.AWAKE)
        self.set('status', self._voice.on_normal())
        self.update()

    def set_closest_peer(self, peer, num_total):
        if peer is None:
            self.set('friend_face', None)
            self.set('friend_name', None)
        else:
            if peer.rssi >= -67:
                num_bars = 4
            elif peer.rssi >= -70:
                num_bars = 3
            elif peer.rssi >= -80:
                num_bars = 2
            else:
                num_bars = 1

            name = '▌' * num_bars
            name += '│' * (4 - num_bars)
            name += ' %s %d (%d)' % (peer.name(), peer.pwnd_run(), peer.pwnd_total())

            if num_total > 1:
                if num_total > 9000:
                    name += ' of over 9000'
                else:
                    name += ' of %d' % num_total

            self.set('friend_face', peer.face())
            self.set('friend_name', name)
        self.update()

    def on_new_peer(self, peer):
        face = ''
        if peer.first_encounter():
            face = random.choice((faces.AWAKE, faces.COOL))
        elif peer.is_good_friend(self._config):
            face = random.choice((faces.MOTIVATED, faces.FRIEND, faces.HAPPY))
        else:
            face = random.choice((faces.EXCITED, faces.HAPPY, faces.SMART))

        self.set('face', face)
        self.set('status', self._voice.on_new_peer(peer))
        self.update()
        time.sleep(3)

    def on_lost_peer(self, peer):
        self.set('face', faces.LONELY)
        self.set('status', self._voice.on_lost_peer(peer))
        self.update()

    def on_free_channel(self, channel):
        self.set('face', faces.SMART)
        self.set('status', self._voice.on_free_channel(channel))
        self.update()

    def on_reading_logs(self, lines_so_far=0):
        self.set('face', faces.SMART)
        self.set('status', self._voice.on_reading_logs(lines_so_far))
        self.update()

    def wait(self, secs, sleeping=True):
        was_normal = self.is_normal()
        part = secs / 10.0

        for step in range(0, 10):
            if was_normal or step > 5:
                if sleeping:
                    if secs > 1:
                        self.set('face', faces.SLEEP)
                        self.set('status', self._voice.on_napping(int(secs)))
                    else:
                        self.set('face', faces.SLEEP2)
                        self.set('status', self._voice.on_awakening())
                else:
                    self.set('status', self._voice.on_waiting(int(secs)))
                    good_mood = self._agent.in_good_mood()
                    if step % 2 == 0:
                        self.set('face', faces.LOOK_R_HAPPY if good_mood else faces.LOOK_R)
                    else:
                        self.set('face', faces.LOOK_L_HAPPY if good_mood else faces.LOOK_L)

            time.sleep(part)
            secs -= part

        self.on_normal()

    def on_shutdown(self):
        self.set('face', faces.SLEEP)
        self.set('status', self._voice.on_shutdown())
        self.update(force=True)
        self._frozen = True

    def on_bored(self):
        self.set('face', faces.BORED)
        self.set('status', self._voice.on_bored())

    def on_blind(self, blind_for):
        self.set('face', faces.BLIND)
        self.set('status', self._voice.on_blind(blind_for))
        self.update()

    def on_sad(self):
        self.set('face', faces.SAD)
        self.set('status', self._voice.on_sad())
        self.update()

    def on_angry(self):
        self.set('face', faces.ANGRY)
        self.set('status', self._voice.on_angry())
        self.update()

    def on_motivated(self, reward):
        self.set('face', faces.MOTIVATED)
        self.set('status', self._voice.on_motivated(reward))
        self.update()

    def on_demotivated(self, reward):
        self.set('face', faces.DEMOTIVATED)
        self.set('status', self._voice.on_demotivated(reward))
        self.update()

    def on_excited(self):
        self.set('face', faces.EXCITED)
        self.set('status', self._voice.on_excited())
        self.update()

    def on_assoc(self, ap):
        self.set('face', faces.INTENSE)
        self.set('status', self._voice.on_assoc(ap))
        self.update()

    def on_deauth(self, sta):
        self.set('face', faces.COOL)
        self.set('status', self._voice.on_deauth(sta))
        self.update()

    def on_miss(self, who):
        self.set('face', faces.SAD)
        self.set('status', self._voice.on_miss(who))
        self.update()

    def on_grateful(self):
        self.set('face', faces.GRATEFUL)
        self.set('status', self._voice.on_grateful())
        self.update()

    def on_lonely(self):
        self.set('face', faces.LONELY)
        self.set('status', self._voice.on_lonely())
        self.update()

    def on_handshakes(self, new_shakes):
        self.set('face', faces.HAPPY)
        self.set('status', self._voice.on_handshakes(new_shakes))
        self.update()

    def on_unread_messages(self, count, total):
        self.set('face', faces.EXCITED)
        self.set('status', self._voice.on_unread_messages(count, total))
        self.update()
        time.sleep(5.0)

    def on_uploading(self, to):
        self.set('face', random.choice((faces.UPLOAD, faces.UPLOAD1, faces.UPLOAD2)))
        self.set('status', self._voice.on_uploading(to))
        self.update(force=True)

    def on_update_available(self, version):
        self.set('status', self._voice.on_update_available(version))
        self.update(force=True)

    # --- the following on_update_* calls all run while automatic-updates has
    # the view pinned (see that plugin), so every write needs force=True to
    # get through. The plain "in progress" stages below leave 'face' alone --
    # the plugin's own animation loop owns it for those -- while the ones with
    # a distinct face (checking/verifying deps, installed/restarting/failed)
    # still set it directly, same as before.

    def on_update_cleaning(self):
        self.set('status', self._voice.on_update_cleaning(), force=True)
        self.update(force=True)

    def on_update_installing(self, version):
        self.set('status', self._voice.on_update_installing(version), force=True)
        self.update(force=True)

    def on_update_downloading(self, version):
        self.set('status', self._voice.on_update_downloading(version), force=True)
        self.update(force=True)

    def on_update_extracting(self, version):
        self.set('status', self._voice.on_update_extracting(version), force=True)
        self.update(force=True)

    def on_update_checking_deps(self):
        self.set('face', faces.SMART, force=True)
        self.set('status', self._voice.on_update_checking_deps(), force=True)
        self.update(force=True)

    def on_update_installing_deps(self):
        self.set('status', self._voice.on_update_installing_deps(), force=True)
        self.update(force=True)

    def on_update_installing_core(self):
        self.set('status', self._voice.on_update_installing_core(), force=True)
        self.update(force=True)

    def on_update_verifying_deps(self):
        self.set('face', faces.SMART, force=True)
        self.set('status', self._voice.on_update_verifying_deps(), force=True)
        self.update(force=True)

    def on_update_installed(self, version):
        self.set('face', faces.COOL, force=True)
        self.set('status', self._voice.on_update_installed(version), force=True)
        self.update(force=True)

    def on_update_restarting(self):
        self.set('face', faces.SLEEP, force=True)
        self.set('status', self._voice.on_update_restarting(), force=True)
        self.update(force=True)

    def on_update_failed(self, version):
        self.set('face', faces.BROKEN, force=True)
        self.set('status', self._voice.on_update_failed(version), force=True)
        self.update(force=True)

    def on_rebooting(self):
        self.set('face', faces.BROKEN)
        self.set('status', self._voice.on_rebooting())
        self.update()

    def on_custom(self, text):
        self.set('face', faces.DEBUG)
        self.set('status', self._voice.custom(text))
        self.update()

    def update(self, force=False, new_data={}):
        for key, val in new_data.items():
            self.set(key, val)

        with self._lock:
            if self._frozen:
                return

            state = self._state
            changes = state.changes(ignore=self._ignore_changes)
            if force or len(changes):
                self._canvas = Image.new('1', (self._width, self._height), WHITE)
                drawer = ImageDraw.Draw(self._canvas)

                plugins.on('ui_update', self)

                for key, lv in state.items():
                    lv.draw(self._canvas, drawer)

                web.update_frame(self._canvas)

                for cb in self._render_cbs:
                    cb(self._canvas)

                self._state.reset()
