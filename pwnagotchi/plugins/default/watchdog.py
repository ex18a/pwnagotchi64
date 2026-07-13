import os
import logging
import subprocess
import time
from datetime import datetime
import pwnagotchi.plugins as plugins
import pwnagotchi

class Watchdog(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.7.3'
    __description__ = 'wifi hardware check with crash logging'

    def __init__(self):
        self.interface = pwnagotchi.config['main']['iface']
        self.lockdown_triggered = False
        self.crash_log_path = '/var/log/pwnagotchi_crashes.log'

    def on_loaded(self):
        logging.info(f"[Watchdog] Active. Monitoring {self.interface}")

    def on_epoch(self, agent, epoch, epoch_data):
        # Stop checking if already dying
        if self.lockdown_triggered:
            return

        try:
            blind_now = agent._epoch.blind_for
        except AttributeError:
            blind_now = 0

        if blind_now > 0:
            agent.view().on_blind(blind_now)

        # If bettercap's systemd unit isn't active, give systemd's own
        # Restart=on-failure policy a chance to bring it back on its own
        # first (confirmed: a "concurrent map iteration and map write" Go
        # fatal error kills the whole process, but systemd typically
        # restarts it within ~30s without any help from us). Only escalate
        # to a full device reboot if it's STILL down after that grace
        # period -- rebooting the instant we see one bad reading would
        # trigger a slower, more disruptive full reboot for exactly the
        # failure that was already about to fix itself.
        if self._is_bettercap_service_down():
            logging.warning("[Watchdog] bettercap service not active -- giving systemd up to 60s to auto-restart it ...")
            if self._is_bettercap_still_down_after_grace_period(agent):
                logging.error("[Watchdog] bettercap still down after grace period! Executing lockdown reboot...")
                self._save_crash_log("BETTERCAP_SERVICE_DOWN")
                self._lockdown_reboot(agent, "bettercap crashed and didn't recover")
                return
            else:
                logging.info("[Watchdog] bettercap recovered and API is responding.")
                self._ensure_wifi_recon_running(agent)

        # Ask agent for the blind counter
        try:
            blind_epochs = agent._epoch.blind_for
        except AttributeError:
            blind_epochs = 0

        # Do nothing if can see perfectly fine
        if blind_epochs == 0:
            return

        # Check if the interface is physically missing
        is_missing = self._is_interface_missing()

        # STAGE 1: The Warning
        if blind_epochs == 1:
            if is_missing:
                logging.warning(f"[Watchdog] blind=1: {self.interface} is missing! Nexmon firmware likely crashed. Waiting 1 epoch...")
            else:
                self._ensure_wifi_recon_running(agent)
            return

        # STAGE 2: The Kill
        if blind_epochs >= 2:
            if is_missing:
                logging.error(f"[Watchdog] blind={blind_epochs}: {self.interface} is STILL missing! Executing lockdown reboot...")
                self._save_crash_log("IW_DEV_VANISHED")
                self._lockdown_reboot(agent, f"{self.interface} vanished")
                return

            # The interface can be present and healthy while bettercap
            # itself has crashed, hung, or dropped its REST/websocket API --
            # that leaves the agent blind with no hardware-level symptom at
            # all, so it needs its own independent check rather than relying
            # on _is_interface_missing() to catch it.
            if self._is_bettercap_unresponsive(agent):
                logging.error(f"[Watchdog] blind={blind_epochs}: {self.interface} present but bettercap is unresponsive! Executing lockdown reboot...")
                self._save_crash_log("BETTERCAP_UNRESPONSIVE")
                self._lockdown_reboot(agent, "bettercap unresponsive")
            else:
                # bettercap is up and responsive, mon0 is present, yet
                # blind_for keeps climbing -- last-resort safety net for
                # any reason wifi.recon might silently not be running
                # (confirmed cause on this device: a bettercap process
                # crash+restart -- see the grace-period recovery path
                # above -- but this catches it even if that path is
                # somehow skipped, e.g. a crash+restart cycle that
                # completes between epoch checks)
                self._ensure_wifi_recon_running(agent)

    def _is_bettercap_service_down(self):
        try:
            result = subprocess.run(['systemctl', 'is-active', 'bettercap'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            # systemctl is-active prints "active" and exits 0 when healthy;
            # anything else ("failed", "inactive", "activating", ...) means
            # the unit isn't in a normal running state.
            return result.stdout.strip() != 'active'
        except Exception as e:
            logging.error(f"[Watchdog] Error checking bettercap service status: {e}")
            return False  # don't false-trigger a reboot if systemctl itself is the thing failing

    def _is_bettercap_still_down_after_grace_period(self, agent, grace_seconds=60, poll_interval=5):
        # Blocks on_epoch for up to grace_seconds -- only while bettercap is
        # already known to be down, in which case the agent's own REST calls
        # are failing anyway, so this isn't costing anything beyond what's
        # already lost. Polls every poll_interval seconds so it returns as
        # soon as systemd's restart succeeds, rather than always waiting
        # the full window.
        waited = 0
        while waited < grace_seconds:
            time.sleep(poll_interval)
            waited += poll_interval
            if not self._is_bettercap_service_down():
                # Service is back -- now verify the REST API is actually
                # responding before declaring recovery, since systemd marks
                # the unit active before bettercap's API is ready
                try:
                    agent.session()
                    logging.info("[Watchdog] bettercap service active and API responding after %ds." % waited)
                    return False
                except Exception:
                    logging.warning("[Watchdog] bettercap service active but API not ready yet, waiting...")
                    continue
        return True

    def _is_interface_missing(self):
        try:
            # use the 'info' command because it cuts through fake "UP" statuses
            iw_output = subprocess.run(['iw', 'dev', self.interface, 'info'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if iw_output.returncode != 0:
                return True # It threw an error, the interface is gone
        except Exception as e:
            logging.error(f"[Watchdog] Error executing iw command: {e}")
            return True # Failsafe

        return False # Interface is healthy and present

    def _is_bettercap_unresponsive(self, agent):
        # agent.session() is the same REST call get_access_points() makes
        # internally -- if bettercap's API has died or hung, this raises
        # (or, if bettercap is wedged rather than dead, could block; if that
        # turns out to happen in practice this may need its own timeout).
        try:
            agent.session()
            return False
        except Exception as e:
            logging.error(f"[Watchdog] bettercap session() check failed: {e}")
            return True

    def _ensure_wifi_recon_running(self, agent):
        # A bettercap process crash+restart (confirmed on-device: an
        # internal Go panic in bettercap's own JSON marshaling code,
        # completely unrelated to nexmon/hardware) starts fresh -- every
        # module off, every wifi.* setting reverted to bettercap's own
        # bare defaults. Watchdog's crash-recovery check only confirms
        # the REST API responds again; that says nothing about whether
        # the wifi.recon module (the thing actually doing the scanning)
        # survived. Confirmed on-device: a device can sit indefinitely
        # "healthy" by every other check here -- mon0 present, API
        # responding -- while genuinely blind for 90+ minutes because
        # nothing is actually listening, fixed instantly the moment
        # wifi.recon is manually turned back on.
        try:
            session = agent.session()
            wifi_module = next((m for m in session.get('modules', []) if m.get('name') == 'wifi'), None)
            if wifi_module is not None and wifi_module.get('running'):
                return  # already running, nothing to do
        except Exception as e:
            logging.error(f"[Watchdog] Error checking wifi.recon module state: {e}")
            return

        logging.warning("[Watchdog] wifi.recon module is not running -- restarting it and re-applying wifi settings")
        try:
            agent._reset_wifi_settings()
            agent.start_module('wifi.recon')
        except Exception as e:
            logging.error(f"[Watchdog] Failed to restart wifi.recon: {e}")

    def _lockdown_reboot(self, agent, reason_text):
        self.lockdown_triggered = True

        # Trigger native reboot face
        agent.set_rebooting()

        # Draw custom text
        agent.view().set('status', f"Crash: {reason_text}!")
        agent.view().update(force=True)

        # stop the UI thread
        agent.view().update = lambda *args, **kwargs: None
        agent.view().set = lambda *args, **kwargs: None
        logging.info("[Watchdog] UI updates disabled, proceeding with reboot cleanup.")

        # Save session data
        try:
            agent._save_recovery_data()
        except Exception:
            pass

        # E-ink Settle Time
        time.sleep(3)

        # Reboot OS
        logging.critical("[Watchdog] Natively rebooting...")
        pwnagotchi.reboot()

        # Trap the Python thread
        while True:
            time.sleep(1)

    def _save_crash_log(self, crash_reason="UNKNOWN"):
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            separator_tag = "------------ CRASH REPORT:"
            separator_full = f"{separator_tag} [{crash_reason}] {timestamp} ------------\n"

            try:
                pwn_output = subprocess.run(['tail', '-n', '50', '/var/log/pwnagotchi.log'], stdout=subprocess.PIPE, text=True)
                pwn_logs = pwn_output.stdout if pwn_output.stdout else "No Pwnagotchi logs found.\n"
            except Exception:
                pwn_logs = "Failed to read Pwnagotchi logs.\n"

            try:
                dmesg_output = subprocess.run(['dmesg'], stdout=subprocess.PIPE, text=True)
                dmesg_logs = "\n".join(dmesg_output.stdout.splitlines()[-50:]) if dmesg_output.stdout else "No dmesg logs found.\n"
            except Exception:
                dmesg_logs = "Failed to read dmesg logs.\n"

            try:
                # This is where the actual root-cause stack trace lives for
                # a bettercap-side crash (e.g. the Go runtime fatal error) --
                # pwnagotchi's own log and dmesg won't show it. 250 lines
                # because a full Go panic dump (goroutine stacks included)
                # routinely runs well past 100 lines on its own.
                bcap_output = subprocess.run(['journalctl', '-u', 'bettercap', '-n', '250', '--no-pager'],
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                bcap_logs = bcap_output.stdout if bcap_output.stdout else "No bettercap logs found.\n"
            except Exception:
                bcap_logs = "Failed to read bettercap logs.\n"

            new_crash_entry = (
                f"{separator_full}"
                f"[PWNAGOTCHI LOGS - LAST 50 LINES]\n{pwn_logs}\n"
                f"[BETTERCAP LOGS - LAST 250 LINES]\n{bcap_logs}\n"
                f"[DMESG LOGS - LAST 50 LINES]\n{dmesg_logs}\n\n"
            )

            if os.path.exists(self.crash_log_path):
                with open(self.crash_log_path, 'r') as f:
                    content = f.read()

                crash_blocks = content.split(separator_tag)
                crash_blocks = [block for block in crash_blocks if block.strip()]

                if len(crash_blocks) >= 50:
                    crash_blocks = crash_blocks[-49:]
                    with open(self.crash_log_path, 'w') as f:
                        for block in crash_blocks:
                            f.write(f"{separator_tag}{block}")
                        f.write(new_crash_entry)
                    return

            with open(self.crash_log_path, 'a') as f:
                f.write(new_crash_entry)

        except Exception as e:
            logging.error(f"[Watchdog] Failed to save crash log data: {e}")
