import os
import logging
import subprocess
from datetime import datetime
import pwnagotchi.plugins as plugins
import pwnagotchi

class Watchdog(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.1.0'
    __description__ = 'Monitors physical Wi-Fi hardware health, saves forensic logs on failure, and triggers recovery reboots.'

    def __init__(self):
        self.interface = pwnagotchi.config['main']['iface']
        self.crashes_detected = 0
        self.crash_log_path = '/var/log/pwnagotchi_crashes.log'

    def on_loaded(self):
        logging.info(f"[Watchdog] Active. Monitoring physical health of {self.interface}...")

    def on_epoch(self, agent, epoch, epoch_data):
        if not self._is_interface_healthy():
            self.crashes_detected += 1
            logging.warning(f"[Watchdog] Hardware anomaly detected on {self.interface}! (Strike {self.crashes_detected}/2)")

            # Wait for two consecutive failed checks before taking extreme action
            if self.crashes_detected >= 2:
                logging.error("[Watchdog] Nexmon driver failure confirmed. Archiving logs and rebooting...")
                self._save_crash_log()
                self._reboot_system()
        else:
            # If the interface is healthy, reset the strike counter
            self.crashes_detected = 0

    def _is_interface_healthy(self):
        try:
            # 1. Check if the interface exists and is UP in the Linux networking stack
            ip_link = subprocess.run(['ip', 'link', 'show', self.interface], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if ip_link.returncode != 0:
                return False

            if "state DOWN" in ip_link.stdout:
                return False

            # 2. Check the kernel log for Broadcom/Nexmon firmware fatal crashes
            dmesg = subprocess.run(['dmesg'], stdout=subprocess.PIPE, text=True)
            recent_logs = "\n".join(dmesg.stdout.splitlines()[-50:])

            if "brcmf_sdio_firmware_fatal" in recent_logs or "brcmfmac: brcmf_bus_txctl" in recent_logs:
                return False

        except Exception as e:
            logging.error(f"[Watchdog] Error checking physical health: {e}")
        return True

    def _save_crash_log(self):
        try:
            # Set up the separator block
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            separator_tag = "------------ CRASH REPORT:"
            separator_full = f"{separator_tag} {timestamp} ------------\n"

            # Grab the last 50 lines of the Pwnagotchi log
            try:
                pwn_output = subprocess.run(['tail', '-n', '50', '/var/log/pwnagotchi.log'], stdout=subprocess.PIPE, text=True)
                pwn_logs = pwn_output.stdout if pwn_output.stdout else "No Pwnagotchi logs found.\n"
            except Exception:
                pwn_logs = "Failed to read Pwnagotchi logs.\n"

            # Grab the last 50 lines of the dmesg kernel log
            try:
                dmesg_output = subprocess.run(['dmesg'], stdout=subprocess.PIPE, text=True)
                dmesg_logs = "\n".join(dmesg_output.stdout.splitlines()[-50:]) if dmesg_output.stdout else "No dmesg logs found.\n"
            except Exception:
                dmesg_logs = "Failed to read dmesg logs.\n"

            # Construct the final crash block
            new_crash_entry = (
                f"{separator_full}"
                f"[PWNAGOTCHI LOGS - LAST 50 LINES]\n{pwn_logs}\n"
                f"[DMESG LOGS - LAST 50 LINES]\n{dmesg_logs}\n\n"
            )

            # Manage the 50-crash limit
            if os.path.exists(self.crash_log_path):
                with open(self.crash_log_path, 'r') as f:
                    content = f.read()

                # Split the file into chunks based on the separator tag
                crash_blocks = content.split(separator_tag)
                crash_blocks = [block for block in crash_blocks if block.strip()] # Filter out empty chunks

                # If we have reached 50 crashes, keep the newest 49, then append the new one
                if len(crash_blocks) >= 50:
                    crash_blocks = crash_blocks[-49:]

                    with open(self.crash_log_path, 'w') as f:
                        for block in crash_blocks:
                            f.write(f"{separator_tag}{block}")
                        f.write(new_crash_entry)
                    return

            # If the file doesn't exist or is under the limit, just append normally
            with open(self.crash_log_path, 'a') as f:
                f.write(new_crash_entry)

        except Exception as e:
            logging.error(f"[Watchdog] Critical failure while attempting to save crash log: {e}")

    def _reboot_system(self):
        subprocess.run(['sudo', 'reboot'])
