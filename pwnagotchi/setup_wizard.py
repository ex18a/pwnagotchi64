import os
import tomlkit

import pwnagotchi.utils as utils

GREEN = '\033[0;32m'
CYAN = '\033[0;36m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
NC = '\033[0m'

# Kept short and curated on purpose -- the full driver list in
# pwnagotchi/ui/hw/__init__.py has ~25 entries, most of which nobody
# running this wizard will ever have. Anyone on something obscure can
# still type its exact `type` string manually via the "other" option.
COMMON_DISPLAY_TYPES = [
    'waveshare_4',
    'waveshare_4_portrait',
    'waveshare_3',
    'waveshare_3_portrait',
    'waveshare_2',
    'waveshare_1',
    'inky',
    'oledhat',
    'displayhatmini',
]

# Never echoed back in the confirmation summary, even though the real
# value is what actually gets written to disk.
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

    # utils.load_config() also makes sure /etc/pwnagotchi/default.toml exists
    # and migrates any /boot-dropped config -- reused here so this wizard
    # works correctly on a totally fresh, never-booted-pwnagotchi install too,
    # same as the real startup path in bin/pwnagotchi. It's only used here to
    # read the *effective* current values to show as prompt defaults -- the
    # actual on-disk write further down goes through tomlkit against the raw
    # override file instead, so any comments/formatting already in
    # config.toml survive untouched.
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

    # --- Basics ---
    print(f"\n{YELLOW}[*] Basics{NC}")
    set_value('main.name', _ask_str("Device name", _get(effective, 'main.name')))

    set_value('main.iface', _ask_str(
        "WiFi monitor interface (mon0 is correct for the built-in chip; "
        "use wlan1 or similar for a supported USB dongle instead)",
        _get(effective, 'main.iface')
    ))

    current_whitelist = ', '.join(_get(effective, 'main.whitelist', []))
    whitelist_raw = input(f"Home network name(s) to never attack, comma-separated [{current_whitelist}]: ").strip()
    if whitelist_raw != '':
        set_value('main.whitelist', [w.strip() for w in whitelist_raw.split(',') if w.strip()])

    # --- Display ---
    print(f"\n{YELLOW}[*] Display{NC}")
    display_enabled = _ask_yesno("Do you have a screen attached", _get(effective, 'ui.display.enabled'))
    set_value('ui.display.enabled', display_enabled)
    if display_enabled:
        set_value('ui.display.type', _ask_choice(
            "What screen do you have?",
            COMMON_DISPLAY_TYPES,
            _get(effective, 'ui.display.type')
        ))
        set_value('ui.display.rotation', _ask_int(
            "Display rotation in degrees (0 or 180 are the only ones that make sense)",
            _get(effective, 'ui.display.rotation')
        ))

    # --- PiSugar 3 ---
    print(f"\n{YELLOW}[*] Battery (PiSugar 3){NC}")
    has_pisugar = _ask_yesno("Do you have a PiSugar 3 battery HAT",
                              _get(effective, 'main.plugins.pisugar3i2c.enabled'))
    set_value('main.plugins.pisugar3i2c.enabled', has_pisugar)
    if has_pisugar:
        set_value('main.plugins.pisugar3i2c.low_battery_shutdown_pct', _ask_int(
            "Battery % to safely auto-shutdown at",
            _get(effective, 'main.plugins.pisugar3i2c.low_battery_shutdown_pct')
        ))

    # --- AI ---
    print(f"\n{YELLOW}[*] AI{NC}")
    set_value('ai.enabled', _ask_yesno(
        "Let the built-in AI tune behavior through trial and error (disable for a fixed, static personality instead)",
        _get(effective, 'ai.enabled')
    ))

    # --- Web UI ---
    print(f"\n{YELLOW}[*] Web UI{NC}")
    print(f"{YELLOW}The default web UI login (pwnagotchi/pwnagotchi) is public knowledge -- "
          f"worth changing if this device will ever be reachable from a network you don't fully trust.{NC}")
    web_auth = _ask_yesno("Require a login for the web UI", _get(effective, 'ui.web.auth'))
    set_value('ui.web.auth', web_auth)
    if web_auth:
        set_value('ui.web.username', _ask_str("Web UI username", _get(effective, 'ui.web.username')))
        set_value('ui.web.password', _ask_password("Web UI password", _get(effective, 'ui.web.password')))

    # --- Confirm and save ---
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

    with open(args.user_config, 'w') as fp:
        fp.write(tomlkit.dumps(doc))

    print(f"\n{GREEN}[+] Saved! Restart pwnagotchi for the new settings to take effect:{NC}")
    print(f"    sudo systemctl restart pwnagotchi")
    return 0
