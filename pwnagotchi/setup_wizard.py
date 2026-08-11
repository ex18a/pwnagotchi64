import os
import re
import time
import tomlkit

import pwnagotchi.utils as utils

GREEN = '\033[0;32m'
CYAN = '\033[0;36m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
NC = '\033[0m'

CONFIG_HEADER_LINES = [
    "This file only contains what you've explicitly set via 'sudo pwnagotchi --setup'",
    "(or added by hand). Anything not listed here falls back to",
    "/etc/pwnagotchi/default.toml, which has every available setting -- for more",
    "advanced tuning than the wizard covers, copy the relevant key/section from",
    "there into this file.",
]

COMMON_DISPLAY_TYPES = [
    'waveshare_4',
    'waveshare_3',
    'waveshare_2',
    'waveshare_1',
    'inky',
    'oledhat',
    'displayhatmini',
]

PORTRAIT_DRIVER_MAP = {
    'waveshare_4': 'waveshare_4_portrait',
    'waveshare_3': 'waveshare_3_portrait',
}
REVERSE_PORTRAIT_DRIVER_MAP = {v: k for k, v in PORTRAIT_DRIVER_MAP.items()}

SECRET_KEYS = {'ui.web.password'}


def _get(d, dotted_key, default=None):
    cur = d
    for part in dotted_key.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _set_tomlkit(doc, dotted_key, value):
    parts = dotted_key.split('.')
    cur = doc
    for part in parts[:-1]:
        if part not in cur:
            cur[part] = tomlkit.table()
        cur = cur[part]
    cur[parts[-1]] = value


def _ask_str(prompt, current):
    raw = input(f"{prompt} [{current}]: ").strip()
    return current if raw == '' else raw


NAME_PATTERN = re.compile(r'^[a-zA-Z0-9\-]{2,25}$')


def _ask_hostname(prompt, current):
    while True:
        raw = input(f"{prompt} [{current}]: ").strip()
        value = current if raw == '' else raw
        if NAME_PATTERN.match(value):
            return value
        print(f"{RED}Invalid name: 2-25 characters, letters/numbers/hyphens only "
              f"(this becomes the device's real hostname).{NC}")


def _ask_int(prompt, current):
    while True:
        raw = input(f"{prompt} [{current}]: ").strip()
        if raw == '':
            return current
        try:
            return int(raw)
        except ValueError:
            print(f"{RED}Please enter a whole number.{NC}")


def _ask_yesno(prompt, current):
    default_str = 'Y/n' if current else 'y/N'
    raw = input(f"{prompt} [{default_str}]: ").strip().lower()
    if raw == '':
        return current
    return raw in ('y', 'yes')


def _ask_password(prompt, current):
    import getpass
    raw = getpass.getpass(f"{prompt} [leave blank to keep current]: ")
    return current if raw == '' else raw


def _ask_list(prompt, current):
    current_str = ', '.join(current)
    raw = input(f"{prompt} [{current_str}] (type 'clear' to remove all): ").strip()
    if raw == '':
        return None
    if raw.lower() == 'clear':
        return []
    return [w.strip() for w in raw.split(',') if w.strip()]


def _ensure_header(doc):
    if CONFIG_HEADER_LINES[0] in tomlkit.dumps(doc):
        return doc
    new_doc = tomlkit.document()
    for line in CONFIG_HEADER_LINES:
        new_doc.add(tomlkit.comment(line))
    new_doc.add(tomlkit.nl())
    for key, value in doc.body:
        if key is None:
            new_doc.add(value)
        else:
            new_doc.add(key, value)
    return new_doc


def _ask_choice(prompt, options, current):
    print(prompt)
    for i, opt in enumerate(options, 1):
        marker = '  <- current' if opt == current else ''
        print(f"  {i}. {opt}{marker}")
    print(f"  {len(options) + 1}. other (type it in manually)")
    while True:
        raw = input(f"Choose [1-{len(options) + 1}], or Enter to keep current: ").strip()
        if raw == '':
            return current
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(options):
                return options[n - 1]
            if n == len(options) + 1:
                manual = input("Enter the display type string exactly: ").strip()
                if manual:
                    return manual
                continue
        print(f"{RED}Invalid choice, try again.{NC}")


