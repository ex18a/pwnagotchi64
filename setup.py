#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from setuptools import setup, find_packages
from setuptools.command.install import install
import glob
import logging
import os
import re
import shutil
import warnings

log = logging.getLogger(__name__)

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

    # opt-in only: pwnagotchi-soaktest deliberately reboots a healthy device
    # every hour, which is only ever wanted for overnight soak-testing on a
    # specific device -- never as default behavior for every user. Enabled
    # only if /root/.soaktest exists, disabled (not just left alone)
    # otherwise so removing that flag file actually turns it back off.
    if os.path.exists('/root/.soaktest'):
        os.system("systemctl enable --now pwnagotchi-soaktest.timer")
    else:
        os.system("systemctl disable --now pwnagotchi-soaktest.timer")

class CustomInstall(install):
    def run(self):
        super().run()
        if os.geteuid() != 0:
            warnings.warn(
                "Not running as root, can't install pwnagotchi system files!"
            )
            return
        install_system_files()
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
