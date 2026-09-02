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
import subprocess
import urllib.request
import warnings

log = logging.getLogger(__name__)

BETTERCAP_PATCH_VERSION = "v2.41.5-pwnagotchi6"
BETTERCAP_PATCH_URL = (
    "https://github.com/ex18a/bettercap/releases/download/"
    f"{BETTERCAP_PATCH_VERSION}/bettercap-arm64-pwnagotchi6"
)
BETTERCAP_PATCH_SHA256 = "5d9fb9e8da88a89c7d962be99595ce401a86f81229e751eda06304a75ef922bd"

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
    # systemd requires files under system-shutdown/ to be executable to be
    # picked up at all (systemd-shutdown(8)) -- silently ignored otherwise,
    # no error, so this is easy to miss
    if dest_filename.startswith("/usr/bin/") or dest_filename.startswith("/lib/systemd/system-shutdown/"):
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

    log.info(f"installing patched bettercap {BETTERCAP_PATCH_VERSION} "
             f"(fixes bettercap/bettercap#803, plus a hopChanges deadlock and a full upstream sync) ...")
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
    if os.path.exists('/.dockerenv') or not os.path.isdir('/run/systemd/system'):
        log.info("Running in a chroot/Docker build environment. Skipping systemctl commands.")
        return

    log.info("Reloading systemd daemon...")
    os.system("systemctl daemon-reload")
    os.system("udevadm control --reload-rules && udevadm trigger")
    os.system("systemctl enable fstrim.timer")
    os.system("systemctl enable --now pwnagotchi-syswatchdog.timer")

    os.system("systemctl disable --now hciuart.service 2>/dev/null")
    os.system("systemctl disable --now bluetooth.service bt-agent.service 2>/dev/null")
    if os.path.exists('/usr/local/bin/bt-wizard'):
        os.remove('/usr/local/bin/bt-wizard')

    if os.path.exists('/root/.soaktest'):
        os.system("systemctl enable --now pwnagotchi-soaktest.timer")
    else:
        os.system("systemctl disable --now pwnagotchi-soaktest.timer")

    if os.path.exists('/root/.battery-curve-test'):
        os.system("systemctl enable --now pwnagotchi-battery-curve-log.timer")
    else:
        os.system("systemctl disable --now pwnagotchi-battery-curve-log.timer")

    with open('/etc/systemd/system.conf') as f:
        system_conf = f.read()
    new_system_conf = system_conf \
        .replace('#RuntimeWatchdogSec=off', 'RuntimeWatchdogSec=60s') \
        .replace('#RebootWatchdogSec=10min', 'RebootWatchdogSec=60s')
    if new_system_conf != system_conf:
        with open('/etc/systemd/system.conf', 'w') as f:
            f.write(new_system_conf)
        os.system("systemctl daemon-reexec")

def regenerate_motd():
    setup_path = os.path.dirname(__file__)
    src = os.path.join(setup_path, 'builder', 'assets', 'system', 'motd-gen.sh')
    if not os.path.exists(src):
        return
    try:
        with open('/etc/hostname') as f:
            hostname = f.read().strip()
    except OSError:
        hostname = os.uname().nodename
    subprocess.run(['bash', src, hostname])

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

# Guarded so this file can be imported (e.g. by automatic-updates.py, to
# call install_patched_bettercap() directly -- see that plugin's comment
# on why it can't just rely on `pip install .` triggering CustomInstall)
# without actually re-running the whole setuptools command dispatch.
# PEP 517 build backends (setuptools.build_meta) still set __name__ ==
# "__main__" when executing this file for a real build, so this doesn't
# change anything about how `pip install .` itself behaves.
if __name__ == "__main__":
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
