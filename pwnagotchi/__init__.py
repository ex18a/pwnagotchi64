import os
import logging
import subprocess
import time
import re



from pwnagotchi._version import __version__

_name = None
config = None

# written by the automatic-updates plugin whenever it installs a dev-branch
# commit (only relevant when /root/dev exists -- see that plugin)
_DEV_FLAG_PATH = '/root/dev'
_DEV_SHA_FILE = '/root/.automatic-updates-sha'

# Shared brcm-wedge reboot budget, used by every Python-side reboot decision
# that can be triggered by a persistent brcmfmac/SDIO wedge (watchdog.py's
# lockdown reboot, agent.py's monitor-interface-start-failure reboot,
# automata.py's blind-epochs reboot) plus pwnlib's own bash copy for the
# syswatchdog service -- all sharing this one state file so a mixed sequence
# of triggers across languages and call sites counts against a single cap.
# Originally only watchdog.py had this check; agent.py's and automata.py's
# reboot calls were found to bypass it entirely (discovered live: a
# persistent brcmfmac wedge under sustained deauth load caused agent.py's
# "monitor interface failed to start 5 times" path to reboot immediately
# with no rate limit at all, only seconds after watchdog.py's OWN check had
# just correctly denied a reboot for exhausting the very same budget).
# Consolidated here as the single implementation so it can't drift out of
# sync between call sites again -- this already happened once (pwnlib's bash
# copy had a permanent-lockout bug, fixed, then watchdog.py's Python copy
# turned out to have the identical bug, also fixed) before this widened to
# "two more call sites don't call it at all."
BRCM_REBOOT_STATE_FILE = '/root/.pwnagotchi-brcm-reboot-state'
BRCM_REBOOT_WINDOW_SECS = 1800
BRCM_REBOOT_MAX_IN_WINDOW = 3


def should_reboot_for_brcm_wedge():
    now = int(time.time())
    count = 0
    last = 0
    try:
        with open(BRCM_REBOOT_STATE_FILE) as f:
            count_str, last_str = f.read().split()
            count = int(count_str)
            last = int(last_str)
    except (FileNotFoundError, ValueError):
        pass

    if now - last > BRCM_REBOOT_WINDOW_SECS:
        count = 0

    # Only write state on an ALLOWED call, never a denied one -- writing on
    # every call (including denied ones) means a persistently failing wedge
    # keeps sliding "last" forward forever, so the window never naturally
    # elapses and the budget locks out permanently after the first burst
    # (observed in production from the bash copy of this same bug: count
    # reached 75 instead of capping at 3).
    if count >= BRCM_REBOOT_MAX_IN_WINDOW:
        return False

    count += 1
    try:
        with open(BRCM_REBOOT_STATE_FILE, 'w') as f:
            f.write("%d %d" % (count, now))
    except OSError:
        pass

    return True


def display_version():
    # short commit sha while tracking the dev branch, else the release version
    if os.path.exists(_DEV_FLAG_PATH) and os.path.exists(_DEV_SHA_FILE):
        try:
            with open(_DEV_SHA_FILE) as fp:
                sha = fp.read().strip()
            if sha:
                return sha[:7]
        except Exception:
            pass
    return __version__


def set_name(new_name):
    if new_name is None:
        return

    new_name = new_name.strip()
    if new_name == '':
        return

    if not re.match(r'^[a-zA-Z0-9\-]{2,25}$', new_name):
        logging.warning("name '%s' is invalid: min length is 2, max length 25, only a-zA-Z0-9- allowed", new_name)
        return

    current = name()
    if new_name != current:
        global _name

        logging.info("setting unit hostname '%s' -> '%s'", current, new_name)
        with open('/etc/hostname', 'wt') as fp:
            fp.write(new_name)

        with open('/etc/hosts', 'rt') as fp:
            prev = fp.read()
            logging.debug("old hosts:\n%s\n", prev)

        with open('/etc/hosts', 'wt') as fp:
            patched = prev.replace(current, new_name, -1)
            logging.debug("new hosts:\n%s\n", patched)
            fp.write(patched)

        os.system("hostname '%s'" % new_name)
        pwnagotchi.reboot()


