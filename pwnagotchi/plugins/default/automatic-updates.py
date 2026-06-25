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

        display.update(force=True, new_data={'status': f"Downloading {info['available']} ..."})
        r = requests.get(info['zip_url'], timeout=60)
        r.raise_for_status()
        with open(zip_path, 'wb') as fp:
            fp.write(r.content)

        display.update(force=True, new_data={'status': f"Extracting {info['available']} ..."})
        shutil.unpack_archive(zip_path, work_dir, format='zip')

        source_dir = next((d for d in glob.glob(os.path.join(work_dir, '*')) if os.path.isdir(d)), None)
        if source_dir is None:
            logging.error("[automatic-updates] couldn't find extracted source folder")
            return False

        # =========================================================
        # DYNAMIC SYSTEM DEPENDENCY INSTALLER
        # =========================================================
        apt_req_file = os.path.join(source_dir, 'apt-requirements.txt')
        
        if os.path.exists(apt_req_file):
            # Read the file, stripping out empty lines and comments
            with open(apt_req_file, 'r') as f:
                packages = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            
            if packages:
                display.update(force=True, new_data={'status': "Installing sys deps ..."})
                logging.info(f"[automatic-updates] Found apt-requirements.txt. Installing: {', '.join(packages)}")
                
                # Clone the current environment variables and force non-interactive mode
                env = os.environ.copy()
                env['DEBIAN_FRONTEND'] = 'noninteractive'
                
                # Update apt sources first so it can actually find the packages
                subprocess.run(['apt-get', 'update'], capture_output=True, env=env)
                
                # Install the packages read from the file
                apt_cmd = ['apt-get', 'install', '-y'] + packages
                apt_result = subprocess.run(apt_cmd, capture_output=True, text=True, env=env)
                
                if apt_result.returncode != 0:
                    logging.error(f"[automatic-updates] apt install failed: {apt_result.stderr.strip()}")
                    return False

                # =========================================================
                # THE SAFEGUARD: Verify packages are actually on the system
                # =========================================================
                logging.info("[automatic-updates] Verifying package installations...")
                for pkg in packages:
                    # dpkg -s checks the actual system status of the package
                    verify_cmd = subprocess.run(['dpkg', '-s', pkg], capture_output=True, text=True)
                    
                    if 'Status: install ok installed' not in verify_cmd.stdout:
                        logging.error(f"[automatic-updates] SAFEGUARD TRIGGERED: {pkg} failed to install. Aborting update to protect Pwnagotchi.")
                        return False # This stops the update entirely
                
                logging.info("[automatic-updates] All dependencies verified. Proceeding with Pwnagotchi update.")
        # =========================================================

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
