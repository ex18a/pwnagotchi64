import logging
import subprocess
import requests
import pwnagotchi.plugins as plugins


class TimezoneSync(plugins.Plugin):
    __author__ = 'https://github.com/ex18a/pwnagotchi64'
    __version__ = '1.0.0'
    __license__ = 'GPL3'
    __description__ = 'Sets the system timezone from IP geolocation once per boot, since there is no hardware RTC to carry it across reboots.'

    def on_loaded(self):
        self._done = False
        logging.info("timezone-sync plugin loaded.")

    def on_internet_available(self, agent):
        if self._done:
            return
        self._done = True

        try:
            current = subprocess.run(
                ['timedatectl', 'show', '-p', 'Timezone', '--value'],
                capture_output=True, text=True, timeout=10, check=True
            ).stdout.strip()

            r = requests.get('https://ipapi.co/timezone/', timeout=10)
            r.raise_for_status()
            detected = r.text.strip()

            if '/' not in detected or len(detected) > 64:
                logging.warning(f"[timezone-sync] unexpected response, skipping: {detected!r}")
                return

            if detected == current:
                logging.info(f"[timezone-sync] already on {detected}")
                return

            subprocess.run(['timedatectl', 'set-timezone', detected], check=True, timeout=10)
            logging.info(f"[timezone-sync] set timezone to {detected} (was {current})")
        except Exception as e:
            logging.warning(f"[timezone-sync] couldn't auto-detect timezone: {e}")
