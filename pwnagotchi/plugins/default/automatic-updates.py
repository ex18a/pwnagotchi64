import os
import logging
import subprocess
import requests
import shutil
import glob
import time
import importlib.util
from datetime import datetime
from threading import Lock, Thread

import pwnagotchi
import pwnagotchi.bettercap as bettercap
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.faces as faces
from pwnagotchi.utils import StatusFile, parse_version as version_to_tuple


class AutomaticUpdates(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.4'
    __name__ = 'automatic-updates'
    __license__ = 'GPL3'
    __description__ = ('Checks GitHub Releases on a configured fork and self-updates the '
                        'pwnagotchi package files when a newer tag is published.')

    DEV_BRANCH = 'dev'
    DEV_FLAG_PATH = '/root/dev'

    PROGRESS_FACES = (faces.UPLOAD, faces.UPLOAD1, faces.UPLOAD2)
    PROGRESS_FRAME_INTERVAL = 0.5

    BLOCKED_REMINDER_INTERVAL = 30

    def __init__(self):
        self.ready = False
        self.status = StatusFile('/root/.automatic-updates')
        self.lock = Lock()
        self._sha_file = '/root/.automatic-updates-sha'
        self._blocked_marker_path = '/root/.automatic-updates-blocked'
        self._tmp_base_dir = '/tmp/automatic-updates'
        self._animating = False
        self._anim_paused = False
        self._anim_thread = None
        self._last_blocked_reminder = 0

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
                    self._clear_blocked_marker()
                    return

                logging.warning(f"[automatic-updates] update available: {info['label']} ({info['kind']})")

                if self._is_blocked(info):
                    logging.error(f"[automatic-updates] {info['label']} is on the auto-update "
                                   "blocklist -- NOT auto-installing, update this device manually")
                    self._mark_blocked(info['label'])
                    agent.view().on_update_available(f"{info['label']} (manual update required)")
                    return

                self._clear_blocked_marker()

                if not self.options['install']:
                    agent.view().on_update_available(info['label'])
                    return

                logging.info(f"[automatic-updates] Installing {info['label']} ...")
                self._start_progress(agent)
                agent.view().on_update_installing(info['label'])

                try:
                    installed = self._install(agent, info)
                finally:
                    self._stop_animation()

                if installed:
                    if info['kind'] == 'commit':
                        with open(self._sha_file, 'w') as f:
                            f.write(info['sha'])
                    logging.info(f"[automatic-updates] Installed {info['label']}, restarting service ...")
                    agent.view().on_update_installed(info['label'])
                    time.sleep(2)
                    logging.info("[automatic-updates] Restarting to apply update ...")
                    agent.view().on_update_restarting()
                    agent.view().unpin()
                    self._apply()
                    return
                else:
                    agent.view().on_update_failed(pwnagotchi.display_version())
                    logging.error(f"[automatic-updates] install of {info['label']} failed")
                    time.sleep(10)
                    agent.view().unpin()

            except Exception as e:
                self._end_progress(agent)
                logging.error(f"[automatic-updates] {e}")

    BLOCKLIST_URL_TEMPLATE = "https://raw.githubusercontent.com/{repo}/main/AUTO_UPDATE_BLOCKLIST"
    BLOCKLIST_FETCH_TIMEOUT = 10

    def _fetch_blocklist(self):
        url = self.BLOCKLIST_URL_TEMPLATE.format(repo=self.options['repo'])
        try:
            resp = requests.get(url, timeout=self.BLOCKLIST_FETCH_TIMEOUT)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            entries = []
            for line in resp.text.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                target = parts[0]
                min_from = parts[1] if len(parts) > 1 else None
                entries.append((target, min_from))
            return entries
        except Exception as e:
            logging.warning(f"[automatic-updates] couldn't fetch blocklist, proceeding anyway: {e}")
            return []

    def _is_blocked(self, info):
        blocklist = self._fetch_blocklist()
        if not blocklist:
            return False

        label = info.get('label', '')
        full_sha = info.get('sha', '')
        current = pwnagotchi.__version__

        for target, min_from in blocklist:
            matches = target == label or (full_sha and (target == full_sha or full_sha.startswith(target)))
            if not matches:
                continue
            if min_from is None:
                return True
            try:
                if version_to_tuple(current) < version_to_tuple(min_from):
                    return True
            except Exception as e:
                logging.warning(f"[automatic-updates] couldn't compare version against blocklist "
                                 f"entry '{target} {min_from}', blocking to be safe: {e}")
                return True
        return False

    def _mark_blocked(self, label):
        try:
            with open(self._blocked_marker_path, 'w') as f:
                f.write(label)
        except Exception as e:
            logging.error(f"[automatic-updates] couldn't write blocked marker: {e}")

    def _clear_blocked_marker(self):
        try:
            if os.path.exists(self._blocked_marker_path):
                os.remove(self._blocked_marker_path)
        except Exception as e:
            logging.error(f"[automatic-updates] couldn't clear blocked marker: {e}")

    def _read_blocked_marker(self):
        try:
            with open(self._blocked_marker_path, 'r') as f:
                return f.read().strip() or None
        except FileNotFoundError:
            return None
        except Exception as e:
            logging.error(f"[automatic-updates] couldn't read blocked marker: {e}")
            return None

    def on_ready(self, agent):
        blocked_label = self._read_blocked_marker()
        if blocked_label:
            agent.view().on_update_available(f"{blocked_label} (manual update required)")

    def on_ui_update(self, ui):
        blocked_label = self._read_blocked_marker()
        if not blocked_label:
            return
        now = time.time()
        if now - self._last_blocked_reminder < self.BLOCKED_REMINDER_INTERVAL:
            return
        self._last_blocked_reminder = now
        ui.set('status', f"{blocked_label} available\nbut can't auto-install")

    def _check_latest(self):
        release_candidate = self._check_latest_release()

        if not self._dev_mode():
            return release_candidate

        commit_candidate = self._check_latest_commit()

        if release_candidate and commit_candidate:
            if release_candidate['published_at'] >= commit_candidate['published_at']:
                return release_candidate
            return commit_candidate

        return release_candidate or commit_candidate

    def _check_latest_release(self):
        repo = self.options['repo']
        resp = requests.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=15)
        if resp.status_code == 404:
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

        last_sha = None
        if os.path.exists(self._sha_file):
            with open(self._sha_file, 'r') as f:
                last_sha = f.read().strip()

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

        apt_req_file = os.path.join(source_dir, 'apt-requirements.txt')

        if os.path.exists(apt_req_file):
            with open(apt_req_file, 'r') as f:
                packages = [line.strip() for line in f if line.strip() and not line.startswith('#')]

            if packages:
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

                    env = os.environ.copy()
                    env['DEBIAN_FRONTEND'] = 'noninteractive'

                    self._dpkg_configure_a()
                    self._ensure_apt_force_ipv4()

                    update_result = subprocess.run(['apt-get', 'update'], capture_output=True, text=True, env=env, timeout=120)
                    if update_result.returncode != 0:
                        logging.error(f"[automatic-updates] apt-get update failed: {update_result.stderr.strip()}")
                        return False

                    apt_cmd = ['apt-get', 'install', '-y'] + missing
                    if not self._apt_install_with_recovery(apt_cmd, env):
                        return False

                    self._anim_paused = True
                    agent.view().on_update_verifying_deps()
                    for pkg in missing:
                        verify_cmd = subprocess.run(['dpkg', '-s', pkg], capture_output=True, text=True)
                        if 'Status: install ok installed' not in verify_cmd.stdout:
                            logging.error(f"[automatic-updates] SAFEGUARD TRIGGERED: {pkg} failed to install. Aborting update to protect Pwnagotchi.")
                            return False

                    logging.info("[automatic-updates] All dependencies verified. Proceeding with Pwnagotchi update.")
                else:
                    logging.info("[automatic-updates] all apt dependencies already present, skipping apt-get entirely.")

        self._anim_paused = False
        logging.info("[automatic-updates] Installing Python core ...")
        agent.view().on_update_installing_core()

        was_ai_paused = agent.is_ai_paused()
        if not was_ai_paused:
            agent.pause_ai()

        logging.info("[automatic-updates] stopping bettercap for the duration of the install ...")
        bettercap.EXPECTED_DOWNTIME = True
        os.system('systemctl stop bettercap')

        pip_log_path = '/tmp/pip-install.log'
        try:
            pip_req_file = os.path.join(source_dir, 'requirements.txt')
            if os.path.exists(pip_req_file) and not self._install_missing_pip_requirements(pip_req_file):
                return False

            logging.info("[automatic-updates] running pip install -- output goes to /tmp/pip-install.log")
            with open(pip_log_path, 'w') as pip_log:
                result = subprocess.run(
                    ['pip3', 'install', '--break-system-packages', '--no-deps',
                     '--no-build-isolation', '.'],
                    cwd=source_dir,
                    stdout=pip_log,
                    stderr=pip_log,
                    timeout=900
                )
            if result.returncode != 0:
                with open(pip_log_path, 'r') as f:
                    lines = f.readlines()
                tail = ''.join(lines[-10:]).strip()
                logging.error(f"[automatic-updates] pip install failed:\n{tail}")
                return False

            self._run_post_install_steps(source_dir)
        except subprocess.TimeoutExpired:
            logging.error("[automatic-updates] pip install timed out after 5 minutes")
            return False
        finally:
            if not was_ai_paused:
                agent.resume_ai()
            logging.info("[automatic-updates] restarting bettercap ...")
            os.system('systemctl start bettercap')
            waited = 0
            while waited < 180:
                try:
                    agent.session()
                    break
                except Exception:
                    time.sleep(5)
                    waited += 5
            bettercap.EXPECTED_DOWNTIME = False

        logging.info("[automatic-updates] pip install completed successfully")
        return True

    APT_INSTALL_HARD_TIMEOUT = 1800
    APT_PROGRESS_LOG_INTERVAL = 60
    DPKG_CONFIGURE_TIMEOUT = 120
    APT_FORCE_IPV4_PATH = '/etc/apt/apt.conf.d/99force-ipv4'

    def _ensure_apt_force_ipv4(self):
        if os.path.exists(self.APT_FORCE_IPV4_PATH):
            return
        try:
            with open(self.APT_FORCE_IPV4_PATH, 'w') as f:
                f.write('Acquire::ForceIPv4 "true";\n')
        except Exception as e:
            logging.warning(f"[automatic-updates] couldn't write {self.APT_FORCE_IPV4_PATH}: {e}")

    def _dpkg_configure_a(self):
        try:
            result = subprocess.run(['dpkg', '--configure', '-a'],
                                     capture_output=True, text=True, timeout=self.DPKG_CONFIGURE_TIMEOUT)
            if result.returncode != 0:
                logging.warning(f"[automatic-updates] dpkg --configure -a: {result.stderr.strip()}")
        except Exception as e:
            logging.warning(f"[automatic-updates] dpkg --configure -a failed to run: {e}")

    def _run_apt_install(self, apt_cmd, env):
        proc = subprocess.Popen(apt_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 env=env, text=True)
        start = time.time()
        last_log = start
        try:
            while proc.poll() is None:
                elapsed = time.time() - start
                if elapsed >= self.APT_INSTALL_HARD_TIMEOUT:
                    proc.kill()
                    proc.wait()
                    logging.error(f"[automatic-updates] apt install exceeded hard timeout of {self.APT_INSTALL_HARD_TIMEOUT}s, killed")
                    return False
                if time.time() - last_log >= self.APT_PROGRESS_LOG_INTERVAL:
                    logging.info(f"[automatic-updates] apt install still running ({int(elapsed)}s elapsed) ...")
                    last_log = time.time()
                time.sleep(2)
        finally:
            output = proc.stdout.read() if proc.stdout else ''

        if proc.returncode != 0:
            logging.error(f"[automatic-updates] apt install failed: {output.strip()[-2000:]}")
            return False
        return True

    def _apt_install_with_recovery(self, apt_cmd, env):
        if self._run_apt_install(apt_cmd, env):
            return True

        logging.warning("[automatic-updates] apt install failed -- attempting dpkg recovery and one retry ...")
        self._dpkg_configure_a()

        if self._run_apt_install(apt_cmd, env):
            logging.info("[automatic-updates] apt install succeeded after dpkg recovery")
            return True

        logging.error("[automatic-updates] apt install still failing after dpkg recovery, giving up for this cycle")
        return False

    def _install_missing_pip_requirements(self, req_file):
        try:
            from packaging.requirements import Requirement
            from importlib.metadata import version as installed_version, PackageNotFoundError
        except Exception as e:
            logging.error(f"[automatic-updates] can't check pip requirements: {e}")
            return True

        with open(req_file, 'r') as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith('#') and not line.startswith('--')]

        missing = []
        for line in lines:
            try:
                req = Requirement(line)
            except Exception:
                continue
            try:
                current = installed_version(req.name)
                if req.specifier and not req.specifier.contains(current, prereleases=True):
                    missing.append(line)
            except PackageNotFoundError:
                missing.append(line)

        if not missing:
            logging.info("[automatic-updates] all pip requirements already satisfied")
            return True

        logging.info(f"[automatic-updates] installing missing/updated pip requirements: {', '.join(missing)}")
        for req_str in missing:
            result = subprocess.run(
                ['pip3', 'install', '--break-system-packages', '--no-deps',
                 '--no-build-isolation', req_str],
                capture_output=True, text=True, timeout=180
            )
            if result.returncode != 0:
                logging.error(f"[automatic-updates] failed to install {req_str}: {result.stderr.strip()}")
                return False
        return True

    def _run_post_install_steps(self, source_dir):
        setup_path = os.path.join(source_dir, 'setup.py')
        if not os.path.exists(setup_path):
            logging.debug("[automatic-updates] no setup.py in this release, skipping post-install steps")
            return

        original_cwd = os.getcwd()
        try:
            os.chdir(source_dir)
            spec = importlib.util.spec_from_file_location('_pwnagotchi_setup', setup_path)
            setup_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(setup_module)
            setup_module.install_system_files()
            setup_module.install_patched_bettercap()
            setup_module.remove_stale_eth0_interfaces_file()
            setup_module.regenerate_motd()
            setup_module.restart_services()
        except Exception as e:
            logging.error(f"[automatic-updates] post-install steps failed: {e}")
        finally:
            os.chdir(original_cwd)

    def _apply(self):
        os.system('systemctl restart pwnagotchi')
