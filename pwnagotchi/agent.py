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
        # --- INTERACTION HISTORY DECAY: NEW ---
        self._last_seen = {}     # mac -> last time we actually saw it on the radio
        self._last_decay = {}    # mac -> last time its history count was decremented
        self._history_lock = threading.Lock()
        # ---------------------------------------
        self._handshakes = {}
        self.last_session = LastSession(self._config)
        self.mode = 'auto'

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
        return self._supported_channels

    def setup_events(self):
        logging.info("connecting to %s ...", self.url)

        for tag in self._config['bettercap']['silence']:
            try:
                self.run('events.ignore %s' % tag, verbose_errors=False)
            except Exception:
                pass

    def _reset_wifi_settings(self):
        mon_iface = self._config['main']['iface']
        self.run('set wifi.interface %s' % mon_iface)
        self.run('set wifi.ap.ttl %d' % self._config['personality']['ap_ttl'])
        self.run('set wifi.sta.ttl %d' % self._config['personality']['sta_ttl'])
        self.run('set wifi.rssi.min %d' % self._config['personality']['min_rssi'])
        self.run('set wifi.handshakes.file %s' % self._config['bettercap']['handshakes'])
        self.run('set wifi.handshakes.aggregate false')

    def start_monitor_mode(self):
        mon_iface = self._config['main']['iface']
        mon_start_cmd = self._config['main']['mon_start_cmd']
        restart = not self._config['main']['no_restart']
        has_mon = False

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
                    self.run('!%s' % mon_start_cmd)
                else:
                    logging.info("waiting for monitor interface %s ...", mon_iface)
                    time.sleep(1)

        logging.info("supported channels: %s", self._supported_channels)
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

    def _wait_bettercap(self):
        while True:
            try:
                _s = self.session()
                return
            except Exception:
                logging.info("waiting for bettercap API to be available ...")
                time.sleep(1)

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

        if not channels:
            self._current_channel = 0
            logging.debug("RECON %ds", recon_time)
            self.run('wifi.recon.channel clear')
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
            for ap in s['wifi']['aps']:
                if ap['encryption'] == '' or ap['encryption'] == 'OPEN':
                    continue
                elif ap['hostname'] not in whitelist \
                        and ap['mac'].lower() not in whitelist \
                        and ap['mac'][:8].lower() not in whitelist:
                    if self._filter_included(ap):
                        aps.append(ap)
        except Exception as e:
            logging.exception("Error while getting acces points (%s)", e)

        aps.sort(key=lambda ap: ap['channel'])
        return self.set_access_points(aps)

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

    def _update_handshakes(self, new_shakes=0):
        if new_shakes > 0:
            self._epoch.track(handshake=True, inc=new_shakes)

        tot = utils.total_unique_handshakes(self._config['bettercap']['handshakes'])
        txt = '%d (%d)' % (len(self._handshakes), tot)

        self._view.set('shakes', txt)

        # --- DYNAMIC POSITIONING ---
        try:
            shakes_x, shakes_y = self._view._state._state['shakes'].xy

            if self._view._width == 122:
                pass
            else:
                dynamic_offset = 32 + (len(txt) * 6)
                self._view._state._state['last_pwnd_name'].xy = (shakes_x + dynamic_offset, shakes_y)

        except Exception:
            pass
        # ---------------------------------

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
            s = self.session()
            self._update_uptime(s)
            self._update_advertisement(s)
            self._update_peers()
            self._update_counters()
            self._update_handshakes(0)
            time.sleep(1)

    # --- INTERACTION HISTORY DECAY: NEW ---
    def start_history_decay(self):
        _thread.start_new_thread(self._history_decay_worker, ())

    def _history_decay_worker(self):
        while True:
            time.sleep(HISTORY_DECAY_CHECK_INTERVAL)
            self._decay_history()

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

            if key not in self._handshakes:
                self._handshakes[key] = jmsg
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
        for key, jmsg in self._handshakes.items():
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

    def associate(self, ap, throttle=0):
        if self.is_stale():
            logging.debug("recon is stale, skipping assoc(%s)", ap['mac'])
            return

        throttle = 0.7

        if self._config['personality']['associate'] and self._should_interact(ap['mac']):
            self._view.on_assoc(ap)

            try:
                logging.info("sending association frame to %s (%s %s) on channel %d [%d clients], %d dBm...",
                    ap['hostname'], ap['mac'], ap['vendor'], ap['channel'], len(ap['clients']), ap['rssi'])
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

    def deauth(self, ap, sta, throttle=0):
        if self.is_stale():
            logging.debug("recon is stale, skipping deauth(%s)", sta['mac'])
            return

        throttle = 0.7

        if self._config['personality']['deauth'] and self._should_interact(sta['mac']):
            self._view.on_deauth(sta)

            try:
                logging.info("deauthing %s (%s) from %s (%s %s) on channel %d, %d dBm ...",
                    sta['mac'], sta['vendor'], ap['hostname'], ap['mac'], ap['vendor'], ap['channel'], ap['rssi'])
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
