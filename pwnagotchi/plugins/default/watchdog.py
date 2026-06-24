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
        self._blind_override_active = False
        self._original_view_set = None

    def on_loaded(self):
        logging.info(f"[Watchdog] Active. Monitoring {self.interface}")

    def on_epoch(self, agent, epoch, epoch_data):
        # Stop checking if already dying
        if self.lockdown_triggered:
            return

        # Pin a "blind" face/status to the screen for as long as blind_for
        # stays above 0, regardless of what the normal recon/wait status
        # cycling would otherwise be showing. Cleared the moment blind_for
        # drops back to 0, or superseded by _lockdown_reboot()'s own crash
        # message if things escalate that far.
        try:
            blind_now = agent._epoch.blind_for
        except AttributeError:
            blind_now = 0

        if blind_now > 0:
            self._enable_blind_override(agent)
            # write straight through the saved original setter -- the
            # filter we just installed would otherwise swallow this too
            self._original_view_set('face', "(\u2613\u203f\u203f\u2613)")
            self._original_view_set('status', f"I'm BLIND ({blind_now})")
        else:
            self._disable_blind_override(agent)

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
            if self._is_bettercap_still_down_after_grace_period():
                logging.error("[Watchdog] bettercap still down after grace period! Executing lockdown reboot...")
                self._save_crash_log("BETTERCAP_SERVICE_DOWN")
                self._lockdown_reboot(agent, "bettercap crashed and didn't recover")
                return
            else:
                logging.info("[Watchdog] bettercap recovered on its own, no reboot needed.")

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

    def _enable_blind_override(self, agent):
        if self._blind_override_active:
            return
        self._blind_override_active = True
        self._original_view_set = agent.view().set

        original = self._original_view_set

        def _filtered_set(key, value, *args, **kwargs):
            if key in ('face', 'status'):
                # swallow everything else trying to touch face/status while
                # the blind overlay is up -- only our own writes (made
                # directly through `original`, bypassing this filter) get
                # through, which is what keeps it pinned on screen instead
                # of getting stomped by the normal "Waiting for Xs..." cycling.
                return
            return original(key, value, *args, **kwargs)

        agent.view().set = _filtered_set

    def _disable_blind_override(self, agent):
        if not self._blind_override_active:
            return
        self._blind_override_active = False
        if self._original_view_set is not None:
            agent.view().set = self._original_view_set
            self._original_view_set = None

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

    def _is_bettercap_still_down_after_grace_period(self, grace_seconds=60, poll_interval=5):
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
                return False
        return self._is_bettercap_service_down()

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

    def _lockdown_reboot(self, agent, reason_text):
        self.lockdown_triggered = True

        # Restore the real view.set() first -- otherwise the blind-overlay
        # filter we may have installed would swallow this very crash
        # message too, since it's also writing to 'status'.
        self._disable_blind_override(agent)

        # Trigger native reboot face
        agent.set_rebooting()

        # Draw custom text
        agent.view().set('status', f"Crash: {reason_text}!")
        agent.view().update(force=True)

        # stop the UI thread
        agent.view().update = lambda *args, **kwargs: None
        agent.view().set = lambda *args, **kwargs: None
        logging.info("[Watchdog] UI Lobotomized. Safe to perform background tasks.")

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
