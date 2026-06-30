import os
import logging
import subprocess
import requests
import shutil
import glob
import time
import threading
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
        self._ui_override_active = False
        self._original_view_set = None
        self._animating = False

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
                    agent.view().update(force=True, new_data={'status': f"Update available: {info['available']}!"})
                    return

                # --- START UI OVERRIDE & ANIMATION ---
                self._enable_ui_override(agent)
                self._set_update_status(agent, f"Installing {info['available']} ...")

                if self._install(agent, info):
                    self._set_update_status(agent, f"Installed {info['available']}, restarting service ...")
                    time.sleep(2)  # Let the user read the success message
                    self._set_update_status(agent, "Restarting to apply update ...")
                    self._disable_ui_override(agent)
                    self._apply()
                    return  # process is about to be killed by the restart anyway
                else:
                    self._set_update_status(agent, f"Install failed, staying on {info['current']}")
                    logging.error(f"[automatic-updates] install of {info['available']} failed, staying on {info['current']}")
                    time.sleep(10)  # Let the user read the failure message
                    self._disable_ui_override(agent)

            except Exception as e:
                logging.error(f"[automatic-updates] {e}")
                self._disable_ui_override(agent)  # Failsafe unlock

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

        self._set_update_status(agent, f"Downloading {info['available']} ...")
        r = requests.get(info['zip_url'], timeout=60)
        r.raise_for_status()
        with open(zip_path, 'wb') as fp:
            fp.write(r.content)

        self._set_update_status(agent, f"Extracting {info['available']} ...")
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
                self._set_update_status(agent, "Checking sys deps ...")
                logging.info(f"[automatic-updates] checking apt-requirements.txt against installed packages: {', '.join(packages)}")

                missing = []
                for pkg in packages:
                    verify_cmd = subprocess.run(['dpkg', '-s', pkg], capture_output=True, text=True)
                    if 'Status: install ok installed' not in verify_cmd.stdout:
                        missing.append(pkg)

                if missing:
                    self._set_update_status(agent, "Installing sys deps ...")
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
                    self._set_update_status(agent, "Verifying package installations...")
                    for pkg in missing:
                        verify_cmd = subprocess.run(['dpkg', '-s', pkg], capture_output=True, text=True)
                        if 'Status: install ok installed' not in verify_cmd.stdout:
                            logging.error(f"[automatic-updates] SAFEGUARD TRIGGERED: {pkg} failed to install. Aborting update to protect Pwnagotchi.")
                            return False  # This stops the update entirely

                    logging.info("[automatic-updates] All dependencies verified. Proceeding with Pwnagotchi update.")
                else:
                    logging.info("[automatic-updates] all apt dependencies already present, skipping apt-get entirely.")
        # =========================================================

        self._set_update_status(agent, "Installing Python core ...")
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

    # =======================================================================
    # UI OVERRIDE & ANIMATION HELPERS
    # =======================================================================
    def _enable_ui_override(self, agent):
        if getattr(self, '_ui_override_active', False):
            return
        self._ui_override_active = True
        self._original_view_set = agent.view().set
        self._current_status = "Initializing update..."
        self._faces = ['(1__0)', '(1__1)', '(0__1)']

        original = self._original_view_set

        # Intercept all incoming screen writes from other core routines/plugins
        def _filtered_set(key, value, *args, **kwargs):
            if key in ('face', 'status'):
                # Swallow everything else trying to touch face or status
                return
            return original(key, value, *args, **kwargs)

        agent.view().set = _filtered_set

        # Spin up an independent thread to animate your custom upload faces
        self._animating = True
        self._animation_thread = threading.Thread(target=self._animate_frames, args=(agent,))
        self._animation_thread.daemon = True
        self._animation_thread.start()

    def _disable_ui_override(self, agent):
        self._animating = False
        if hasattr(self, '_animation_thread') and self._animation_thread.is_alive():
            self._animation_thread.join(timeout=2)

        if not getattr(self, '_ui_override_active', False):
            return
        self._ui_override_active = False

        if hasattr(self, '_original_view_set') and self._original_view_set is not None:
            agent.view().set = self._original_view_set
            self._original_view_set = None

    def _set_update_status(self, agent, status_text):
        """Safely writes straight through the interceptor to update screen text"""
        self._current_status = status_text
        if getattr(self, '_ui_override_active', False) and getattr(self, '_original_view_set', None):
            self._original_view_set('status', status_text)
            agent.view().update(force=True)
        logging.info(f"[automatic-updates] {status_text}")

    def _animate_frames(self, agent):
        """Background animation loop that respects E-ink refresh limits"""
        face_idx = 0
        while getattr(self, '_animating', False):
            if getattr(self, '_original_view_set', None):
                current_face = self._faces[face_idx]
                # Write face and preserve current status line simultaneously
                self._original_view_set('face', current_face)
                if getattr(self, '_current_status', None):
                    self._original_view_set('status', self._current_status)
                agent.view().update(force=True)

                face_idx = (face_idx + 1) % len(self._faces)
            # 0.5-second sleep keeps the animation looking active without lagging the screen
            time.sleep(0.5)
