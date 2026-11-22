# Changelog

Release notes for every pwnagotchi64 release, newest first. Older releases were removed from
GitHub Releases (only the latest keeps its image download); the git tags are kept, so the code
of every version is still available (`git checkout <tag>`).

## 0.0.1.2 (2026-09-19)

### 📶 Bluetooth is back
- Bluetooth phone tethering returns — pair your phone and share its internet over a Bluetooth PAN. Run `sudo bt-wizard` (the setup wizard also offers it) to pair, trust and connect in one step, with a retry loop if pairing doesn't take the first time.
- Bluetooth stays a **fallback only** — USB and Ethernet always win the connection, so the tether is only used when nothing else is up.
- Auto-updates won't run over a Bluetooth-only link (a phone tether isn't reliable enough to pull a full update), and a stuck Bluetooth adapter is now recovered in the background without rebooting the device.

### ⚠️ Enabling Bluetooth on an existing device
The `bt-wizard` tooling and services arrive automatically via the normal auto-update, but the radio itself is switched on at the **boot-config level**, which an in-place update can't change. To flip it on after updating, paste this over SSH — it enables the radio and reboots:

```
sudo sed -i 's/^dtoverlay=disable-bt$/dtparam=krnbt=on/' /boot/firmware/config.txt && sudo reboot
```

(Or flash this image fresh, which gets everything cleanly.)

⭐️ If you're enjoying the project, a star means a lot!

**Full Changelog**: https://github.com/ex18a/pwnagotchi64/compare/0.0.1.1...0.0.1.2

## 0.0.1.1 (2026-09-12)

### 📶 WiFi
- Better WiFi stability on Pi Zero 2 W — recovers from chip crashes without rebooting

### 🖥️ Display & UI
- Waveshare 4 driver fix for dark mode
- Optional PNG image faces
- Edit config from the web UI

**Recommended to flash this image manually**

⭐️ If you're enjoying the project, a star means a lot!

## 0.0.1.0 (2026-09-04)

### 📡 WiFi / External Adapters
- Automatic external WiFi adapter switching — plug in, it's picked up in seconds; unplug, falls back to built-in. Works at boot too.
- Shows on screen/in logs which WiFi device is actually in use (built-in or external, with driver name).
- Added monitor-mode + injection driver for RTL8812AU/8814AU/8821AU adapters, built into the image.
  - This driver only ships with a freshly flashed image — it doesn't install via `automatic-updates` on existing devices. If you need it, re-flash your SD card with the latest image.

### 🧠 AI / Agent
- AI-auto-toggle now also drops to AUTO on sad, not just bored.
- Retuned default personality values for a snappier pace.

### 🔄 Auto-Updates
- Fixed updates silently skipping post-install steps.
- Installs now self-heal from an interrupted dpkg state.
- Apt forced to IPv4 — fixes hangs on IPv6-broken networks.
- Fixed the "install failed" screen showing the wrong version.
- `whitelist` and `pisugar3i2c` plugins disabled by default.

### 🎨 UI / Display
- Fixed a display freeze in portrait-mode's landscape→portrait swap.
- Added `ui.status-log` toggle (now off by default — see SSH section).
- Simplified friend-panel label.

### 🛡️ Bluetooth
- Removed entirely, disabled at the hardware level too, for stability.

### 📶 New Plugin
- `channel_control` — toggle AI 5GHz channel use without invalidating a trained brain.

### 📄 Documentation
- Added `USER_GUIDE.md`.
- Trimmed `README.md` down to an overview.

### 🖥️ SSH / Terminal
- Persistent status bar (face, status, mode, PWND) in every SSH session via `tmux`. Mouse scroll works; click-drag copies to your clipboard (or Shift+drag as a fallback).
- MOTD now shows a `Pwnagotchi-64` ASCII banner.
- Timezone is now auto-detected via IP geolocation on boot, instead of always defaulting to UTC.

### 🛠️ Reliability
- Session recovery data now survives every restart, not just deliberate reboots.
- Fixed a bug where a successful update could get wiped and endlessly retried.
- Fixed `pwngrid-peer` being misdiagnosed as dead and restarted needlessly.
- Fixed the mode label (`AUTO`/`AI`/`TRAIN`) showing incorrectly sometimes.
- SDIO-wedge recovery now catches another crash signature.
- Fixed harmless shutdown-race errors being logged as scary failures.

