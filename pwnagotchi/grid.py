import subprocess
import requests
import json
import logging
import threading
import time

import pwnagotchi

# pwngrid-peer is running on port 8666
API_ADDRESS = "http://127.0.0.1:8666/api/v1"

# Cooldown between automatic pwngrid-peer restarts, so a burst of failed
# calls while it's down doesn't trigger a restart storm.
_RESTART_COOLDOWN = 180
_last_restart_time = 0.0
_restart_lock = threading.Lock()

# Endpoints whose response is a list rather than an object -- used to pick
# a safe fallback value when a call fails, so callers never have to
# separately handle "call failed" as a distinct case from "call succeeded
# with an empty result".
_LIST_ENDPOINTS = ("peers", "memory", "inbox")


def _safe_default(path):
    return [] if any(marker in path for marker in _LIST_ENDPOINTS) else {}


def is_connected():
    try:
        # Check against the active community grid uptime endpoint
        requests.get('https://api.opwngrid.xyz/api/v1/uptime', timeout=2.0)
        return True
    except:
        return False


def _auto_start_grid():
    # Restarts pwngrid-peer when it's simply not running (connection
    # refused) -- this is the one case worth an automatic recovery
    # attempt, since the daemon being down is unambiguous and restarting
    # it is non-destructive. Distinct from a 422 response, which means
    # pwngrid-peer IS running and rejected something about the specific
    # request it received (see call()'s comment) -- restarting the daemon
    # wouldn't fix that, so this is deliberately not triggered for 422s.
    global _last_restart_time
    with _restart_lock:
        now = time.time()
        if now - _last_restart_time < _RESTART_COOLDOWN:
            return False
        _last_restart_time = now

    def start_task():
        try:
            logging.warning("[Grid Auto-Starter] Connection Refused! Daemon is dead. Booting it back up...")
            subprocess.run(['sudo', 'systemctl', 'restart', 'pwngrid-peer'])
            logging.info("[Grid Auto-Starter] pwngrid-peer revived and on cooldown.")
        except Exception as e:
            logging.error(f"[Grid Auto-Starter] Failed to execute startup sequence: {e}")

    start_thread = threading.Thread(target=start_task)
    start_thread.daemon = True
    start_thread.start()
    return True


def call(path, obj=None):
    url = f"{API_ADDRESS}{path}"
    try:
        if obj is None:
            logging.debug(f"grid.call GET {url}")
            # cut down from the original 30s/60s connect/read timeout,
            # which could block the calling thread for up to a minute on
            # a slow or wedged pwngrid-peer
            r = requests.get(url, timeout=(1.0, 3.0))
        else:
            logging.debug(f"grid.call POST {url} with data")

            # Send bytes as raw data, send everything else as JSON
            if isinstance(obj, bytes):
                r = requests.post(url, data=obj, timeout=(1.0, 3.0))
            else:
                r = requests.post(url, json=obj, timeout=(1.0, 3.0))

        if r.status_code == 200:
            return r.json()

        # every 422 in pwngrid-peer's own source (checked directly:
        # github.com/jayofelony/pwngrid, every http.StatusUnprocessableEntity
        # call site) means it couldn't parse/validate the specific request
        # it just received -- an empty body, invalid JSON, a bad page
        # number, a signature check failing, etc. It is never about
        # server-side state being corrupted, so there's nothing to "heal"
        # by wiping pwngrid-peer's identity/database and restarting it --
        # that was tried previously and didn't address the actual cause,
        # since the next request with the same bug would just 422 again
        # against a fresh identity. r.text carries pwngrid-peer's actual
        # error message (see its ERROR() helper), which is the useful
        # diagnostic signal here.
        logging.error(f"grid.call unexpected status code {r.status_code} for {url}: {r.text}")

    except requests.exceptions.ConnectionError as e:
        # matches both "connection refused" (daemon not running) and other
        # connection-level failures; only the former is worth auto-starting
        # for, but there's no clean way to distinguish them from the
        # exception alone, and restarting an already-running-but-otherwise
        # unreachable daemon is harmless
        if _auto_start_grid():
            logging.error(f"grid.call caught a connection error, triggering Auto-Starter: {e}")
    except requests.exceptions.Timeout:
        # the daemon is alive but busy (e.g. syncing to the cloud) -- stay
        # quiet, this is expected occasionally and not worth logging every
        # time
        pass
    except Exception as e:
        logging.error(f"grid.call communication error for {url}: {e}")

    return _safe_default(path)


def advertise(enabled=True):
    return call("/mesh/%s" % ('true' if enabled else 'false'))


def set_advertisement_data(data):
    return call("/mesh/data", obj=data)


def get_advertisement_data():
    return call("/mesh/data")


def memory():
    return call("/mesh/memory")


def peers():
    return call("/mesh/peers")


def closest_peer():
    all = peers()
    return all[0] if len(all) else None


def update_data(last_session):
    brain = {}
    try:
        with open('/root/brain.json') as fp:
            brain = json.load(fp)
    except:
        pass

    enabled = [name for name, options in pwnagotchi.config['main']['plugins'].items() if
               'enabled' in options and options['enabled']]
    language = pwnagotchi.config['main']['lang']

    data = {
        'session': {
            'duration': last_session.duration,
            'epochs': last_session.epochs,
            'train_epochs': last_session.train_epochs,
            'avg_reward': last_session.avg_reward,
            'min_reward': last_session.min_reward,
            'max_reward': last_session.max_reward,
            'deauthed': last_session.deauthed,
            'associated': last_session.associated,
            'handshakes': last_session.handshakes,
            'peers': last_session.peers,
        },
        'uname': subprocess.getoutput("uname -a"),
        'brain': brain,
        'version': pwnagotchi.__version__,

        'build': "Pwnagotchi64 by ex18a",
        'plugins': enabled,
        'language': language,
        'bettercap': subprocess.getoutput("bettercap -version"),
        'opwngrid': subprocess.getoutput("pwngrid -version")
    }

    logging.debug("updating grid data: %s" % data)
    call("/data", data)


def report_ap(essid, bssid):
    try:
        call("/report/ap", {
            'essid': essid,
            'bssid': bssid,
        })
        return True
    except Exception as e:
        logging.exception("error while reporting ap %s(%s)" % (essid, bssid))

    return False


def inbox(page=1, with_pager=False):
    obj = call("/inbox?p=%d" % page)

    # 1. If call() failed and returned a list, reset it to a safe dictionary
    if isinstance(obj, list) or not isinstance(obj, dict):
        obj = {'pages': 1, 'messages': []}

    # 2. Guarantee the required keys exist so the Web UI never crashes
    if 'pages' not in obj:
        obj['pages'] = 1
    if 'messages' not in obj:
        obj['messages'] = []

    return obj.get("messages", []) if not with_pager else obj


def inbox_message(id):
    return call("/inbox/%d" % int(id))


def mark_message(id, mark):
    return call("/inbox/%d/%s" % (int(id), str(mark)))


def send_message(to, message):
    return call("/unit/%s/inbox" % to, message.encode('utf-8'))

