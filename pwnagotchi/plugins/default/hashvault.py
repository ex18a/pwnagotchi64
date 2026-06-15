import os
import logging
import subprocess
import time
import pwnagotchi
import pwnagotchi.plugins as plugins

class HashVault(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.3.1'
    __description__ = 'Monitors handshakes via config and archives into a sibling hashes folder.'

    def __init__(self):
        self.handshake_dir = None
        self.hash_dir = None
        self.last_checked_mtime = {}

    def on_loaded(self):
        try:
            # Access the global configuration dictionary
            config = pwnagotchi.config
            self.handshake_dir = config.get('bettercap', {}).get('handshakes', '/root/handshakes')

            # Calculate the sibling path
            parent_dir = os.path.dirname(os.path.normpath(self.handshake_dir))
            self.hash_dir = os.path.join(parent_dir, 'hashes')

            logging.info(f"[HashVault] Monitoring handshakes at: {self.handshake_dir}")
            logging.info(f"[HashVault] Vaulting hashes to: {self.hash_dir}")

            if not os.path.exists(self.hash_dir):
                os.makedirs(self.hash_dir, exist_ok=True)

            self._startup_cleanup()
        except Exception as e:
            logging.error(f"[HashVault] CRITICAL LOAD ERROR: {e}")

    def _startup_cleanup(self):
        if not self.handshake_dir or not os.path.exists(self.handshake_dir):
            return
        for filename in os.listdir(self.handshake_dir):
            if filename.endswith('.pcap'):
                self._attempt_valid_pcap(os.path.join(self.handshake_dir, filename))

    def on_sleep(self, agent, t):
        self._process_files()

    def _process_files(self):
        if not self.handshake_dir or not os.path.exists(self.handshake_dir):
            return

        for filename in os.listdir(self.handshake_dir):
            if filename.endswith('.pcap'):
                fullpath = os.path.join(self.handshake_dir, filename)
                try:
                    current_mtime = os.path.getmtime(fullpath)
                except Exception:
                    continue

                if time.time() - current_mtime > 10:
                    last_checked = self.last_checked_mtime.get(fullpath, 0)
                    if current_mtime > last_checked:
                        self._attempt_valid_pcap(fullpath, current_mtime)

    def _attempt_valid_pcap(self, pcap_path, current_mtime=None):
        filename = os.path.basename(pcap_path)
        hash_filename = filename.replace('.pcap', '.22000')
        output_hash = os.path.join(self.hash_dir, hash_filename)

        if os.path.exists(output_hash):
            return

        logging.info(f"[HashVault] Analyzing: {filename}")

        subprocess.run(
            ['/usr/bin/hcxpcapngtool', '-o', output_hash, pcap_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        if os.path.exists(output_hash):
            logging.info(f"[HashVault] Vaulted: {hash_filename}")

        if current_mtime is None:
            try:
                current_mtime = os.path.getmtime(pcap_path)
            except Exception:
                current_mtime = time.time()

        self.last_checked_mtime[pcap_path] = current_mtime
