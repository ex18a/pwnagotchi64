import subprocess
import socket
import requests
import json
import logging
import threading
import time

import pwnagotchi

# pwngrid-peer is running on port 8666
API_ADDRESS = "http://127.0.0.1:8666/api/v1"

# THE BOOT DELAY FIX
# Set the timer to the exact moment the Pi powers on and loads the plugin!
LAST_RESTART_TIME = time.time()


def is_connected():
    try:
        # Check against the active community grid uptime endpoint
        requests.get('https://api.opwngrid.xyz/api/v1/uptime', timeout=2.0)
        return True
    except:
        return False


def _auto_heal_grid():
    def heal_task():
        try:
            logging.warning("[Grid Auto-Heal] 422 Detected. Stopping corrupted pwngrid-peer...")
            subprocess.run(['sudo', 'systemctl', 'stop', 'pwngrid-peer'])

            logging.warning("[Grid Auto-Heal] Nudging corrupted database into the void...")
            subprocess.run(['sudo', 'rm', '-rf', '/root/.pwngrid/'])

            logging.warning("[Grid Auto-Heal] Booting fresh pwngrid-peer instance...")
            subprocess.run(['sudo', 'systemctl', 'start', 'pwngrid-peer'])

            logging.info("[Grid Auto-Heal] Database factory reset complete!")
        except Exception as e:
            logging.error(f"[Grid Auto-Heal] Failed to execute recovery sequence: {e}")

    # Launch this in background so the UI ticker doesn't freeze waiting for systemctl!
    heal_thread = threading.Thread(target=heal_task)
    heal_thread.daemon = True
    heal_thread.start()


def _auto_start_grid():
    global LAST_RESTART_TIME
    current_time = time.time()

    # Cooldown Lock (180 seconds)
    if current_time - LAST_RESTART_TIME < 180:
        return False  # Tell the main script we are on cooldown so it stays silent

    LAST_RESTART_TIME = current_time

    def start_task():
        try:
            logging.warning("[Grid Auto-Starter] Connection Refused! Daemon is dead. Booting it back up...")
            subprocess.run(['sudo', 'systemctl', 'restart', 'pwngrid-peer'])
            logging.info("[Grid Auto-Starter] pwngrid-peer revived and on 2-minute cooldown.")
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
            # Slashed timeout from 60s down to 3s to prevent UI thread lockups
            r = requests.get(url, timeout=(1.0, 3.0))
        else:
            logging.debug(f"grid.call POST {url} with data")

            # Send bytes as raw data, send everything else as JSON
            if isinstance(obj, bytes):
                r = requests.post(url, data=obj, timeout=(1.0, 3.0))
            else:
                r = requests.post(url, json=obj, timeout=(1.0, 3.0))

        # AUTO-HEAL INTERCEPTOR
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 422:
            logging.error(f"grid.call caught 422 Unprocessable Entity! Triggering Auto-Heal...")
            _auto_heal_grid()
            # Return safe structures to prevent UI thread crashes while healing
            if "peers" in path or "memory" in path or "inbox" in path:
                return []
            return {}
        else:
            logging.error(f"grid.call unexpected status code {r.status_code} for {url}")

    except Exception as e:
        error_str = str(e)
        if "Connection refused" in error_str:
            # Trigger the auto-starter only if the cooldown has finished
            if _auto_start_grid():
                logging.error(f"grid.call caught Connection Refused! Triggering Auto-Starter...")
        elif "Read timed out" in error_str:
            # The daemon is alive but busy syncing to the cloud. Stay completely silent!
            pass
        else:
            logging.error(f"grid.call communication error for {url}: {e}")

    # Return safe structures to prevent UI thread crashes if communication drops
    if "peers" in path or "memory" in path or "inbox" in path:
        return []
    return {}


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

