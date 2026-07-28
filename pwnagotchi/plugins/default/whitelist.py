import os
import logging
import pwnagotchi
import pwnagotchi.plugins as plugins


class Whitelist(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '2.4.1'
    __description__ = 'Harvests MACs/SSIDs, syncs with HashVault, supports case-sensitive SSIDs, and safely blanks memory on unload.'

    def __init__(self):
        self.whitelist_path = '/root/.whitelist'
        self.handshake_dir = None
        self.hash_dir = None

    def on_loaded(self):
        config = pwnagotchi.config
        self.handshake_dir = config.get('bettercap', {}).get('handshakes', '/root/handshakes')
        parent_dir = os.path.dirname(os.path.normpath(self.handshake_dir))
        self.hash_dir = os.path.join(parent_dir, 'hashes')

        self._ensure_whitelist_file_exists()

        config_entries = pwnagotchi.config['main'].get('whitelist', [])
        if config_entries:
            logging.info(f"[whitelist] Found entries in config.toml. Moving them to physical file.")
            self._harvest_config_entries(config_entries)

        pwnagotchi.config['main']['whitelist'] = []

        logging.info("[whitelist] Plugin active. Syncing with HashVault...")
        self._process_and_sync()

    def on_epoch(self, agent, epoch, epoch_data):
        self._process_and_sync()

    def on_sleep(self, agent, t):
        self._process_and_sync()

    def _ensure_whitelist_file_exists(self):
        try:
            if not os.path.exists(self.whitelist_path):
                open(self.whitelist_path, 'a').close()
                os.chmod(self.whitelist_path, 0o666)
                logging.info(f"[whitelist] Created missing whitelist file at {self.whitelist_path}")
        except Exception as e:
            logging.error(f"[whitelist] Error creating whitelist file: {e}")

    def _harvest_config_entries(self, config_entries):
        self._ensure_whitelist_file_exists()
        try:
            with open(self.whitelist_path, 'r') as f:
                existing_entries = [line.split('#')[0].strip() for line in f if line.strip()]

            added = False
            with open(self.whitelist_path, 'a') as f:
                for entry in config_entries:
                    clean_entry = entry.strip()

                    if ':' in clean_entry:
                        clean_entry = clean_entry.lower()

                    if clean_entry and clean_entry not in existing_entries:
                        f.write(f"{clean_entry} # Manual_Config_Entry\n")
                        existing_entries.append(clean_entry)
                        added = True

            if added:
                logging.info(f"[whitelist] Successfully saved manual config entries into {self.whitelist_path}.")
        except Exception as e:
            logging.error(f"[whitelist] Error harvesting config entries: {e}")

    def _process_and_sync(self):
        self._scan_handshakes_for_whitelist()
        self._inject_into_runtime()

    def _scan_handshakes_for_whitelist(self):
        if not os.path.exists(self.hash_dir):
            return

        for filename in os.listdir(self.hash_dir):
            if filename.endswith('.22000'):
                pcap_file = filename.replace('.22000', '.pcap')
                pcap_path = os.path.join(self.handshake_dir, pcap_file)
                hash_path = os.path.join(self.hash_dir, filename)

                if os.path.exists(pcap_path) and os.path.exists(hash_path):
                    self._extract_and_append_mac(filename)

    def _extract_and_append_mac(self, hash_filename):
        try:
            clean_name = hash_filename.replace('.22000', '')
            parts = clean_name.rsplit('_', 1)

            if len(parts) == 2:
                network_name = parts[0]
                raw_mac = parts[1].lower()

                if len(raw_mac) == 12:
                    formatted_mac = ":".join(raw_mac[i:i+2] for i in range(0, 12, 2))

                    self._ensure_whitelist_file_exists()

                    with open(self.whitelist_path, 'r') as f:
                        existing_entries = [line.split('#')[0].strip() for line in f if line.strip()]

                    if formatted_mac not in existing_entries:
                        with open(self.whitelist_path, 'a') as f:
                            f.write(f"{formatted_mac} # {network_name}\n")
                        logging.info(f"[whitelist] Logged new verified MAC: {formatted_mac} ({network_name})")
        except Exception as e:
            logging.error(f"[whitelist] MAC Extraction error: {e}")

    def _inject_into_runtime(self):
        self._ensure_whitelist_file_exists()

        try:
            with open(self.whitelist_path, 'r') as f:
                external_entries = [line.split('#')[0].strip() for line in f if line.strip() and not line.strip().startswith('#')]

            external_entries = [m for m in external_entries if m]

            if external_entries:
                current_config = pwnagotchi.config['main']['whitelist']
                added_count = 0
                for entry in external_entries:
                    if entry not in current_config:
                        current_config.append(entry)
                        added_count += 1

                if added_count > 0:
                    logging.info(f"[whitelist] Injected {added_count} verified entries into runtime.")
        except Exception as e:
            logging.error(f"[whitelist] Sync error: {e}")

    def on_unload(self, ui):
        logging.info("[whitelist] Plugin disabled. Wiping the runtime whitelist completely blank...")
        pwnagotchi.config['main']['whitelist'] = []
