import os
import logging
import subprocess
import requests
import shutil
import glob
from threading import Lock

import pwnagotchi
import pwnagotchi.plugins as plugins
from pwnagotchi.utils import StatusFile, parse_version as version_to_tuple


class AutomaticUpdates(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.0'
    __name__ = 'automatic-updates'
    __license__ = 'GPL3'
    __description__ = ('Checks GitHub Releases on a configured fork and self-updates the '
                        'pwnagotchi package files when a newer tag is published.')

    def __init__(self):
        self.ready = False
        self.status = StatusFile('/root/.automatic-updates')
        self.lock = Lock()

    def on_loaded(self):
        missing = [k for k in ('repo', 'interval') if k not in self.options or not self.options[k]]
        if missing:
            logging.error(f"[automatic-updates] missing required option(s): {', '.join(missing)}")
            return

        self.options.setdefault('install', False)
        self.ready = True
        logging.info(f"[automatic-updates] watching {self.options['repo']} for new releases "
                     f"every {self.options['interval']}h (install={self.options['install']})")

    def on_internet_available(self, agent):
        if not self.ready or self.lock.locked():
            return

        with self.lock:
            if self.status.newer_then_hours(self.options['interval']):
                return

            logging.info("[automatic-updates] checking for a new release ...")
            display = agent.view()
            prev_status = display.get('status')

            try:
                info = self._check_latest()
                self.status.update()

                if info is None:
                    logging.debug("[automatic-updates] no update found")
                    return

                logging.warning(f"[automatic-updates] update available: {info['current']} -> {info['available']}")

                if not self.options['install']:
                    display.update(force=True, new_data={'status': f"Update available: {info['available']}!"})
                    return

                display.update(force=True, new_data={'status': f"Installing {info['available']} ..."})
                if self._install(display, info):
                    logging.info(f"[automatic-updates] installed {info['available']}, restarting service ...")
                    display.update(force=True, new_data={'status': 'Restarting to apply update ...'})
                    self._apply()
                    return  # process is about to be killed by the restart anyway
                else:
                    logging.error(f"[automatic-updates] install of {info['available']} failed, staying on {info['current']}")

            except Exception as e:
                logging.error(f"[automatic-updates] {e}")

            display.update(force=True, new_data={'status': prev_status if prev_status is not None else ''})

    def _check_latest(self):
        repo = self.options['repo']
        resp = requests.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=15)
        if resp.status_code == 404:
            # repo has no releases published yet
            return None
        resp.raise_for_status()
        latest = resp.json()

        available = latest['tag_name'].lstrip('v')
        current = pwnagotchi.__version__

        if version_to_tuple(available) <= version_to_tuple(current):
            return None

        return {
            'repo': repo,
            'current': current,
            'available': available,
            'tag': latest['tag_name'],
            'zip_url': f"https://github.com/{repo}/archive/refs/tags/{latest['tag_name']}.zip",
        }

    def _install(self, display, info):
        work_dir = f"/tmp/automatic-updates/{info['available']}"
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir)

        zip_path = os.path.join(work_dir, 'source.zip')

        # Downloads everything in the repo at that tag, as a single zip --
        # there's no per-file selection step.
        display.update(force=True, new_data={'status': f"Downloading {info['available']} ..."})
        r = requests.get(info['zip_url'], timeout=60)
        r.raise_for_status()
        with open(zip_path, 'wb') as fp:
            fp.write(r.content)

        display.update(force=True, new_data={'status': f"Extracting {info['available']} ..."})
        shutil.unpack_archive(zip_path, work_dir, format='zip')

        # GitHub's tag archive always extracts to one subfolder, normally
        # named "<repo-name>-<tag-without-leading-v>"
        source_dir = next((d for d in glob.glob(os.path.join(work_dir, '*')) if os.path.isdir(d)), None)
        if source_dir is None:
            logging.error("[automatic-updates] couldn't find extracted source folder")
            return False

        # This is the step that actually decides "where files go" -- pip
        # reads setup.py inside source_dir and copies every pwnagotchi
        # package file from the extracted repo on top of whatever's
        # already installed in site-packages. --no-deps so it only
        # touches our own files, not every dependency too.
        result = subprocess.run(['pip3', 'install', '--break-system-packages', '--no-deps', '.'], cwd=source_dir,
                                capture_output=True, text=True)
        if result.returncode != 0:
            logging.error(f"[automatic-updates] pip install failed: {result.stderr.strip()}")
            return False

        return True

    def _apply(self):
        # Only the pwnagotchi package itself changed -- bettercap, pwngrid,
        # and the kernel/drivers are untouched, so restarting the service
        # is enough to load the new code. No full device reboot needed.
        os.system('systemctl restart pwnagotchi')