def run_wizard(args):
    if os.geteuid() != 0:
        print(f"{RED}[!] This writes to /etc/pwnagotchi/config.toml, please run it with sudo:{NC}")
        print(f"    sudo pwnagotchi --setup")
        return 1

    print(f"{CYAN}==========================================={NC}")
    print(f"{CYAN}     Pwnagotchi Configuration Wizard        {NC}")
    print(f"{CYAN}==========================================={NC}")
    print("Press Enter on any question to keep the current value shown in [brackets].\n")

    effective = utils.load_config(args)

    if os.path.exists(args.user_config):
        with open(args.user_config) as fp:
            doc = tomlkit.parse(fp.read())
    else:
        doc = tomlkit.document()

    changes = {}

    def set_value(dotted_key, value):
        changes[dotted_key] = value
        _set_tomlkit(doc, dotted_key, value)

    print(f"\n{YELLOW}[*] Basics{NC}")
    set_value('main.name', _ask_hostname("Device name", _get(effective, 'main.name')))

    home_networks = _ask_list(
        "Home WiFi network name(s), comma-separated",
        _get(effective, 'main.home_networks', [])
    )
    if home_networks is not None:
        set_value('main.home_networks', home_networks)

    whitelist = _ask_list(
        "Any other network name(s) to never attack, e.g. friends/neighbors, comma-separated",
        _get(effective, 'main.whitelist', [])
    )
    if whitelist is not None:
        set_value('main.whitelist', whitelist)

    print(f"\n{YELLOW}[*] Display{NC}")
    display_enabled = _ask_yesno("Do you have a screen attached", _get(effective, 'ui.display.enabled'))
    set_value('ui.display.enabled', display_enabled)
    if display_enabled:
        current_type = _get(effective, 'ui.display.type')
        chosen_type = _ask_choice(
            "What screen do you have?",
            COMMON_DISPLAY_TYPES,
            REVERSE_PORTRAIT_DRIVER_MAP.get(current_type, current_type)
        )
        set_value('ui.display.type', PORTRAIT_DRIVER_MAP.get(chosen_type, chosen_type))

    print(f"\n{YELLOW}[*] Battery (PiSugar 3){NC}")
    has_pisugar = _ask_yesno("Do you have a PiSugar 3 battery HAT",
                              _get(effective, 'main.plugins.pisugar3i2c.enabled'))
    set_value('main.plugins.pisugar3i2c.enabled', has_pisugar)
    if has_pisugar:
        set_value('main.plugins.pisugar3i2c.low_battery_shutdown_pct', _ask_int(
            "Battery % to safely auto-shutdown at",
            _get(effective, 'main.plugins.pisugar3i2c.low_battery_shutdown_pct')
        ))

    print(f"\n{YELLOW}[*] AI{NC}")
    set_value('ai.enabled', _ask_yesno(
        "Let the built-in AI tune behavior through trial and error (disable for a fixed, static personality instead)",
        _get(effective, 'ai.enabled')
    ))

    print(f"\n{YELLOW}[*] Web UI{NC}")
    print(f"{YELLOW}The default web UI login (pwnagotchi/pwnagotchi) is public knowledge -- "
          f"worth changing if this device will ever be reachable from a network you don't fully trust.{NC}")
    web_auth = _ask_yesno("Require a login for the web UI", _get(effective, 'ui.web.auth'))
    set_value('ui.web.auth', web_auth)
    if web_auth:
        set_value('ui.web.username', _ask_str("Web UI username", _get(effective, 'ui.web.username')))
        set_value('ui.web.password', _ask_password("Web UI password", _get(effective, 'ui.web.password')))

    print(f"\n{CYAN}==========================================={NC}")
    print(f"{CYAN}   About to write these changes to:{NC}")
    print(f"{CYAN}   {args.user_config}{NC}")
    print(f"{CYAN}==========================================={NC}")
    for key, value in changes.items():
        shown = '********' if key in SECRET_KEYS else value
        print(f"  {key} = {shown}")

    confirm = _ask_yesno("\nSave this configuration", True)
    if not confirm:
        print(f"{RED}[!] Aborted, nothing was written.{NC}")
        return 1

    doc = _ensure_header(doc)
    with open(args.user_config, 'w') as fp:
        fp.write(tomlkit.dumps(doc))

    print(f"\n{GREEN}[+] Configuration saved.{NC}")

    print(f"\n{YELLOW}[*] Bluetooth tethering setup is disabled here for now -- known stability "
          f"issues under heavy use, not fixed yet.{NC}")

    print(f"\n{GREEN}[+] Config saved, restarting pwnagotchi to apply changes...{NC}")
    print(f"{YELLOW}Press Ctrl+C to cancel the restart (the config is already saved).{NC}")
    try:
        for remaining in range(10, 0, -1):
            print(f"\r{YELLOW}Restarting in {remaining} seconds...{NC}", end='', flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{RED}[!] Restart cancelled -- run 'sudo systemctl restart pwnagotchi' "
              f"whenever you're ready.{NC}")
        return 0
    print()
    os.system('systemctl restart pwnagotchi')
    return 0
