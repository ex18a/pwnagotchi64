import os
import logging
import subprocess
import requests
import shutil
import glob
import time
from threading import Lock

import pwnagotchi
import pwnagotchi.plugins as plugins
from pwnagotchi.utils import StatusFile, parse_version as version_to_tuple


class AutomaticUpdates(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.1'
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

            try:
                info = self._check_latest()
                self.status.update()

                if info is None:
                    logging.debug("[automatic-updates] no update found")
                    return

                logging.warning(f"[automatic-updates] update available: {info['current']} -> {info['available']}")

                if not self.options['install']:
                    agent.view().on_update_available(info['available'])
                    return

                logging.info(f"[automatic-updates] Installing {info['available']} ...")
                agent.view().on_update_installing(info['available'])

                if self._install(agent, info):
                    logging.info(f"[automatic-updates] Installed {info['available']}, restarting service ...")
                    agent.view().on_update_installed(info['available'])
                    time.sleep(2)  # Let the user read the success message
                    logging.info("[automatic-updates] Restarting to apply update ...")
                    agent.view().on_update_restarting()
                    self._apply()
                    return  # process is about to be killed by the restart anyway
                else:
                    agent.view().on_update_failed(info['current'])
                    logging.error(f"[automatic-updates] install of {info['available']} failed, staying on {info['current']}")
                    time.sleep(10)  # Let the user read the failure message

            except Exception as e:
                logging.error(f"[automatic-updates] {e}")

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

    def _install(self, agent, info):
        work_dir = f"/tmp/automatic-updates/{info['available']}"
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir)

        zip_path = os.path.join(work_dir, 'source.zip')

        logging.info(f"[automatic-updates] Downloading {info['available']} ...")
        agent.view().on_update_downloading(info['available'])
        r = requests.get(info['zip_url'], timeout=60)
        r.raise_for_status()
        with open(zip_path, 'wb') as fp:
            fp.write(r.content)

        logging.info(f"[automatic-updates] Extracting {info['available']} ...")
        agent.view().on_update_extracting(info['available'])
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
                # Check first -- only pay the apt-get update + install cost
                # if something is actually missing
                agent.view().on_update_checking_deps()
                logging.info(f"[automatic-updates] checking apt-requirements.txt against installed packages: {', '.join(packages)}")

                missing = []
                for pkg in packages:
                    verify_cmd = subprocess.run(['dpkg', '-s', pkg], capture_output=True, text=True)
                    if 'Status: install ok installed' not in verify_cmd.stdout:
                        missing.append(pkg)

                if missing:
                    agent.view().on_update_installing_deps()
                    logging.info(f"[automatic-updates] missing packages, installing: {', '.join(missing)}")

                    # Clone the current environment variables and force non-interactive mode
                    env = os.environ.copy()
                    env['DEBIAN_FRONTEND'] = 'noninteractive'

                    # Update apt sources first so it can actually find the packages
                    update_result = subprocess.run(['apt-get', 'update'], capture_output=True, text=True, env=env)
                    if update_result.returncode != 0:
                        logging.error(f"[automatic-updates] apt-get update failed: {update_result.stderr.strip()}")
                        return False

                    # Install only the packages that were actually missing
                    apt_cmd = ['apt-get', 'install', '-y'] + missing
                    apt_result = subprocess.run(apt_cmd, capture_output=True, text=True, env=env)

                    if apt_result.returncode != 0:
                        logging.error(f"[automatic-updates] apt install failed: {apt_result.stderr.strip()}")
                        return False

                    # =========================================================
                    # THE SAFEGUARD: Verify packages are actually on the system
                    # =========================================================
                    agent.view().on_update_verifying_deps()
                    for pkg in missing:
                        verify_cmd = subprocess.run(['dpkg', '-s', pkg], capture_output=True, text=True)
                        if 'Status: install ok installed' not in verify_cmd.stdout:
                            logging.error(f"[automatic-updates] SAFEGUARD TRIGGERED: {pkg} failed to install. Aborting update to protect Pwnagotchi.")
                            return False  # This stops the update entirely

                    logging.info("[automatic-updates] All dependencies verified. Proceeding with Pwnagotchi update.")
                else:
                    logging.info("[automatic-updates] all apt dependencies already present, skipping apt-get entirely.")
        # =========================================================

        logging.info("[automatic-updates] Installing Python core ...")
        agent.view().on_update_installing_core()
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
