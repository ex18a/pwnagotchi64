#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from setuptools import setup, find_packages
from setuptools.command.install import install
import glob
import hashlib
import logging
import os
import re
import shutil
import urllib.request
import warnings

log = logging.getLogger(__name__)

# Kali's apt-packaged bettercap has real, unpatched, still-open upstream
# concurrency bugs (bettercap/bettercap#803 and a related, previously
# unreported one): several Station fields (WPS, and separately
# Encryption/Cipher/Authentication) are written from the packet-processing
# goroutine with zero synchronization while being read concurrently by
# AccessPoint.MarshalJSON() every time the REST API streams an event --
# confirmed on-device to panic and crash the whole bettercap process under
# real deauth-heavy traffic, twice, on two different fields. Fixed in
# ex18a/bettercap (see branch pwnagotchi-wps-fix for the root-cause
# writeup); this installs that patched arm64 build in place of whatever
# apt-requirements.txt pulled in, rather than trying to get the fix
# upstream into Kali's package first.
BETTERCAP_PATCH_VERSION = "v2.41.5-pwnagotchi2"
BETTERCAP_PATCH_URL = (
    "https://github.com/ex18a/bettercap/releases/download/"
    f"{BETTERCAP_PATCH_VERSION}/bettercap-arm64-pwnagotchi2"
)
BETTERCAP_PATCH_SHA256 = "ac208c2c31b49407f210f7fe791bb418339bde27f70daac2b03a587f83799099"

def install_file(source_filename, dest_filename):
    # do not overwrite network configuration if it exists already
    # https://github.com/evilsocket/pwnagotchi/issues/483
    if dest_filename.startswith('/etc/network/interfaces.d/') and os.path.exists(dest_filename):
        log.info(f"{dest_filename} exists, skipping ...")
        return

    log.info(f"installing {source_filename} to {dest_filename} ...")
    dest_folder = os.path.dirname(dest_filename)
    if not os.path.isdir(dest_folder):
        os.makedirs(dest_folder)

    shutil.copyfile(source_filename, dest_filename)
    if dest_filename.startswith("/usr/bin/"):
        os.chmod(dest_filename, 0o755)

def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def install_patched_bettercap():
    bettercap_path = "/usr/bin/bettercap"

    # Compare the *live binary's own hash* rather than trusting a separate
    # version-marker file -- self-healing if anything else (an apt upgrade,
    # a manual reinstall) ever silently reverts /usr/bin/bettercap back to
    # stock, and naturally a no-op on every unrelated dev-branch commit
    # once the patch is already in place, without needing to re-download
    # ~75MB on every single auto-update.
    if os.path.exists(bettercap_path):
        try:
            if _sha256_of(bettercap_path) == BETTERCAP_PATCH_SHA256:
                return
        except Exception as e:
            log.warning(f"could not hash existing bettercap binary, reinstalling to be safe: {e}")

    log.info(f"installing patched bettercap {BETTERCAP_PATCH_VERSION} (fixes bettercap/bettercap#803) ...")
    tmp_path = "/tmp/bettercap-pwnagotchi-patch"
    try:
        urllib.request.urlretrieve(BETTERCAP_PATCH_URL, tmp_path)

        digest = _sha256_of(tmp_path)
        if digest != BETTERCAP_PATCH_SHA256:
            log.error(f"patched bettercap checksum mismatch (expected {BETTERCAP_PATCH_SHA256}, got {digest}) -- "
                       "keeping existing binary, not installing")
            return

        # keep exactly one backup of whatever was there before our first
        # patch install (almost always the apt-packaged stock binary) --
        # if this already exists, a prior run already made it, so don't
        # clobber it with what might by now be our own patched binary
        stock_backup = bettercap_path + ".stock-backup"
        if os.path.exists(bettercap_path) and not os.path.exists(stock_backup):
            shutil.copy2(bettercap_path, stock_backup)

        shutil.move(tmp_path, bettercap_path)
        os.chmod(bettercap_path, 0o755)

        # the go-built binary's default caplet search path
        # (/usr/local/share/bettercap/caplets/) differs from where the apt
        # package and this repo's own builder/assets/bettercap/*.cap get
        # installed (/usr/share/bettercap/caplets/) -- confirmed on-device
        # this binary otherwise fails to start with "caplet
        # pwnagotchi-auto.cap not found". Duplicate the caplets already on
        # disk into the second location rather than changing where they're
        # installed from, so nothing else needs to change.
        caplets_src = "/usr/share/bettercap/caplets"
        caplets_dst = "/usr/local/share/bettercap/caplets"
        if os.path.isdir(caplets_src):
            os.makedirs(caplets_dst, exist_ok=True)
            for fname in ("pwnagotchi-auto.cap", "pwnagotchi-manual.cap"):
                src = os.path.join(caplets_src, fname)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(caplets_dst, fname))

        log.info(f"patched bettercap {BETTERCAP_PATCH_VERSION} installed.")
    except Exception as e:
        log.error(f"failed to install patched bettercap: {e} -- keeping existing binary")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def install_system_files():
    setup_path = os.path.dirname(__file__)
    data_path = os.path.join(setup_path, "builder/data")

    for source_filename in glob.glob("%s/**" % data_path, recursive=True):
        if os.path.isfile(source_filename):
            dest_filename = source_filename.replace(data_path, '')
            install_file(source_filename, dest_filename)

