import os
import logging
import subprocess
from datetime import datetime
import pwnagotchi.plugins as plugins
import pwnagotchi

class Watchdog(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.7.0'
    __description__ = 'Monitors physical Wi-Fi hardware health via iw dev and triggers recovery reboots.'

    def __init__(self):
        self.interface = pwnagotchi.config['main']['iface']
        self.crashes_detected = 0
        self.crash_log_path = '/var/log/pwnagotchi_crashes.log'

    def on_loaded(self):
        logging.info(f"[Watchdog] Active. Hardcore monitoring of {self.interface} via mac80211 subsystem...")

    def on_epoch(self, agent, epoch, epoch_data):
        blind_epochs = agent.session().get('blind', 0)
        is_blind = (blind_epochs >= 1)

        health_status = self._is_interface_healthy(is_blind)

        if health_status == "FATAL_CRASH":
            logging.error(f"[Watchdog] FATAL dmesg crash detected on {self.interface}! Archiving and rebooting...")
            self._save_crash_log("DMESG_CRASH")
            self._trigger_native_reboot(agent, "Hardware Crash")

        elif health_status == "FATAL_VANISHED":
            logging.error(f"[Watchdog] SILENT DEAFNESS: {self.interface} vanished from iw dev! Archiving and rebooting...")
            self._save_crash_log("IW_DEV_VANISHED")
            self._trigger_native_reboot(agent, "Silent Deafness")

        elif health_status == "DOWN":
            self.crashes_detected += 1
            logging.warning(f"[Watchdog] Interface {self.interface} is DOWN! (Strike {self.crashes_detected}/2)")

            if self.crashes_detected >= 2:
                logging.error("[Watchdog] Interface failed to recover. Archiving logs and rebooting...")
                self._save_crash_log("IP_LINK_DOWN")
                self._trigger_native_reboot(agent, "Interface Down")
        else:
            if self.crashes_detected > 0:
                logging.info(f"[Watchdog] {self.interface} recovered naturally. Resetting strike counter.")
            self.crashes_detected = 0

    def _is_interface_healthy(self, is_blind):
        try:
            if is_blind:
                iw_output = subprocess.run(['iw', 'dev'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if iw_output.returncode == 0 and f"Interface {self.interface}" not in iw_output.stdout:
                    return "FATAL_VANISHED"

            dmesg = subprocess.run(['dmesg'], stdout=subprocess.PIPE, text=True)
            recent_logs = "\n".join(dmesg.stdout.splitlines()[-50:])
            if "brcmf_fw_crashed" in recent_logs or "failed backplane access over SDIO" in recent_logs:
                return "FATAL_CRASH"

            ip_link = subprocess.run(['ip', 'link', 'show', self.interface], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if ip_link.returncode != 0 or "state DOWN" in ip_link.stdout:
                return "DOWN"

        except Exception as e:
            logging.error(f"[Watchdog] Error checking physical health: {e}")

        return "HEALTHY"

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

    def _trigger_native_reboot(self, agent, reason_text):
        logging.info(f"[Watchdog] Triggering custom native reboot sequence: {reason_text}")

        try:
            # 1. Put the UI into the panic state (This natively draws the dead face)
            agent.set_rebooting()

            # 2. Overwrite the generic default panic text with our exact reason
            agent.view().set('status', f"Crash: {reason_text}! Rebooting...")
            agent.view().update(force=True)

            # 3. Save the recovery data (JSON backup) so the current session isn't lost
            agent._save_recovery_data()
        except Exception as e:
            logging.error(f"[Watchdog] Error during UI lockdown: {e}")

        # 4. Issue the actual OS-level reboot command
        pwnagotchi.reboot()

        # 5. The Ultimate UI Lock: Paralyze the AI thread so it cannot overwrite the screen
        logging.info("[Watchdog] Paralyzing the AI brain to lock the e-ink display...")
        import time
        while True:
            time.sleep(1)
