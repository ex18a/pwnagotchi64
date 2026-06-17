# Pwnagotchi 64-Bit AI Edition

This is a high-performance, 64-bit-native fork of Pwnagotchi. Built from the ground up on Kali Linux, it replaces legacy AI implementations with a modern **PyTorch** engine, resulting in a much smarter, more stable experience.

Whether you’re running a Pi Zero 2 W or a Pi 3B+, this build is engineered to keep your Pwnagotchi fast, reliable right out of the box.

This is a specialized, high-performance fork of the Pwnagotchi project. This build is designed for 64-bit architecture, utilizing **PyTorch** for AI inference and training, providing a significant boost in intelligence and processing stability over the original A2C implementation.

> **Hardware Support:** specifically optimized for the **Raspberry Pi Zero 2 W**. The **Raspberry Pi 3B+** is also supported.
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
* Sufficient disk space (at least 6GB+ for the build process).

**Instructions:**
1. Clone the repository.
2. Run:
```bash
make
```

The build process will automatically:
* Package your local source code.
* Launch an isolated Debian container.
* Download the official Kali base image and apply all security patches, Bluetooth drivers, and custom UI plugins.
* Output the final, ready-to-flash image to the `pwnagotchi64/dist/` folder called pwnagotchi-0.0.0.0-64bit-kali.img

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

* If I have inadvertently used your code, script, or concept without proper attribution, thank you for your indirect help! Please open an issue so I can ensure you are properly credited here.*

This project is open-source and inherits the original **GPL-3.0 License**.
