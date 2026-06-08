import os
import logging
import subprocess
import time
import pwnagotchi.plugins as plugins

class HashVault(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.0'
    __description__ = 'Monitors, validates, and archives handshakes into a dedicated hash repository without deleting raw PCAPs.'

    def __init__(self):
        self.handshake_dir = '/root/handshakes/'
        self.hash_dir = os.path.join(self.handshake_dir, 'hashes')
        self.last_checked_mtime = {}

    def on_loaded(self):
        logging.info("[HashVault] Vault secured. Monitoring handshakes directory...")

        # Ensure the hashes subfolder exists right away
        if not os.path.exists(self.hash_dir):
            try:
                os.makedirs(self.hash_dir, exist_ok=True)
                logging.info(f"[HashVault] Created dedicated repository: {self.hash_dir}")
            except Exception as e:
                logging.error(f"[HashVault] Failed to create repository folder: {e}")

        self._startup_cleanup()

    def _startup_cleanup(self):
        if not os.path.exists(self.handshake_dir):
            return
        for filename in os.listdir(self.handshake_dir):
            if filename.endswith('.pcap'):
                self._attempt_valid_pcap(os.path.join(self.handshake_dir, filename))

    def on_sleep(self, agent, t):
        self._process_files()

    def _process_files(self):
        if not os.path.exists(self.handshake_dir):
            return

        for filename in os.listdir(self.handshake_dir):
            if filename.endswith('.pcap'):
                fullpath = os.path.join(self.handshake_dir, filename)

                try:
                    current_mtime = os.path.getmtime(fullpath)
                except Exception:
                    continue

                # Process files that have been idle for at least 10 seconds
                if time.time() - current_mtime > 10:
                    last_checked = self.last_checked_mtime.get(fullpath, 0)

                    # Only re-scan if the file has been modified since the last check
                    if current_mtime > last_checked:
                        self._attempt_valid_pcap(fullpath, current_mtime)

    def _attempt_valid_pcap(self, pcap_path, current_mtime=None):
        filename = os.path.basename(pcap_path)
        hash_filename = filename.replace('.pcap', '.22000')
        output_hash = os.path.join(self.hash_dir, hash_filename)

        # Skip scanning if a valid hash already exists in the vault
        if os.path.exists(output_hash):
            return

        logging.info(f"[HashVault] Analyzing packet updates for: {filename}")

        # Execute extraction tool targeting the safe subfolder
        subprocess.run(
            ['/usr/bin/hcxpcapngtool', '-o', output_hash, pcap_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Success notification if a valid signature was found
        if os.path.exists(output_hash):
            logging.info(f"[HashVault] Valid handshake locked into vault: {hash_filename}")

        # Record evaluation timestamp to prevent loop processing
        if current_mtime is None:
            try:
                current_mtime = os.path.getmtime(pcap_path)
            except Exception:
                current_mtime = time.time()

        self.last_checked_mtime[pcap_path] = current_mtime
