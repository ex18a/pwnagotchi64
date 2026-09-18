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

HISTORY_DECAY_CHECK_INTERVAL = 60
HISTORY_DECAY_INTERVAL = 30 * 60

FORGET_HANDSHAKE_FILE = '/root/.pwnagotchi-forget'

class Agent(Client, Automata, AsyncAdvertiser, AsyncTrainer):
    def __init__(self, view, config, keypair):
        Client.__init__(self, config['bettercap']['hostname'],
                        config['bettercap']['scheme'],
                        config['bettercap']['port'],
                        config['bettercap']['username'],
                        config['bettercap']['password'])
        self._supported_channels = utils.iface_channels('mon0')
        Automata.__init__(self, config, view, self._supported_channels)
        AsyncAdvertiser.__init__(self, config, view, keypair)
        AsyncTrainer.__init__(self, config)

        self._started_at = time.time()
        self._filter = None if not config['main']['filter'] else re.compile(config['main']['filter'])
        self._current_channel = 0
        self._tot_aps = 0
        self._aps_on_channel = 0
        self._view = view
        self._view.set_agent(self)
        self._web_ui = Server(self, config['ui'])

        self._pending_wait = 0

        self._access_points = []
        self._last_pwnd = None
        self._tot_handshakes_cache = None
        self._history = {}
        self._last_seen = {}
        self._last_decay = {}
        self._history_lock = threading.Lock()
        self._handshakes = {}
        self._handshakes_lock = threading.Lock()
        self.last_session = LastSession(self._config)
        self.mode = 'ai' if config.get('ai', {}).get('enabled', False) else 'auto'
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
        if not self._supported_channels:
            self._supported_channels = utils.iface_channels('mon0')
        return self._supported_channels

    def setup_events(self):
        logging.info("connecting to %s ...", self.url)

        for tag in self._config['bettercap']['silence']:
            try:
                self.run('events.ignore %s' % tag, verbose_errors=False)
            except Exception:
                pass

    def _apply_hop_period(self):
        hop_period = self._config['personality'].get('wifi_hop_period_ms', 1000)
        self.run('set wifi.hop.period %d' % hop_period)

    def _reset_wifi_settings(self):
        self.run('set wifi.interface mon0')
        self.run('set wifi.ap.ttl %d' % self._config['personality']['ap_ttl'])
        self.run('set wifi.sta.ttl %d' % self._config['personality']['sta_ttl'])
        self.run('set wifi.rssi.min %d' % self._config['personality']['min_rssi'])
        self.run('set wifi.handshakes.file %s' % self._config['bettercap']['handshakes'])
        self.run('set wifi.handshakes.aggregate false')

        self._apply_hop_period()

    MAX_MON_START_ATTEMPTS = 5

    def start_monitor_mode(self):
        mon_iface = 'mon0'
        mon_start_cmd = self._config['main']['mon_start_cmd']
        restart = not self._config['main']['no_restart']
        has_mon = False
        failed_attempts = 0

        while has_mon is False:
            s = self.session()
            for iface in s['interfaces']:
                if iface['name'] == mon_iface:
                    logging.info("found monitor interface: %s", iface['name'])
                    try:
                        driver_path = '/sys/class/net/%s/device/driver' % iface['name']
                        driver = os.path.basename(os.path.realpath(driver_path)) if os.path.exists(driver_path) else ''
                        if driver == 'brcmfmac':
                            kind = 'built-in WiFi'
                        elif not driver:
                            kind = 'unknown, %s unavailable' % iface['name']
                        else:
                            kind = 'external WiFi adapter'
                        logging.info("%s is using %s (driver: %s)", iface['name'], kind, driver)
                        if kind == 'external WiFi adapter':
                            self._view.pin(keys=('status',))
                            try:
                                self._view.set('status', 'Using external WiFi adapter\n(driver: %s)' % driver, force=True)
                                self._view.update(force=True)
                                time.sleep(5)
                            finally:
                                self._view.unpin()
                    except Exception:
                        pass
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
                            if pwnagotchi.should_reboot_for_brcm_wedge():
                                logging.critical(
                                    "monitor interface failed to start %d times in a row -- "
                                    "rebooting to clear driver state", failed_attempts)
                                pwnagotchi.reboot(mode='AUTO')
                                return
                            else:
                                logging.error(
                                    "monitor interface failed to start %d times in a row, but "
                                    "reboot budget exhausted -- will keep retrying without "
                                    "rebooting", failed_attempts)
                                failed_attempts = 0
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

    BETTERCAP_WAIT_TIMEOUT = 180

    def _wait_bettercap(self):
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
        self.start_history_decay()
        self.next_epoch()
        self.set_ready()

    def flush_pending_wait(self):
        if self._current_channel != 0 and self._pending_wait > 0:
            logging.info("holding on channel %d for %ds before ending epoch ...",
                         self._current_channel, self._pending_wait)
            self.wait_for(self._pending_wait)
        self._pending_wait = 0

    def recon(self):
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

        try:
            self.run('wifi.recon clear')
        except Exception as e:
            logging.warning("wifi.recon clear failed, mon0/bettercap likely down (%s)", e)

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

    def set_access_points(self, aps, unfiltered_count=0):
        self._access_points = aps

        now = time.time()
        with self._history_lock:
            for ap in aps:
                self._last_seen[ap['mac']] = now
                for sta in ap['clients']:
                    self._last_seen[sta['mac']] = now

        plugins.on('wifi_update', self, aps)
        self._epoch.observe(aps, list(self._peers.values()), unfiltered_count)
        return self._access_points

    def get_access_points(self):
        whitelist = self._config['main']['whitelist']
        home_networks = self._config['main'].get('home_networks', [])
        aps = []
        unfiltered_count = 0
        try:
            s = self.session()
            plugins.on("unfiltered_ap_list", self, s['wifi']['aps'])
            unfiltered_count = len(s['wifi']['aps'])
            self._whitelist_ap_visible = bool(home_networks) and any(
                ap['hostname'] in home_networks or ap['mac'].lower() in home_networks
                or ap['mac'][:8].lower() in home_networks
                for ap in s['wifi']['aps']
            )
            for ap in s['wifi']['aps']:
                if ap['encryption'] == '' or ap['encryption'] == 'OPEN':
                    continue
                elif ap['hostname'] not in whitelist and ap['hostname'] not in home_networks \
                        and ap['mac'].lower() not in whitelist and ap['mac'].lower() not in home_networks \
                        and ap['mac'][:8].lower() not in whitelist and ap['mac'][:8].lower() not in home_networks:
                    if self._filter_included(ap):
                        aps.append(ap)
        except Exception as e:
            if bettercap.EXPECTED_DOWNTIME:
                logging.debug("error while getting access points (expected -- update in progress): %s", e)
            else:
                logging.exception("Error while getting acces points (%s)", e)

        aps.sort(key=lambda ap: ap['channel'])
        return self.set_access_points(aps, unfiltered_count)

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
        secs = int(time.time() - self._started_at)
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
        total_str = str(tot)
        session_str = str(session)
        try:
            if self._view._width != 122:
                raise ValueError("not portrait")
            shakes = self._view._state._state['shakes']
            mode = self._view._state._state['mode']
            label_px = shakes.label_spacing + shakes.label_font.getlength(shakes.label)
            available_px = mode.xy[0] - shakes.xy[0] - label_px
            value_budget = max(0, available_px // 6)
        except Exception:
            value_budget = 0

        overhead = 3
        session_budget = value_budget - overhead - len(total_str)
        if value_budget and 0 < session_budget < len(session_str):
            session_str = '9' * (session_budget - 1) + '+' if session_budget > 1 else '+'

        return '%s (%s)' % (session_str, total_str)

    def _update_handshakes(self, new_shakes=0):
        if new_shakes > 0:
            self._epoch.track(handshake=True, inc=new_shakes)
        if new_shakes > 0 or self._tot_handshakes_cache is None:
            self._tot_handshakes_cache = utils.total_unique_handshakes(self._config['bettercap']['handshakes'])
        tot = self._tot_handshakes_cache
        txt = self._format_shakes_text(len(self._handshakes), tot)
        self._view.set('shakes', txt)
        try:
            shakes_x, shakes_y = self._view._state._state['shakes'].xy
            if self._view._width == 122:
                self._view._state._state['last_pwnd_name'].xy = (shakes_x, 236)
            else:
                dynamic_offset = 32 + (len(txt) * 6)
                self._view._state._state['last_pwnd_name'].xy = (shakes_x + dynamic_offset, shakes_y)
        except Exception:
            pass

        if self._last_pwnd is None:
            self._last_pwnd = self._get_historical_last_pwnd()

        if self._last_pwnd is not None:
            self._view.set('last_pwnd_name', self._last_pwnd)
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
        try:
            logging.warning("writing recovery data to %s ...", RECOVERY_DATA_FILE)
        except RuntimeError:
            pass
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

                now = time.time()
                with self._history_lock:
                    for mac in self._history:
                        self._last_seen[mac] = now
                        self._last_decay[mac] = now

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
        asyncio.set_event_loop(loop)
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
        _thread.start_new_thread(self._event_poller, (asyncio.new_event_loop(),))

    def is_module_running(self, module):
        s = self.session()
        for m in s['modules']:
            if m['name'] == module:
                return m['running']
        return False

    START_MODULE_MAX_ATTEMPTS = 5
    START_MODULE_RETRY_DELAY = 2

    def start_module(self, module):
        last_err = None
        for attempt in range(self.START_MODULE_MAX_ATTEMPTS):
            try:
                self.run('%s on' % module)
                return
            except Exception as err:
                last_err = err
                if 'Interface Not Up' in str(err):
                    logging.warning("[start_module] %s not up yet, retrying (%d/%d) ...",
                                     module, attempt + 1, self.START_MODULE_MAX_ATTEMPTS)
                    time.sleep(self.START_MODULE_RETRY_DELAY)
                    continue
                raise
        raise last_err

    def restart_module(self, module):
        self.run('%s off; %s on' % (module, module))

    def _has_handshake(self, bssid):
        with self._handshakes_lock:
            for key in self._handshakes:
                if bssid.lower() in key.lower():
                    return True
        return False

    def _should_interact(self, who):
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

        if throttle is None:
            throttle = self._config['personality'].get('action_throttle', 0.8)

        if self._config['personality']['associate'] and self._should_interact(ap['mac']):
            self._view.on_assoc(ap)

            try:
                logging.info("sending association frame to %s (%s %s) on channel %d [%d clients], %d dBm...",
                    ap['hostname'], ap['mac'], ap['vendor'], ap['channel'], len(ap['clients']), ap['rssi'])
                self.run('wifi.recon %s' % ap['mac'])
                self.run('wifi.assoc %s' % ap['mac'])
                self._epoch.track(assoc=True)

                self._pending_wait = max(self._pending_wait,
                                          self._config['personality']['min_recon_time'])

            except Exception as e:
                self._on_error(ap['mac'], e)

            plugins.on('association', self, ap)
            if throttle > 0:
                time.sleep(throttle)
                self._epoch.track(sleep=True, inc=throttle)

            self._view.on_normal()

    def deauth(self, ap, sta, throttle=None):
        if self.is_stale():
            logging.debug("recon is stale, skipping deauth(%s)", sta['mac'])
            return

        if throttle is None:
            throttle = self._config['personality'].get('action_throttle', 0.8)

        if self._config['personality']['deauth'] and self._should_interact(sta['mac']):
            self._view.on_deauth(sta)

            try:
                logging.info("deauthing %s (%s) from %s (%s %s) on channel %d, %d dBm ...",
                    sta['mac'], sta['vendor'], ap['hostname'], ap['mac'], ap['vendor'], ap['channel'], ap['rssi'])
                self.run('wifi.recon %s' % ap['mac'])
                self.run('wifi.deauth %s' % sta['mac'])
                self._epoch.track(deauth=True)

                self._pending_wait = max(self._pending_wait,
                                          self._config['personality']['hop_recon_time'])

            except Exception as e:
                self._on_error(sta['mac'], e)

            plugins.on('deauthentication', self, ap, sta)

            if throttle > 0:
                time.sleep(throttle)
                self._epoch.track(sleep=True, inc=throttle)

            self._view.on_normal()

    def set_channel(self, channel, verbose=True):
        if self.is_stale():
            logging.debug("recon is stale, skipping set_channel(%d)", channel)
            return

        if channel != self._current_channel:
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

        if self._current_channel != 0:
            self._view.set('channel', '%d' % self._current_channel)
