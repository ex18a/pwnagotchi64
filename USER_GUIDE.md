# Pwnagotchi 64-Bit AI Edition — User Guide

An in-depth guide to how this fork works, what's different from the original
[evilsocket/pwnagotchi](https://github.com/evilsocket/pwnagotchi), and how to actually use it.
For a quick overview and build instructions, see [`README.md`](README.md).

## Contents

- [Architecture](#architecture)
- [How Pwnagotchi Works](#how-pwnagotchi-works)
- [What This Fork Changes](#what-this-fork-changes)
- [First Boot & Setup](#first-boot--setup)
- [Day-to-Day Use](#day-to-day-use)
- [Personality Parameters](#personality-parameters)
- [Configuration Reference](#configuration-reference)
- [External WiFi Adapters](#external-wifi-adapters)
- [Auto-Updates](#auto-updates)
- [System-Level Recovery](#system-level-recovery)
- [Troubleshooting](#troubleshooting)

---

## Architecture

Four separate processes cooperate on the device:

- **`bettercap`** (Go) — does the actual WiFi work: channel hopping, association, deauth, handshake
  capture, all driven through its own REST/websocket API on `localhost:8081`. Runs as its own systemd
  service, independent of pwnagotchi.
- **`pwnagotchi`** (Python) — the agent. Drives bettercap through that API, runs the epoch loop, hosts
  the reinforcement-learning model, and owns the display/web UI. Depends on bettercap already being up
  to do anything useful, but tolerates it not being ready yet (retries the connection rather than
  crashing).
- **`pwngrid-peer`** — handles the mesh side: each unit has an RSA keypair-based identity
  (`/etc/pwnagotchi/id_rsa`), and this process advertises/discovers other units and exchanges
  encounters (bonding, `opwngrid` reporting) independently of the main recon loop.
- **`pwnagotchi-syswatchdog`** — a bash script run every 3 minutes by a systemd timer, entirely outside
  the Python process, watching for failures nothing inside Python could ever notice or recover from
  (see [System-Level Recovery](#system-level-recovery)).

Configuration is two files merged at runtime: `pwnagotchi/defaults.toml` (shipped with the image,
overwritten on every update — never edit it directly) provides every default value, and
`/etc/pwnagotchi/config.toml` (created by `sudo pwnagotchi --setup`, yours to edit) overrides only the
keys you actually set. Anything you don't set in `config.toml` just falls through to the default.

---

## How Pwnagotchi Works

Pwnagotchi doesn't attack WiFi itself — bettercap does, via its `wifi.recon` module. Pwnagotchi is a
supervisor that decides *how* to run bettercap, and learns to do that better over time.

**The epoch loop** (one cycle, repeated forever): run recon, react to whatever bettercap found
(associate to APs, deauth clients to provoke a handshake), hold on a channel for a bit, then close out
the epoch and check in with the AI. The AI sees what that epoch produced — handshakes captured, time
spent blind, targets missed — as a reward signal, and adjusts its next set of personality parameters
(see [below](#personality-parameters)) accordingly. Over enough epochs it learns which behavior
actually works in the environment it's really in, rather than running forever on one fixed
configuration that might suit a desk and nothing else.

**Moods** are a separate, simple state machine (`automata.py`) that turns epoch outcomes into
faces/status text — bored after enough inactive epochs, sad if that continues, angry if it gets worse,
excited after a run of active epochs, lonely/grateful depending on how many other units it's bonded
with. Purely cosmetic — it doesn't feed back into training.

**Modes**: `AUTO` runs recon on a fixed personality, no learning. `AI` actively trains. `MANUAL` is for
interactive, hand-driven use. This fork adds automatic switching between `AI` and `AUTO` on top of
this — see below.

The on-screen mode indicator adds one more distinction on top of these: while in `AI` mode, it shows
`TRAIN` specifically during an active training batch, dropping back to a plain `AI` label the rest of
the time (inference only, no batch currently running). It's a display-only distinction, not a separate
underlying mode.

---

## What This Fork Changes

Everything in this section is specific to this fork — none of it exists in upstream
`evilsocket/pwnagotchi`.

### Platform

- **64-bit, PyTorch/stable-baselines3** instead of the original 32-bit TensorFlow/A2C stack — faster
  epoch processing, better training stability.
- **Kali Linux base** instead of the legacy 32-bit image, giving native Nexmon firmware support for the
  Raspberry Pi's built-in chip (reliable monitor mode + injection without extra driver work).
- **A patched `bettercap` binary**, installed automatically — fixes several real upstream crash bugs
  found through on-device testing (data races, a channel-hop deadlock), not stock bettercap.
- Actively tested against the **Raspberry Pi Zero 2 W** with a waveshare eink 2.13 v4 display and
  **PiSugar 3** battery. May run on other ARM64 boards but isn't tested against them. Also supports
  I2C SSD1306 OLED displays (`i2coled`) as an alternative to the Waveshare drivers.

### AI-auto-toggle (training only when it matters)

Two behaviors, both about *when* the AI is allowed to train, not how it runs bettercap:

**Pauses at home.** Once `main.home_networks` lists a home network and it's currently visible, drops to
plain `AUTO` and stops training until you leave, resuming automatically once you do.

*Why this matters*: home is a fixed, recurring environment — if a disproportionate share of all
training data comes from sitting in the one place you spend the most time, the model can't tell
"genuinely common" apart from "I've just been sitting here a lot." If your home APs happen to sit on
channels 3/7/9, heavy home-time training could teach the model to favor those channels as if they were
broadly common, when it's really just local sampling bias from one location dominating the data.
Excluding home time from training removes that bias at the source.

**Pauses when bored.** If nothing's happening — a dead area, or every visible AP already exhausted —
the AI finishes whatever training batch is already in progress, then drops to `AUTO` instead of
grinding through the dead stretch. Resumes only once real activity returns *and* stays for a few
epochs *and* the surrounding APs have genuinely changed since it went idle, not just the first random
blip AUTO's own background scanning happens to see.

*Why this matters*: by the time it's gone bored, that stretch's outcome is already locked in — nothing
available right now can add more interactions to an already-exhausted target or conjure a new AP.
Continuing to train through the idle stretch teaches nothing new; it just adds negative-reward noise on
top of already-collected signal, and the boredom penalty gets worse the longer the dead stretch
continues — training through that window actively drags the learned policy in the wrong direction.

Both directions (bored **or** sad) trigger the drop to `AUTO` — `bored_num_epochs` and `sad_num_epochs`
are independent AI-learned thresholds with no fixed ordering between them, so checking only one could
get stuck waiting on a threshold the AI's current policy has made temporarily unreachable.

### Interaction history decay

A target that's hit `max_interactions` isn't ignored forever. If it hasn't been seen again for a while,
its interaction count slowly decays back down, fully resetting once you've been away from it long
enough — so a network you hammered while out doesn't come back still on cooldown once you're home, and
vice versa.

### Brain/model self-healing & backups

`brain.nn` self-heals instead of crashing the whole agent if it ever becomes incompatible (e.g. after an
update changes the model's shape). Backups are tiered — dated snapshots plus rolling and permanent
copies — and a bad reset gets backed up rather than silently deleted, so a corrupted or incompatible
brain doesn't cost you the trained model.

### Automatic external WiFi adapter switching

Plug in a compatible external USB WiFi adapter (one with a monitor-mode + injection-capable driver —
see [External WiFi Adapters](#external-wifi-adapters)) and it's used automatically within a few
seconds, no config needed. Unplug it and it falls back to the built-in chip just as fast. The correct
one is also picked at boot, regardless of whether the adapter was already plugged in when it powered
on.

Mechanically: a udev rule watches for the adapter's network interface appearing or disappearing, and
restarts **both** `bettercap` and `pwnagotchi` together — not bettercap alone, which would leave the
already-running pwnagotchi process out of sync with a bettercap instance that came back with every
module off and every setting reverted to bare defaults. A debounce window and a same-state no-op check
keep a single plug/unplug event from causing more than one restart.

### Rebuilt/new plugins

- **`portrait-mode`** — switches to a portrait display driver and repositions every UI element to
  match, for a vertical layout instead of the original landscape one.
- **`hashvault`** — watches for captured handshakes, validates them, and converts them into
  ready-to-crack hashcat files automatically, eliminating manual cleanup.
- **`channel_control`** — live on/off switch (Web UI → Plugins) for whether the AI may pick 5GHz
  channels, without invalidating a trained `brain.nn` (the model's action space is still sized from
  real hardware capability at startup; this just filters the channel list it's offered).
- **`watchdog`** — two-stage in-process safety net (see [System-Level Recovery](#system-level-recovery)
  for how it differs from `pwnagotchi-syswatchdog`).
- **`automatic-updates`** — self-updates in place; see [Auto-Updates](#auto-updates).
- **`dev-ai-trained`** — shows lifetime completed training epochs read from `brain.json`.
- **`tweak_view`** — mobile-friendly UI layout editor: drag-to-position elements, live preview,
  export/import/reset.
- **`whitelist`** — harvests seen MACs/SSIDs, syncs with HashVault, supports case-sensitive SSIDs.
  Disabled by default.
- **`IPDisplay`** — shows the device's current IP address(es) on screen.
- **`pisugar3i2c`** — direct I2C PiSugar 3 battery plugin with reading smoothing (averages over a
  window rather than letting the percentage jump around) and a configurable low-battery auto-shutdown
  threshold. Disabled by default (enable it if you actually have a PiSugar 3 attached).
- **`memtemp`** — CPU/memory usage and temperature on screen, refreshed on its own throttled interval
  rather than every UI redraw. Enabled by default.
- **`wpa-sec`** — optionally uploads captured handshakes to
  [wpa-sec.stanev.org](https://wpa-sec.stanev.org) automatically. Disabled by default (needs your own
  API key).
- **`gps`** — stock upstream plugin, unmodified: saves GPS coordinates alongside any handshake
  captured, if you have a supported GPS source attached.

### Bluetooth removed entirely

Disabled at the hardware level (`dtoverlay=disable-bt`) and every related service/package — not just
turned off in software. If you need Bluetooth, this isn't the build for it.

### Other changes

- `ui.status-log` (default on) mirrors whatever's currently on the physical screen into
  `pwnagotchi.log` as `[STATUS]` lines, so you can follow along over SSH without a screen attached.
- `main.iface` is no longer a config option — every part of the system already assumed `mon0`
  unconditionally, so it's hardwired now rather than being a setting that looked configurable but
  would actually break things if changed.

---

## First Boot & Setup

1. Flash the built image with Raspberry Pi Imager. **Don't** use its pre-configured WiFi/SSH options —
   just flash the plain image, or it will break.
2. Boot it and connect — default SSH is `pwn` / `raspberry`, and over USB gadget mode the device is at
   `10.42.0.2`.
3. Run the interactive setup wizard to create your config:
   ```
   sudo pwnagotchi --setup
   ```
   This creates `/etc/pwnagotchi/config.toml` with only the keys you actually answered.
4. Reboot to apply.

---

## Day-to-Day Use

**The screen** shows a face, a status line (what it's currently doing, in plain language), the current
channel, uptime, handshake count, and whichever plugin elements are enabled. That status text is also
mirrored into `pwnagotchi.log` (`ui.status-log`), so `tail -f /var/log/pwnagotchi.log` gives you the
same picture over SSH without a display attached.

**The web UI** (`http://<device-ip>:8080` by default) — rebuilt on a dark, terminal-green theme in this
fork — shows the same information plus a Plugins page with inline descriptions; enable/disable any
plugin live without editing config files or restarting, and jump straight into a plugin's own web UI
from there when it has one.

**Modes**: boots in `AUTO` by default. A one-shot manual-mode override (`sudo pwnagotchi --manual`, or
the web UI's restart-in-manual-mode action) drops it into `MANUAL` for that boot only. If
`ai.enabled = true` (the default), it actively trains whenever it isn't paused by one of the
AI-auto-toggle conditions above; set `ai.enabled = false` to keep it in plain `AUTO` permanently.

---

## Personality Parameters

Everything under `[personality]` in `config.toml`/`defaults.toml` is also an AI-tunable parameter —
whatever you set is only the *starting* value if `ai.enabled = true`, since training adjusts these
over time. Setting them yourself is mainly useful for `AUTO`-only use (`ai.enabled = false`), or to
give training a reasonable starting point.

| Key | Meaning |
|---|---|
| `advertise` | Whether this unit broadcasts its identity for mesh discovery/bonding (`pwngrid`). Off by default in this fork. |
| `deauth` | Whether `associate()`/`deauth()` are actually allowed to fire — gates sending deauth frames at qualifying clients. |
| `associate` | Same gate, for sending association frames at qualifying APs. |
| `channels` | Passed straight to bettercap's `wifi.recon.channel`; empty means bettercap's own default hop list, not "all channels" explicitly. |
| `min_rssi` | Passed straight to bettercap's `wifi.rssi.min` — APs weaker than this are ignored. |
| `ap_ttl` / `sta_ttl` | Passed straight to bettercap's own `wifi.ap.ttl`/`wifi.sta.ttl` — **seconds**, not epochs, since bettercap has no concept of an epoch. |
| `recon_time` | Seconds bettercap is left scanning before pwnagotchi reacts to what it found — one wait covering the whole configured channel set for that epoch, not per-channel. |
| `max_inactive_scale` | Epoch-count *threshold* — once `inactive_for` reaches this many consecutive inactive epochs, `recon_time` gets multiplied by `recon_inactive_multiplier`. |
| `recon_inactive_multiplier` | The multiplier itself, applied once `max_inactive_scale` is reached. |
| `hop_recon_time` | How long to hold the current channel after a deauth, waiting for the handshake reply — the longer of the two action-holds, always wins if an associate-hold is also queued. Also reused as the idle-hold when there's nothing to attack that epoch at all. |
| `min_recon_time` | How long to hold the current channel after an associate, waiting for a reply — shorter than `hop_recon_time`, despite the name it isn't a floor on `recon_time`. |
| `max_interactions` | Cap on total deauth/associate attempts against one target before giving up on it. Cumulative across epochs — only cleared by a separate time-based decay, not reset every epoch. |
| `max_misses_for_recon` | Missed-interaction threshold marking the current recon as stale (forces a fresh pass); also scales how angry vs. lonely the reaction is when exceeded. |
| `excited_num_epochs` / `bored_num_epochs` / `sad_num_epochs` | Consecutive active/inactive epoch thresholds for those mood states. |
| `bond_encounters_factor` | Two uses of the same value: the number of encounters with *one* peer needed to count it as a "good friend" (own face), and separately, the divisor applied to the *sum* of every peer's encounters to determine how strong the overall support network is (grateful/lonely/bored-vs-grateful checks). |
| `home_absent_epochs` | Epochs away from a home network before the AI-wake cooldown clears — stops it flip-flopping right after leaving home. |
| `ai_wake_epochs` | Minimum consecutive active epochs before the AI resumes from a bored-triggered pause. |
| `environment_change_threshold` | Fraction of the AP set that was visible when it went bored which must have dropped out of range before the AI will resume (default 0.5 = at least half must be gone). |
| `wifi_hop_period_ms` | Passed straight to bettercap's `wifi.hop.period` — how fast bettercap itself hops channels while scanning. |
| `action_throttle` | Seconds slept after sending an associate/deauth frame, throttling how fast consecutive actions fire. |

---

## Configuration Reference

The full set of defaults lives in `pwnagotchi/defaults.toml` — read it directly for anything not
covered here. A few commonly touched keys, in `config.toml`:

```toml
[main]
name = "your-device-name"
home_networks = ["your-home-ssid"]

[main.plugins.whitelist]
enabled = true

[main.plugins.channel_control]
enable_5ghz = false

[ai]
enabled = false   # stay in AUTO permanently, never train

[personality]
channels = [1, 6, 11]   # restrict recon to specific channels
max_interactions = 999  # effectively unlimited deauth/assoc attempts per target
```

---

## External WiFi Adapters

Any adapter using a driver with monitor mode + packet injection support works — this image already
includes a driver for the common RTL8812AU/8814AU/8821AU chipsets found in most external monitor-mode
adapters, so those work without installing anything.

For a different chipset, install the matching driver yourself. Detection and switching (see above)
work automatically for any adapter once its driver is present and it enters monitor mode correctly —
nothing else needs configuring.

---

## Auto-Updates

The `automatic-updates` plugin checks GitHub Releases on `main` by default, downloading and installing
a new tagged release automatically (`install = true`) at whatever `interval` (hours) you set.

A retroactive safety net (`AUTO_UPDATE_BLOCKLIST` at the repo root) can block a specific bad release
from auto-installing even after the fact, fetched fresh from `main` on every check — this is checked
*before* anything is downloaded, so a blocked release never reaches the device at all.

Check what version is actually running from the on-screen status line at boot, or the corresponding
line in `pwnagotchi.log`.

---

## System-Level Recovery

Two independent safety nets, at different layers:

**`watchdog` plugin** (in-process, Python) — runs every epoch. Gives bettercap up to 60 seconds to
self-recover from a crash via systemd's own restart policy before escalating to a full reboot;
separately tracks blind epochs to detect a missing monitor interface (reboots if it's still gone after
one warning epoch) or a bettercap that's present but unresponsive. Also has a last-resort check for
`wifi.recon` silently not running even when everything else looks healthy — a bettercap crash+restart
starts fresh with every module off, and the crash-recovery check alone only confirms the REST API
responds again, not that scanning actually resumed.

**`pwnagotchi-syswatchdog`** (system-level, bash, systemd timer every 3 minutes) — runs entirely
outside the Python process, so it keeps working even if pwnagotchi itself is completely wedged:

- Detects and recovers from internal WiFi chip firmware flakiness (reloads the driver, no reboot;
  escalates to a full reboot only if the same flakiness returns after that).
- Thermal protection — pauses `bettercap`/`pwnagotchi` at 70°C, resumes at 50°C, hard-reboots as a last
  resort at 85°C.
- Reboots if `bettercap` is crash-looping, or if `pwnagotchi.log` goes stale while the service should
  be active.
- A hardware watchdog (`RuntimeWatchdogSec=60s`) recovers from a genuine full kernel lockup that
  nothing in userspace could otherwise detect at all.

---

## Troubleshooting

**Check the logs first**: `/var/log/pwnagotchi.log` (the agent itself),
`/var/log/pwnagotchi-syswatchdog.log` (system-level recovery actions), and
`sudo journalctl -u bettercap` / `-u pwnagotchi` for anything at the systemd level.

**No internet / updates not checking in**: confirm actual connectivity with `curl`, not `ping` — some
networks/CDNs don't respond to ICMP even when HTTP/HTTPS works fine, so a failed ping alone doesn't
mean anything's wrong. If `apt` specifically hangs or fails while other traffic works, it's often an
IPv6-advertised-but-not-actually-routed network; this image already forces IPv4 for its own apt calls,
but a manual `apt update` may still need `-o Acquire::ForceIPv4=true` on a network like that.

**Device rebooted unexpectedly**: check `/var/log/pwnagotchi-syswatchdog.log` first — it logs the exact
reason before every reboot it triggers. If nothing's there, check `/var/log/pwnagotchi_crashes.log`,
written by the in-process `watchdog` plugin's own lockdown-reboot path.

**WiFi seems stuck/blind**: both watchdogs above already try to self-heal this (driver reload, bettercap
restart, interface rebuild) — give it a couple of minutes before assuming it needs manual intervention.
`iw dev` shows current interface state directly if you want to check by hand.

**Plugin acting up**: toggle it off/on from the web UI's Plugins page first — cheaper than SSHing in,
and confirms whether it's plugin-specific before digging further.
