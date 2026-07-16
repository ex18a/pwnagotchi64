import json
import logging
import requests
import websockets
import asyncio
import random

from requests.auth import HTTPBasicAuth
from time import sleep

requests.adapters.DEFAULT_RETRIES = 5 # increase retries number

ping_timeout  = 180
ping_interval = 15
max_queue = 10000

min_sleep = 0.5
max_sleep = 5.0

# Set by automatic-updates.py right before it deliberately stops bettercap
# for the duration of a pip install (see its own comments for why), and
# cleared right after starting it back up. Every reconnect-retry loop below
# checks this so a perfectly expected, self-inflicted outage doesn't spam
# the log with the exact same WARNING lines a genuine bettercap crash
# would -- otherwise every single update looks like an incident.
EXPECTED_DOWNTIME = False

def _log_retry(msg):
    if EXPECTED_DOWNTIME:
        logging.debug(msg)
    else:
        logging.warning(msg)


def decode(r, verbose_errors=True):
    try:
        return r.json()
    except Exception as e:
        if r.status_code == 200:
            logging.error("error while decoding json: error='%s' resp='%s'" % (e, r.text))
        else:
            err = "error %d: %s" % (r.status_code, r.text.strip())
            if verbose_errors:
                logging.info(err)
            raise Exception(err)
        return r.text


class Client(object):
    def __init__(self, hostname='localhost', scheme='http', port=8081, username='user', password='pass'):
        self.hostname = hostname
        self.scheme = scheme
        self.port = port
        self.username = username
        self.password = password
        self.url = "%s://%s:%d/api" % (scheme, hostname, port)
        self.websocket = "ws://%s:%s@%s:%d/api" % (username, password, hostname, port)
        self.auth = HTTPBasicAuth(username, password)

    # session takes optional argument to pull a sub-dictionary
    #  ex.: "session/wifi", "session/ble"
    def session(self, sess="session"):
        r = requests.get("%s/%s" % (self.url, sess), auth=self.auth)
        return decode(r)

    async def start_websocket(self, consumer):
        s = "%s/events" % self.websocket

        # More modern version of the approach below
        # logging.info("Creating new websocket...")
        # async for ws in websockets.connect(s):
        #     try:
        #         async for msg in ws:
        #             try:
        #                 await consumer(msg)
        #             except Exception as ex:
        #                     logging.debug("Error while parsing event (%s)", ex)
        #     except websockets.exceptions.ConnectionClosedError:
        #         sleep_time = max_sleep*random.random()
        #         logging.warning('Retrying websocket connection in {} sec'.format(sleep_time))
        #         await asyncio.sleep(sleep_time)
        #         continue

        # restarted every time the connection fails
        while True:
            logging.info("creating new websocket...")
            try: 
                async with websockets.connect(s, ping_interval=ping_interval, ping_timeout=ping_timeout, max_queue=max_queue) as ws:
                    # listener loop
                    while True:
                        try:
                            async for msg in ws:
                                try:
                                    await consumer(msg)
                                except Exception as ex:
                                        logging.debug("error while parsing event (%s)", ex)
                        except websockets.exceptions.ConnectionClosedError:
                            try: 
                                pong = await ws.ping()
                                await asyncio.wait_for(pong, timeout=ping_timeout)
                                logging.warning('ping OK, keeping connection alive...')
                                continue
                            except:
                                sleep_time = min_sleep + max_sleep*random.random()
                                logging.warning('ping error - retrying connection in {} sec'.format(sleep_time))
                                await asyncio.sleep(sleep_time)
                                break
            except ConnectionRefusedError:
                sleep_time = min_sleep + max_sleep*random.random()
                _log_retry('nobody seems to be listening at the bettercap endpoint...')
                _log_retry('retrying connection in {} sec'.format(sleep_time))
                await asyncio.sleep(sleep_time)
                continue
            except OSError:
                sleep_time = min_sleep + max_sleep*random.random()
                _log_retry('connection to the bettercap endpoint failed...')
                _log_retry('retrying connection in {} sec'.format(sleep_time))
                await asyncio.sleep(sleep_time)
                continue


    def run(self, command, verbose_errors=True):
        while True:
            try:
                r = requests.post("%s/session" % self.url, auth=self.auth, json={'cmd': command})
            except requests.exceptions.ConnectionError as e:
                sleep_time = min_sleep + max_sleep*random.random()
                _log_retry("can't run my request... connection to the bettercap endpoint failed...")
                _log_retry('retrying run in {} sec'.format(sleep_time))
                sleep(sleep_time)
            else:
                break

        return decode(r, verbose_errors=verbose_errors)
