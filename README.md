# Pwnagotchi 64-Bit AI Edition

## What is Pwnagotchi?

Pwnagotchi is a WiFi-auditing tool that carries a face and a personality, running on a small piece
of hardware (usually a Raspberry Pi) you take with you. The actual attack work — deauthing,
associating, capturing handshakes — is all done by [**bettercap**](https://www.bettercap.org/); a
lot of people assume the "AI" is what's hacking the WiFi, but it isn't. What the AI does is learn
how to *run* bettercap well: how long to linger on a channel before hopping, how aggressively to
hop between channels, how long to wait for a handshake before giving up on a target, how weak a
signal is even worth bothering with, and a dozen other timing/behavior knobs. Every epoch, it sees
what those settings produced — handshakes captured, time spent blind, targets missed — and that
becomes a reward signal nudging its *next* set of settings. Over time it learns which behavior
actually works in whatever environment it's really operating in, instead of running forever on one
fixed configuration that might be great sitting still on a desk and useless out on a walk.

Credit for the original concept and the reinforcement-learning core goes to
[**evilsocket**](https://github.com/evilsocket), who created Pwnagotchi — see Acknowledgments below.

## About This Fork

This build keeps that same reinforcement-learning core but rebuilds the platform underneath it:

* **64-bit, PyTorch/stable-baselines3** instead of the original's older 32-bit, TensorFlow-based
  A2C implementation — faster epoch processing and better training stability.
* **Kali Linux base** instead of the legacy 32-bit image, for native Nexmon firmware support —
  reliable monitor mode and packet injection without extra driver work.
* **Epoch/personality logic reworked for walking-speed use** rather than sitting stationary on a
  desk (see [Fork-Only AI Behavior](#fork-only-ai-behavior) below for the specifics).

> **Hardware Support:** specifically optimized for the **Raspberry Pi Zero 2 W** with **waveshare
> eink 2.13 v4** and **pisugar 3**.
>
> The **Raspberry Pi 3B+** is also supported.
>
> *Note: while this 64-bit image may run on other ARM64 devices, these two boards are the only
> platforms I actively test against.*

---

## Fork-Only AI Behavior

Two behaviors specific to this fork, both about *when the AI is allowed to train*, not just how it
runs bettercap:

### Pauses training at home

If you tell it about your home network(s) (`main.home_networks` in `config.toml`), the AI drops to
plain AUTO mode and stops training the moment one of them is visible, resuming once you leave.

**Why this matters:** home is a fixed, recurring environment — if a disproportionate share of all
training data comes from sitting in the one place you spend the most time, the model can't tell
"genuinely common" apart from "I've just been sitting here a lot." A concrete example: if your home
APs happen to sit on channels 3/7/9, an AI that trains on home a lot could learn to favor those
channels as if they were broadly common, when that's really just local sampling bias from one
location dominating the training data. Excluding home time from training entirely removes that bias
at the source, rather than trying to correct for it after the fact.

### Pauses training when bored

If nothing's happening — a genuinely dead area, or every visible AP already exhausted and given up
on — the AI finishes whatever training batch is already in progress, then drops to AUTO instead of
continuing to grind through the dead stretch. It only resumes once real activity has come back *and*
stayed for a few epochs *and* the surrounding APs have genuinely changed since it went idle — not
just the first random blip AUTO's own background scanning happens to see.

**Why this matters:** by the time it's gone bored, that stretch's outcome is already locked in —
nothing available right now can add more interactions to an already-exhausted target or conjure a
new AP out of nowhere. Continuing to train through the idle stretch doesn't teach it anything new;
it just adds negative-reward noise on top of signal that's already been collected, and Pwnagotchi's
boredom penalty gets *worse* the longer the dead stretch continues — so letting it keep training
through that window actively drags the learned policy in the wrong direction instead of just wasting
time.

---

## Purpose-Built Plugins

* **Portrait Mode:** A custom UI plugin that rotates the display for a fresh, vertical aesthetic.
* **HashVault:** An automated utility that monitors for captured handshakes, automatically validates
  them, and converts them into ready-to-crack hashcat files, eliminating the need for manual cleanup.

---

## Configuration / Usage
ssh login is **user:** `pwn` , **password:** `raspberry`

default ip for gadgetmode is `10.42.0.2`

User configuration file is at `/etc/pwnagotchi/config.toml`.

Do not edit `/etc/pwnagotchi/default.toml` — it is overwritten on every restart.

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
<!-- test commit 4: verifying on-screen blocked-update display, take 2 -->
