import os
import logging
import subprocess
import time
from datetime import datetime
import pwnagotchi.plugins as plugins
import pwnagotchi

class Watchdog(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.7.2'
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
                logging.error(f"[Watchdog] blind=2: {self.interface} is STILL missing! Executing lockdown reboot...")
                self._save_crash_log("IW_DEV_VANISHED")
                self._lockdown_reboot(agent, f"{self.interface} vanished")

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

            new_crash_entry = (
                f"{separator_full}"
                f"[PWNAGOTCHI LOGS - LAST 50 LINES]\n{pwn_logs}\n"
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
            logging.error(f"[Watchdog] Critical failure while attempting to save crash log: {e}")
