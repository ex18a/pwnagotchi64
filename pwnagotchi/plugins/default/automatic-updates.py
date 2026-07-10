import os
import logging
import subprocess
import requests
import shutil
import glob
import time
from datetime import datetime
from threading import Lock, Thread

import pwnagotchi
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.faces as faces
from pwnagotchi.utils import StatusFile, parse_version as version_to_tuple


class AutomaticUpdates(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.2'
    __name__ = 'automatic-updates'
    __license__ = 'GPL3'
    __description__ = ('Checks GitHub Releases on a configured fork and self-updates the '
                        'pwnagotchi package files when a newer tag is published.')

    # hardcoded rather than a config option -- there's only ever one branch
    # this cares about, and the /root/dev flag is what turns it on
    DEV_BRANCH = 'dev'
    DEV_FLAG_PATH = '/root/dev'

    # frames the progress animation cycles through for the "in progress"
    # stages that don't have their own distinct face (checking/verifying
    # deps and the terminal states keep theirs -- see _install() and
    # on_internet_available())
    PROGRESS_FACES = (faces.UPLOAD, faces.UPLOAD1, faces.UPLOAD2)
    PROGRESS_FRAME_INTERVAL = 0.5

    def __init__(self):
        self.ready = False
        self.status = StatusFile('/root/.automatic-updates')
        self.lock = Lock()
        self._sha_file = '/root/.automatic-updates-sha'
        self._tmp_base_dir = '/tmp/automatic-updates'
        self._animating = False
        self._anim_paused = False
        self._anim_thread = None

    def on_loaded(self):
        missing = [k for k in ('repo', 'interval') if k not in self.options or not self.options[k]]
        if missing:
            logging.error(f"[automatic-updates] missing required option(s): {', '.join(missing)}")
            return

        self.options.setdefault('install', False)
        self.ready = True
        logging.info(f"[automatic-updates] watching {self.options['repo']} for new releases "
                     f"every {self.options['interval']}h (install={self.options['install']})")
        if self._dev_mode():
            logging.info(f"[automatic-updates] {self.DEV_FLAG_PATH} present -- also tracking "
                         f"{self.options['repo']}@{self.DEV_BRANCH} for new commits")

    def _dev_mode(self):
        return os.path.exists(self.DEV_FLAG_PATH)

    def _start_progress(self, agent):
        # pins face/status so nothing else (bored, AI reward pings, etc.) can
        # interrupt the install sequence, and keeps the face animating in the
        # background for the whole thing rather than sitting on one static
        # frame -- pause/resume it around the moments that want their own
        # distinct face (see _install()). Stays pinned past the animation
        # itself, through the final installed/failed message, until
        # _end_progress() -- see on_internet_available().
        agent.view().pin()
        self._animating = True
        self._anim_paused = False

        def _loop():
            idx = 0
            while self._animating:
                try:
                    if not self._anim_paused:
                        agent.view().set('face', self.PROGRESS_FACES[idx], force=True)
                        agent.view().update(force=True)
                        idx = (idx + 1) % len(self.PROGRESS_FACES)
                except Exception as e:
                    logging.error(f"[automatic-updates] error while animating progress: {e}")
                time.sleep(self.PROGRESS_FRAME_INTERVAL)

        self._anim_thread = Thread(target=_loop, daemon=True)
        self._anim_thread.start()

    def _stop_animation(self):
        self._animating = False
        if self._anim_thread is not None and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=2)
        self._anim_thread = None

    def _end_progress(self, agent):
        self._stop_animation()
        agent.view().unpin()

    def on_internet_available(self, agent):
        if not self.ready or self.lock.locked():
            return

        with self.lock:
            if self.status.newer_then_hours(self.options['interval']):
                return

            logging.info("[automatic-updates] checking for updates ...")

            try:
                info = self._check_latest()
                self.status.update()

                if info is None:
                    logging.debug("[automatic-updates] no update found")
                    return

                logging.warning(f"[automatic-updates] update available: {info['label']} ({info['kind']})")

                if not self.options['install']:
                    agent.view().on_update_available(info['label'])
                    return

                logging.info(f"[automatic-updates] Installing {info['label']} ...")
                self._start_progress(agent)
                agent.view().on_update_installing(info['label'])

                try:
                    installed = self._install(agent, info)
                finally:
                    # animation stops here -- the terminal face below takes
                    # over, but stays pinned until the user's had a chance
                    # to actually read it
                    self._stop_animation()

                if installed:
                    if info['kind'] == 'commit':
                        with open(self._sha_file, 'w') as f:
                            f.write(info['sha'])
                    logging.info(f"[automatic-updates] Installed {info['label']}, restarting service ...")
                    agent.view().on_update_installed(info['label'])
                    time.sleep(2)  # Let the user read the success message
                    logging.info("[automatic-updates] Restarting to apply update ...")
                    agent.view().on_update_restarting()
                    agent.view().unpin()
                    self._apply()
                    return  # process is about to be killed by the restart anyway
                else:
                    agent.view().on_update_failed(info['label'])
                    logging.error(f"[automatic-updates] install of {info['label']} failed")
                    time.sleep(10)  # Let the user read the failure message
                    agent.view().unpin()

            except Exception as e:
                self._end_progress(agent)
                logging.error(f"[automatic-updates] {e}")

    def _check_latest(self):
        release_candidate = self._check_latest_release()

        if not self._dev_mode():
            return release_candidate

        commit_candidate = self._check_latest_commit()

        if release_candidate and commit_candidate:
            # both have something new -- install whichever is actually more recent
            if release_candidate['published_at'] >= commit_candidate['published_at']:
                return release_candidate
            return commit_candidate

        return release_candidate or commit_candidate

    def _check_latest_release(self):
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
            'kind': 'release',
            'label': available,
            'current': current,
            'published_at': datetime.fromisoformat(latest['published_at']),
            'zip_url': f"https://github.com/{repo}/archive/refs/tags/{latest['tag_name']}.zip",
        }

    def _check_latest_commit(self):
        repo = self.options['repo']
        branch = self.DEV_BRANCH

        resp = requests.get(
            f"https://api.github.com/repos/{repo}/commits/{branch}",
            timeout=15,
            headers={'Accept': 'application/vnd.github.v3+json'}
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        data = resp.json()
        sha = data['sha']
        message = data['commit']['message'].split('\n')[0]
        committed_at = datetime.fromisoformat(data['commit']['committer']['date'])

        # Load last known SHA from disk so restarts don't lose state
        last_sha = None
        if os.path.exists(self._sha_file):
            with open(self._sha_file, 'r') as f:
                last_sha = f.read().strip()

        # First run -- seed SHA to disk and don't trigger an install
        if last_sha is None:
            with open(self._sha_file, 'w') as f:
                f.write(sha)
            logging.info(f"[automatic-updates] seeded current dev SHA: {sha[:7]} - {message}")
            return None

        # No change
        if sha == last_sha:
            logging.debug(f"[automatic-updates] no new commits since {sha[:7]}")
            return None

        return {
            'kind': 'commit',
            'label': sha[:7],
            'sha': sha,
            'message': message,
            'published_at': committed_at,
            'zip_url': f"https://github.com/{repo}/archive/refs/heads/{branch}.zip",
        }

    def _install(self, agent, info):
        # Previous attempts each leave their own /tmp/automatic-updates/<label>
        # folder behind (zip + extracted source + pip build artifacts) and
        # nothing ever cleaned those up -- wipe the whole parent dir here so
        # every install starts from a clean, empty /tmp regardless of how
        # many prior attempts have run before.
        logging.info("[automatic-updates] Cleaning up tmp ...")
        agent.view().on_update_cleaning()
        if os.path.exists(self._tmp_base_dir):
            shutil.rmtree(self._tmp_base_dir, ignore_errors=True)

        work_dir = os.path.join(self._tmp_base_dir, info['label'])
        os.makedirs(work_dir)

        zip_path = os.path.join(work_dir, 'source.zip')

        logging.info(f"[automatic-updates] Downloading {info['label']} ...")
        agent.view().on_update_downloading(info['label'])
        r = requests.get(info['zip_url'], timeout=60)
        r.raise_for_status()
        with open(zip_path, 'wb') as fp:
            fp.write(r.content)

        logging.info(f"[automatic-updates] Extracting {info['label']} ...")
        agent.view().on_update_extracting(info['label'])
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
                # if something is actually missing. Pause the progress
                # animation for this bit -- it has its own distinct face.
                self._anim_paused = True
                agent.view().on_update_checking_deps()
                logging.info(f"[automatic-updates] checking apt-requirements.txt against installed packages: {', '.join(packages)}")

                missing = []
                for pkg in packages:
                    verify_cmd = subprocess.run(['dpkg', '-s', pkg], capture_output=True, text=True)
                    if 'Status: install ok installed' not in verify_cmd.stdout:
                        missing.append(pkg)

                if missing:
                    self._anim_paused = False
                    agent.view().on_update_installing_deps()
                    logging.info(f"[automatic-updates] missing packages, installing: {', '.join(missing)}")

                    # Clone the current environment variables and force non-interactive mode
                    env = os.environ.copy()
                    env['DEBIAN_FRONTEND'] = 'noninteractive'

                    # Update apt sources first so it can actually find the packages
                    update_result = subprocess.run(['apt-get', 'update'], capture_output=True, text=True, env=env, timeout=120)
                    if update_result.returncode != 0:
                        logging.error(f"[automatic-updates] apt-get update failed: {update_result.stderr.strip()}")
                        return False

                    # Install only the packages that were actually missing
                    apt_cmd = ['apt-get', 'install', '-y'] + missing
                    apt_result = subprocess.run(apt_cmd, capture_output=True, text=True, env=env, timeout=300)

                    if apt_result.returncode != 0:
                        logging.error(f"[automatic-updates] apt install failed: {apt_result.stderr.strip()}")
                        return False

                    # =========================================================
                    # THE SAFEGUARD: Verify packages are actually on the system
                    # =========================================================
                    self._anim_paused = True
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

        # resume the progress animation -- covers every path above, whether
        # deps were missing, already present, or there was no apt-requirements
        # file at all
        self._anim_paused = False
        logging.info("[automatic-updates] Installing Python core ...")
        agent.view().on_update_installing_core()
        logging.info("[automatic-updates] running pip install -- output goes to /tmp/pip-install.log")

        # Write pip output to a log file instead of capturing it -- capturing
        # into a pipe buffer and never reading it can deadlock once the
        # output exceeds the OS pipe buffer size.
        pip_log_path = '/tmp/pip-install.log'
        try:
            with open(pip_log_path, 'w') as pip_log:
                result = subprocess.run(
                    ['pip3', 'install', '--break-system-packages', '--no-deps', '.'],
                    cwd=source_dir,
                    stdout=pip_log,
                    stderr=pip_log,
                    timeout=300  # 5 minute hard limit
                )
            if result.returncode != 0:
                with open(pip_log_path, 'r') as f:
                    lines = f.readlines()
                tail = ''.join(lines[-10:]).strip()
                logging.error(f"[automatic-updates] pip install failed:\n{tail}")
                return False
        except subprocess.TimeoutExpired:
            logging.error("[automatic-updates] pip install timed out after 5 minutes")
            return False

        logging.info("[automatic-updates] pip install completed successfully")
        return True

    def _apply(self):
        # Only the pwnagotchi package itself changed -- bettercap, pwngrid,
        # and the kernel/drivers are untouched, so restarting the service
        # is enough to load the new code. No full device reboot needed.
        os.system('systemctl restart pwnagotchi')