It would mean a lot to me if you could leave a ⭐️ on the project page!

## 0.0.0.9 (2026-08-18)

### 🧠 AI / Agent
- When an epoch turns up nothing worth attacking, the device now parks on a channel (one of your `personality.channels`, or 1/6/11 by default) for a bit instead of pointlessly hopping around — gives the wifi chip a break when there's nothing nearby.
- Revised default personality settings: quicker recon cycle, shorter AP timeout, and faster AI wake.

### 📡 Bettercap / WiFi
- Bettercap patch bumped to pwnagotchi6 — fixes a channel-hop deadlock and re-syncs with upstream master.

### 🚀 Performance / efficiency
- Hashvault plugin - Stopped rescanning the whole handshakes folder every second — the unique-handshake count is cached and only recounted when a new one actually lands.
- whitelist plugin -  keeps its known entries in memory now instead of re-reading `.whitelist` on every pass.

### 🖥️ Display / Hardware
- **Added an `i2coled` driver for I2C SSD1306 OLED screens.** (closes #12)
- Long handshake SSIDs get truncated on the Waveshare 3/4 so the last-pwned name stops overlapping the mode text.
- friend name flush-left on portrait, and removed the `friend_face` element as spacing was to tight.

### ⚙️ Config / Setup
- Setup wizard: validates the device name as a real hostname, lets you clear home_networks/whitelist and cancel the restart, writes the portrait display variant directly, and points at `defaults.toml` for the full setting list.
- `sleep`/`sleep2` faces are arrays now.
- Dropped the default third-party plugin repo from `custom_plugin_repos`.
- Builder no longer seeds `config.toml` from `defaults.toml` at image-build time.

### 📄 Misc
- wpa-sec: fixed the download-interval throttle (was firing way more often than the configured interval) and stopped it overwriting a good cracked-passwords file with a truncated download.

## 0.0.0.8 (2026-08-09)

### 🧠 AI / Agent
- Home network whitelist added; a whitelisted area no longer counts as "blind" for reboot purposes.
- Fixed AI getting stuck in AUTO if boredom hit mid-training.
- Deterministic prediction outside of training, laziness raised to 0.8.
- Mode indicator shows `TRAIN` during a training batch.
- Minimum RSSI threshold lowered to -95 (auto mode)

### 📡 Bettercap / WiFi
- Bettercap patch bumped to pwnagotchi5 (nl80211 netlink channel hopping).

### 🛡️ Reliability
- Watchdog reboot timer widened 30s→60s after a false-positive.
- Fixed RTC persistence (missing hwclock).

### 📶 Bluetooth / Networking
- hci0 hardware errors auto-recover now, no reboot needed.
- usb0 no longer adds a default route without a real carrier; watchdog reconciles it if it goes stale.
- Fixed `is_connected()` falsely reporting no internet on a working connection.

### 🔄 Auto-Updates
- Added a retroactive update blocklist, with on-screen notice if you're running something blocked.
- Patched bettercap and `builder/data`/`requirements.txt` now actually sync through in-place updates.
- Pip install timeout widened 300s→900s.
- Updates notify-only over bluetooth (no bandwidth-heavy installs).

### 🖥️ Display / Hardware
- Fixed screen rotation (was 180° out).
- Fixed plugin elements staying black after a colour inversion.
- Fixed Display Hat Mini crash-loop, and the ACT LED going dark after boot (now configurable).
- Portrait name/cursor centering is resolution-independent now.
- Fixed TRAIN mode text clipping, and mode jumping to the wrong corner after a live portrait/landscape switch.
- Centered status text and face on the portrait drivers.
- Fixed battery %, AGE, IP, and PWND/last-pwned-name alignment and spacing, both portrait and landscape.
- Fixed APS colliding with the channel number.
- Dropped the brackets around the last-pwned network name.
- All plugin-positioned elements (battery, AGE, IP, memtemp) now follow the driver's own layout instead of a separate hardcoded portrait table — fixes things reverting to the wrong spot after toggling portrait mode live.

### ⚙️ Config / Setup
- Fixed swapped example values in the whitelist/home_networks defaults.
- Setup wizard now asks for home networks and other skip-list networks separately; dropped the interactive bluetooth step.
- Default auto-update check interval 6h → 1h.

### 📄 Misc
- README restructured — leads with what Pwnagotchi is, explains the home/bored AI pause behavior.
- Added `tweak_view` as a default plugin.
- Fixed mark-as-read never actually clearing the inbox unread count.
- Web UI wasn't multi-threaded, fixed.
- Fixed a text-wrapping bug that could drop the last line of status text.
- motd cleaned up (typos, box-drawing border, regenerates on in-place updates too).

### ⚠️ Known Issue
Bluetooth tethering still causes real stability issues under heavy use — recommend not setting it up for now. Known bug, not fixed yet.

## 0.0.0.7 (2026-07-16)

A big one — multi-day marathon fixing silent failure modes and testing in the field. Should be noticeably more self-healing now.

### 🧠 AI / Agent
- AI now pauses in the same spot for too long and wakes up when it actually moves somewhere new, not just from a stray AP passing by.
- Pauses around home Wi-Fi too.
- Reverted AI parameter ranges back to the original, wider ones — the narrower version hurt handshake capture.
- `brain.nn` self-heals instead of crashing if it becomes incompatible. Fixed a few silent AI startup/race bugs.
- Always boots into AUTO mode regardless of tether state.
- Smarter brain backups: dated snapshots, rolling + permanent tiers, bad resets get backed up instead of deleted.
- Capped how many channels the AI can select at once (max 6) — letting it pick 7+ at a time was too much for this WiFi chip to handle reliably.

### 📡 Bettercap / WiFi Reliability
- Forked bettercap to fix some real crash bugs for stability (found and fixed three separate data races).
- Fixed bettercap silently going blind to all wifi activity for 90+ minutes after a restart without anyone noticing.
- Monitor-mode startup retries instead of crashing.
- Fixed channel holding not actually holding during deauth/assoc waits — bettercap kept drifting off channel in the background, missing handshake replies. Now uses bettercap's own proper pinning mechanism instead, and fixed a crash that mechanism could trigger on startup (found via live field testing).
- Fixed the deauth/assoc throttle, which was silently doing nothing before.
- Tuned wifi hop timing based on a lot of on-device crash testing.

### 🛡️ Reliability / Watchdogs
- New hardware watchdog for full kernel lockups.
- New system watchdog for bettercap crash-loops, stale logs, overheating.
- Fixed the updater hanging the whole device under memory pressure.
- Removed a destructive "auto-heal" that wiped the device's grid identity over harmless errors.
- Quieter logging during updates and other known-benign hiccups.

### 🔋 PiSugar 3 Battery
- Configurable low-battery shutdown threshold.
- Fixed the PiSugar not cutting power after a clean shutdown.
- Fixed the battery percentage curve using real logged data — it used to sit at ~60% for hours then crash to empty.

### 📶 Bluetooth
- Fixed reconnecting over Bluetooth wiping the device's default route.
- Auto-updates avoid running over Bluetooth-only connections now.
- New interactive setup wizard (`pwnagotchi --setup`), including Bluetooth pairing.

### 🖥️ E-Ink Display
- Added another Waveshare portrait display, cleaned up layout across the board.
- Full-refresh timing based on actual screen updates instead of a rough guess, fixing ghosting.

### 🗂️ Handshakes
- Cleaned up a hashvault quirk that left 0-byte marker files in the hashes folder — that bookkeeping is hidden now.

### 📄 Misc
- Fixed a few plugins/threads dying silently with no trace in the logs.
- Added an explanation to the README of why Pwnagotchi has an AI at all.

## 0.0.0.6 (2026-07-08)

### 🎨 UI / Web Interface
- **Home page display now scales properly** — the device UI image resizes to fit the browser window on both width and height (no more scrolling to see the whole screen on portrait builds), while still fitting normally on landscape setups. No more stretching/distortion.

### 🖥️ E-Ink Display (Portrait Driver)
- **Fixed washed-out/grey blacks** on the Waveshare V4 portrait driver — full hardware refreshes are now triggered once per 3 epoch instead of only every 1000 renders, keeping partial-refresh ghosting from building up.
>note there is a bug where the screen looks bad when first booted but cleans up pretty quicky. ill sort this soon.
- Portrait mode now supports booting directly into portrait (not just landscape→portrait swap), with proper font/position handling either way.
- have re-written the way portrait mode is handled. it now switchs to a seperate custom driver to fix override issues to the lanscape driver, plugin still handles font sizing and the driver switch so still needed if you like portrait mode
- Added a safety check that disables portrait mode entirely if an unsupported display type is configured, rather than failing partway. the plugin was designed for waveshare eink 2.13 v4 and will not work with others.

### 🛡️ Reliability / Watchdog
- **Fixed a false-recovery bug in the Watchdog plugin** — previously, it treated bettercap as "recovered" as soon as `systemctl` reported the service active, even though the REST API often wasn't actually ready yet. It now waits and verifies `agent.session()` responds before declaring recovery, preventing the device from getting stuck silently blind after a bettercap crash.
- some ui elements like uptime and aps frozen after a while (maybe fixed now).

### 🧠 Agent
- Interaction throttle for `associate()`/`deauth()` raised from `0.7` → `0.8`. (testing long term stability but i think this is the sweet spot)

### 🔋 Performance
- **`memtemp` plugin now throttles to a 15-second refresh interval** instead of recalculating and redrawing mem/CPU/temp/freq stats on every single UI redraw — reduces unnecessary reads of `/sys` and CPU work.

### 📄 Misc
- Added a startup banner in logs with the pwnagotchi64 version on boot making it easier to see restarts.

## 0.0.0.5 (2026-06-30)

### v0.0.0.5: The AI Overhaul Update

**Summary**

Version 0.0.0.5 is the biggest update yet to how your Pwnagotchi actually thinks and looks. The reward model has been rebalanced and the personality dial ranges widened so the AI can explore a much wider range of behavior  and a brand-new interaction history decay system means your unit won't permanently blacklist a network it met once in passing. On top of that, the entire Web UI has been rebuilt on a modern dark theme.

#### 🚀 New Features

* **Interaction History Decay:** Networks you've maxed out interactions with are no longer permanently ignored. If a network hasn't been seen in 30 minutes, its interaction count slowly decays back down, and fully resets once you've been away from it long enough — so a network you hammered at the shop won't still be ignored when you get home, and vice versa.
* **Smarter AI-AUTO Personality Restore:** When the AI goes dormant and drops into AUTO mode, your unit's personality settings (recon time, RSSI thresholds, channel hopping, etc.) now properly snap back to your configured baseline every epoch — including the values pushed live to bettercap — instead of getting stuck on whatever the AI last set before it went quiet.
* **Modernized Web UI:** The entire web interface has been rebuilt on a dark, terminal-green themed UI and plugins page now shows inline descriptions and links straight through to a plugin's own web UI when it has one.

#### 🛠️ Improvements & Updates

* **Widened AI Exploration Ranges:** The AI's allowed parameter ranges (recon time, TTLs, recon multiplier, etc.) have been widened so it has a clearer, more extreme "this setting is bad" signal to learn from on both ends — letting it find a genuine sweet spot rather than hugging conservative defaults.
* **Rebalanced Reward Function:** Added a proper reward bonus for sustained activity (mirroring the existing sad/bored penalties), and bumped the theoretical reward ceiling to match.
* **Tuned Default Personality:** Rebuilt the baseline `personality.*` defaults for a calmer, less aggressive AUTO/AI-disabled experience — roughly a 3-minute epoch pace, tighter RSSI selectivity, and proportionally rescaled mood thresholds (excited/bored/sad) to match the new timing.
* **Faster Auto-Updates:** The auto-update plugin now checks installed apt packages first and only runs `apt-get update`/`install` if something's actually missing — skipping a slow, unnecessary step on most update runs.
* **Removed dev-blind:** Fully removed now that Watchdog's blindness detection covers the same ground, as planned in the previous release.
* **Cleaned up unused USB gateway/networking leftovers** from the builder assets.

#### 🐛 Bug Fixes

* **AI Pause Now Actually Pauses:** Fixed a bug where switching to AUTO mode when bored only changed the on-screen label — the AI kept running, training, and overwriting personality settings in the background regardless. The AI training thread now genuinely suspends and resumes in sync with the AUTO/AI mode switch.
* **Web UI Missing Auth Key Crash:** Fixed a `KeyError` crash on `/inbox` and other pages caused by a missing `ui.web.auth` config default.

#### 🙏 It would mean a lot to me if you could leave a ⭐️ on the project page!

## 0.0.0.4 (2026-06-25)

### v0.0.0.4: The Automation Update

**Summary**
Version 0.0.0.4 brings major quality-of-life improvements and smarter pacing to your Pwnagotchi. The highlight of this release is the new auto-update plugin—meaning your SD-card flashing days are finally over. Also introduced dynamic AI-AUTO state switching to manage your unit's boredom, modernized parts of the Web UI,

#### 🚀 New Features
* **Auto-Update Plugin:** Say goodbye to flashing SD cards for every release. Your Pwnagotchi will now automatically upgrade to the latest version by itself.
* **Dynamic AI-AUTO Switching:** If your Pwnagotchi gets bored, the AI will now turn off and seamlessly drop into AUTO mode to save resources. Taking your buddy for a walk will wake the AI right back up.

#### 🛠️ Improvements & Updates
* **Modernized Web UI:** The plugins page has been completely redesigned for a cleaner, more modern look.
* **Smoother Battery Monitoring:** Updated the PiSugar plugin to average its readings over a 10-second window, which stops the battery percentage from sporadically jumping around (as much).
* **Accessible Handshakes:** Moved the handshakes directory directly into the user folder (`/home/pwn/`) so you can access your caps much faster.
* **Watchdog:** The watchdog plugin has been updated to actively monitor for bettercap crashes to keep things running smoothly.
* **Visual Blindness Indicator:** If your Pwnagotchi goes "blind," it will now clearly express this status directly on the screen.
This is part of watchdog and will replace the dev-blind plugin (dev-blind will be removed in the next release)

#### 🐛 Bug Fixes
* **Channel Desync Fixed:** Resolved an issue where the unit would sometimes wait on the wrong channel after a deauth or association attempt.
* **Pwngrid Routing:** Fixed the profile link so it correctly points to the new Pwngrid.
* **AI Laziness Tuned:** Fixed an issue with default laziness. Your Pwnagotchi is now much more likely to start a training session, though reduced the epochs per episode to keep the pacing balanced.

#### 🙏 It would mean a lot to me if you could leave a ⭐️ on the project page!

## 0.0.0.3 (2026-06-22)

### v0.0.0.3 - Stability Update

I've focused mostly on bug fixes and stability for this update.

#### 🌐 PwnGRID Fixes
* **Startup Delay:** In the last version, there were still some errors coming from GRID not connecting to the API. I think I've fixed this by delaying the startup time so the Pwnagotchi is fully ready before it tries to connect.
* **No More Freezing:** There was also an issue where if it tried to connect and failed, it would pause the entire Pwnagotchi for 60 seconds while it waited to retry. This has also been fixed.

#### 🛡️ WiFi & Watchdog Improvements
* **Hardware Monitoring:** I've had problems with the nexmon driver crashing the built-in WiFi of the Pi. I've updated the Watchdog plugin to actively monitor the WiFi hardware—if it sees it has crashed, the Pwnagotchi will now reboot automatically.
* **Packet Throttling:** I've added a small pause between deauth and assoc packets, hopefully to stop the WiFi chip from being overwhelmed and crashing in the first place.

> **A quick note on hardware:** The built-in WiFi was not designed to do monitor mode and packet injection. The nexmon driver is a hack to make it capable of this, but it is inherently unstable and will cause crashes.

---

#### 🙏 A Massive Thank You
Lastly, I'd like to thank everyone for their support on the project. I'm very happy people want to try my version of Pwnagotchi and have fun with it.

I've put many days and hours into making this version what it is through coding, testing, and troubleshooting. 

It would mean a lot to me if you could leave a ⭐️ on the project page! 

Thank you for your support.

## 0.0.0.2 (2026-06-17)

now connects to pwngrid

## 0.0.0.1 (2026-06-16)

### v0.0.0.1 - Initial Public Release

First official release of **Pwnagotchi 64-Bit AI Edition**!
