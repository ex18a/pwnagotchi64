# Pwnagotchi 64-Bit AI Edition

This is a specialized, high-performance fork of the Pwnagotchi project. This build is designed for 64-bit architecture, utilizing **PyTorch** for AI inference and training, providing a significant boost in intelligence and processing stability over the original A2C implementation.

## Why does Pwnagotchi even have an "AI"?

A lot of people assume the AI is what actually hacks the WiFi — it isn't. The real attack work (deauthing, associating, capturing handshakes) is all done by **bettercap**. What the AI does is learn how to *run* bettercap well: how long to linger on a channel before hopping, how aggressively to hop between channels, how long to wait for a handshake before giving up on a target, how far away (signal-wise) is even worth bothering with, and a dozen other timing/behavior knobs. Every epoch, it sees what those settings produced — handshakes captured, time spent blind, targets missed — and that becomes a reward signal nudging its *next* set of settings. Over time it learns which behavior actually works in whatever environment it's really operating in, instead of running forever on one fixed configuration that might be great sitting still on a desk and useless out on a walk. That's the whole original idea behind the project (credit to evilsocket, see Acknowledgments below) — this fork keeps that same reinforcement-learning core, just rebuilt on a modern PyTorch/stable-baselines3 engine instead of the original's older TensorFlow-based one, and with the epoch/personality logic reworked specifically for walking-speed use rather than sitting stationary.

> **Hardware Support:** specifically optimized for the **Raspberry Pi Zero 2 W** with **waveshare eink 2.13 v4** and **pisugar 3**.
>
>  The **Raspberry Pi 3B+** is also supported.
>
> *Note: While this 64-bit image may run on other ARM64 devices, these two boards are the only platforms I actively test against.*

---

## What makes this build different?

This fork maintains the classic Pwnagotchi AI personality while completely overhauling the underlying architecture. By migrating to a 64-bit Kali Linux base, I have removed the legacy 32-bit bottlenecks that previously limited processing stability.

### Key Features
* **Modern AI Engine:** I have ported the AI inference to PyTorch. The core learning logic remains faithful to the original, but running it on a modern PyTorch framework allows for significantly faster epoch processing and improved stability, ensuring the Pwnagotchi learns smarter without the lag.
* **Kali Linux Backbone:** This build is standardized on Kali Linux to ensure native support for Nexmon firmware. This provides rock-solid monitor mode and reliable packet injection, ensuring deauth frames land accurately.
* **Bluetooth Tethering Wizard:** I developed an automated setup wizard that solves the most frustrating part of the Pwnagotchi experience. It handles kernel-level networking, IP routing, and pairing configuration automatically, making reliable Bluetooth tethering possible in just a few simple steps.

## Purpose-Built Plugins:

* **Portrait Mode:** A custom UI plugin that rotates the display for a fresh, vertical aesthetic.

* **HashVault:** An automated utility that monitors for captured handshakes, automatically validates them, and converts them into ready-to-crack hashcat files, eliminating the need for manual cleanup.

---

## Configuration / Usage
ssh login is **user:** `pwn` , **password:** `raspberry`

default ip for gadgetmode is `10.42.0.2`

User configuration file is at `/etc/pwnagotchi/config.toml`.

Do not edit `/etc/pwnagotchi/default.toml` — it is overwritten on every restart.

For bluetooth setup use: `sudo bt-wizard`

---

## Building from Source
This project uses Docker to create a clean, reproducible build environment. This ensures your system stays clean and the build succeeds regardless of your local Linux distribution.

**Requirements:**
* Docker installed and configured.
* Sufficient disk space (at least 16GB+ for the build process).

**Instructions:**
1. Clone the repository.
2. Run:
```bash
make
```

The build process will automatically:
* Package the local source code.
* Launch an isolated Debian container.
* Download the official Kali base image and apply all security patches, Bluetooth drivers, and custom UI plugins.
* Output the final, ready-to-flash image to the `pwnagotchi64/dist/` folder called pwnagotchi64-0.0.0.0.img

---

## Flashing SD Card
The easiest way is to use Raspberry PI Imager.
dont use any pre-setup features like wifi, you will break it.

---

## Acknowledgments & Credits

This 64-bit build would not be possible without the foundational work and continuous community efforts of the following developers. My fork builds directly upon their heavy lifting:

* **[evilsocket](https://github.com/evilsocket)** - The original creator and architect of the Pwnagotchi project.
* **[aluminum-ice](https://github.com/aluminum-ice)** - For crucial contributions to the core codebase.
* **[jayofelony](https://github.com/jayofelony)** - For crucial contributions to the core codebase.

*If I have inadvertently used your code, script, or concept without proper attribution, thank you for your indirect help! Please open an issue so I can ensure you are properly credited here.*

This project is open-source and inherits the original **GPL-3.0 License**.

<!-- test commit: confirming end-to-end auto-update pipeline, 2026-07-16 -->
<!-- test commit 2: verifying blocklist actually blocks, 2026-07-16 -->
<!-- test commit 3: verifying on-screen blocked-update display, 2026-07-16 -->