def restart_services():
    # Check if we are running inside a Docker container or chroot environment
    # where systemd is not actively running as the init system.
    if os.path.exists('/.dockerenv') or not os.path.isdir('/run/systemd/system'):
        log.info("Running in a chroot/Docker build environment. Skipping systemctl commands.")
        return

    # Only reload systemd units if the OS is actually booted with systemd
    log.info("Reloading systemd daemon...")
    os.system("systemctl daemon-reload")
    os.system("systemctl enable fstrim.timer")
    # --now: an existing device picking this up via an in-place update should
    # start getting covered right away, not just on its next reboot
    os.system("systemctl enable --now pwnagotchi-syswatchdog.timer")

    # krnbt=on (boot/config.txt) makes the kernel attach the BT UART chip
    # directly at boot; hciuart.service (userspace btuart/hciattach) does the
    # same job the traditional way and ships enabled by default on the base
    # image. Left enabled alongside krnbt, both fight over the same UART
    # connection to the combo WiFi+BT chip -- suspected contributor to
    # nexmon/mon0 instability whenever bluetooth is actually in use.
    # Fresh images no longer enable it (see builder/pwnagotchi.sh); this
    # covers already-provisioned devices picking it up via an in-place update.
    os.system("systemctl disable --now hciuart.service 2>/dev/null")

    # opt-in only: pwnagotchi-soaktest deliberately reboots a healthy device
    # every hour, which is only ever wanted for overnight soak-testing on a
    # specific device -- never as default behavior for every user. Enabled
    # only if /root/.soaktest exists, disabled (not just left alone)
    # otherwise so removing that flag file actually turns it back off.
    if os.path.exists('/root/.soaktest'):
        os.system("systemctl enable --now pwnagotchi-soaktest.timer")
    else:
        os.system("systemctl disable --now pwnagotchi-soaktest.timer")

def remove_stale_eth0_interfaces_file():
    # base Kali image leftover, not ours -- duplicates our own eth0-cfg
    # (kept for Pi 3B+ support) but declares "auto eth0", which fails and
    # takes the whole networking.service down with it on any board without
    # a physical ethernet port (e.g. Pi Zero 2 W). Fresh images no longer
    # ship this (see builder/pwnagotchi.sh), but already-provisioned
    # devices picking this up via an in-place update still have it.
    path = '/etc/network/interfaces.d/eth0'
    if os.path.exists(path):
        os.remove(path)
        log.info(f"removed stale {path} (base image leftover, duplicates eth0-cfg)")


class CustomInstall(install):
    def run(self):
        super().run()
        if os.geteuid() != 0:
            warnings.warn(
                "Not running as root, can't install pwnagotchi system files!"
            )
            return
        install_system_files()
        # deliberately not gated behind restart_services()'s chroot/Docker
        # guard -- downloading and swapping a binary needs no running
        # systemd, so this must also apply during a fresh image build
        # (builder/pwnagotchi.sh runs this same `pip install` inside a
        # qemu-aarch64-static chroot, no systemd PID 1 present there)
        install_patched_bettercap()
        remove_stale_eth0_interfaces_file()
        restart_services()

def version(version_file):
    if "PWN_VERSION" in os.environ:
       return os.environ["PWN_VERSION"]
    else:
       with open(version_file, 'rt') as vf:
          version_file_content = vf.read()

       version_match = re.search(r"__version__\s*=\s*[\"\']([^\"\']+)", version_file_content)

       if version_match:
          return version_match.groups()[0]

    return None

with open('requirements.txt') as fp:
    required = [
        line.strip()
        for line in fp
        if line.strip() and not line.startswith("--")
    ]

VERSION_FILE = 'pwnagotchi/_version.py'
pwnagotchi_version = version(VERSION_FILE)

setup(name='pwnagotchi64',
      version=pwnagotchi_version,
      description='(⌐■_■) - Deep Reinforcement Learning instrumenting bettercap for WiFI pwning (64-bit Port).',
      author='evilsocket && the dev team',
      author_email='evilsocket@gmail.com',
      maintainer='ex18a',
      maintainer_email='your.email@example.com',
      url='https://github.com/yourusername/pwnagotchi64',
      license='GPL-3.0-or-later',
      install_requires=required,
      cmdclass={
          "install": CustomInstall,
      },
      scripts=['bin/pwnagotchi'],
      package_data={'pwnagotchi': ['defaults.yml', 'pwnagotchi/defaults.yml', 'locale/*/LC_MESSAGES/*.mo']},
      include_package_data=True,
      packages=find_packages(),
      classifiers=[
          'Programming Language :: Python :: 3',
          'Development Status :: 5 - Production/Stable',
          'Environment :: Console',
      ])