def name():
    global _name
    if _name is None:
        with open('/etc/hostname', 'rt') as fp:
            _name = fp.read().strip()
    return _name


def uptime():
    with open('/proc/uptime') as fp:
        return int(fp.read().split('.')[0])


def mem_usage():
    with open('/proc/meminfo') as fp:
        for line in fp:
            line = line.strip()
            if line.startswith("MemTotal:"):
                kb_mem_total = int(line.split()[1])
            if line.startswith("MemFree:"):
                kb_mem_free = int(line.split()[1])
            if line.startswith("Buffers:"):
                kb_main_buffers = int(line.split()[1])
            if line.startswith("Cached:"):
                kb_main_cached = int(line.split()[1])
        kb_mem_used = kb_mem_total - kb_mem_free - kb_main_cached - kb_main_buffers
        return round(kb_mem_used / kb_mem_total, 1)

    return 0


def _cpu_stat():
    """
    Returns the splitted first line of the /proc/stat file
    """
    with open('/proc/stat', 'rt') as fp:
        return list(map(int,fp.readline().split()[1:]))


def cpu_load():
    """
    Returns the current cpuload
    """
    parts0 = _cpu_stat()
    time.sleep(0.1)
    parts1 = _cpu_stat()
    parts_diff = [p1 - p0 for (p0, p1) in zip(parts0, parts1)]
    user, nice, sys, idle, iowait, irq, softirq, steal, _guest, _guest_nice = parts_diff
    idle_sum = idle + iowait
    non_idle_sum = user + nice + sys + irq + softirq + steal
    total = idle_sum + non_idle_sum
    return non_idle_sum / total


def temperature(celsius=True):
    with open('/sys/class/thermal/thermal_zone0/temp', 'rt') as fp:
        temp = int(fp.read().strip())
    c = int(temp / 1000)
    return c if celsius else ((c * (9 / 5)) + 32)


def shutdown():
    logging.warning("shutting down ...")

    from pwnagotchi.ui import view
    if view.ROOT:
        view.ROOT.on_shutdown()
        # give it some time to refresh the ui
        time.sleep(10)

    logging.warning("syncing...")

    from pwnagotchi import fs
    for m in fs.mounts:
        m.sync()
 
    os.system("sync")
    os.system("halt")


def restart(mode, restart_bettercap=True):
    logging.warning("restarting in %s mode ...", mode)

    if mode == 'AUTO':
        os.system("touch /root/.pwnagotchi-auto")
    else:
        os.system("touch /root/.pwnagotchi-manual")

    if restart_bettercap:
        try:
            subprocess.run(["service", "bettercap", "restart"], timeout=30)
        except subprocess.TimeoutExpired:
            logging.error("service bettercap restart timed out after 30s")

        time.sleep(2)

    try:
        subprocess.run(["service", "pwnagotchi", "restart"], timeout=30)
    except subprocess.TimeoutExpired:
        logging.error("service pwnagotchi restart timed out after 30s")


def reboot(mode=None):
    if mode is not None:
        mode = mode.upper()
        logging.warning("rebooting in %s mode ...", mode)
    else:
        logging.warning("rebooting ...")

    from pwnagotchi.ui import view
    if view.ROOT:
        view.ROOT.on_rebooting()
        # give it some time to refresh the ui
        time.sleep(10)

    if mode == 'AUTO':
        os.system("touch /root/.pwnagotchi-auto")
    elif mode == 'MANU':
        os.system("touch /root/.pwnagotchi-manual")

    logging.warning("syncing...")

    from pwnagotchi import fs
    for m in fs.mounts:
        m.sync()

    os.system("sync")
    os.system("shutdown -r now")
