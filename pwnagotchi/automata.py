import logging
import copy

import pwnagotchi.plugins as plugins
from pwnagotchi.ai.epoch import Epoch


# basic mood system
class Automata(object):
    def __init__(self, config, view):
        self._config = config
        self._view = view
        self._epoch = Epoch(config)

        # --- AI AUTO-TOGGLE INIT ---
        # Track if the user originally wanted AI enabled
        self._ai_base_enabled = config.get('ai', {}).get('enabled', False)
        self._default_personality = copy.deepcopy(config['personality'])   # baseline snapshot
        # consecutive epochs since a whitelisted AP was last seen (see set_bored-style AI toggle below).
        # starts past the threshold so a fresh boot that never sees the home network
        # doesn't impose an artificial cooldown on the normal wake-on-activity path
        self._home_absent_for = config['personality'].get('home_absent_epochs', 5)
        # min consecutive active epochs required before AI wakes back up from a
        # bored-triggered AUTO pause -- without this, a single deauth/assoc
        # attempt against one faint, unattackable-in-practice AP (anything
        # above min_rssi counts, however marginal) was enough to flip straight
        # back to AI, undoing the whole point of pausing on boredom in the
        # first place
        self._ai_wake_epochs = config['personality'].get('ai_wake_epochs', 2)
        # BSSIDs visible at the moment the AI last went bored -- compared
        # against what's currently visible to detect a genuine location
        # change (see _environment_changed_enough()), rather than waking on
        # any random activity against the same static set of nearby APs
        self._env_snapshot_at_bored = set()

    def _on_miss(self, who):
        logging.info("it looks like %s is not in range anymore :/", who)
        self._epoch.track(miss=True)
        self._view.on_miss(who)

    def _on_error(self, who, e):
        # when we're trying to associate or deauth something that is not in range anymore
        # (if we are moving), we get the following error from bettercap:
        # error 400: 50:c7:bf:2e:d3:37 is an unknown BSSID or it is in the association skip list.
        if 'is an unknown BSSID' in str(e):
            self._on_miss(who)
        else:
            logging.error(e)

    def set_starting(self):
        self._view.on_starting()

    def set_ready(self):
        plugins.on('ready', self)

    def in_good_mood(self):
        return self._has_support_network_for(1.0)

    def _has_support_network_for(self, factor):
        bond_factor = self._config['personality']['bond_encounters_factor']
        total_encounters = sum(peer.encounters for _, peer in self._peers.items())
        support_factor = total_encounters / bond_factor
        return support_factor >= factor

    # triggered when it's a sad/bad day but you have good friends around ^_^
    def set_grateful(self):
        self._view.on_grateful()
        plugins.on('grateful', self)

    def set_lonely(self):
        if not self._has_support_network_for(1.0):
            logging.info("unit is lonely")
            self._view.on_lonely()
            plugins.on('lonely', self)
        else:
            logging.info("unit is grateful instead of lonely")
            self.set_grateful()

    def set_bored(self):
        factor = self._epoch.inactive_for / self._config['personality']['bored_num_epochs']
        if not self._has_support_network_for(factor):
            logging.warning("%d epochs with no activity -> bored", self._epoch.inactive_for)
            self._view.on_bored()
            plugins.on('bored', self)
        else:
            logging.info("unit is grateful instead of bored")
            self.set_grateful()

    def set_sad(self):
        factor = self._epoch.inactive_for / self._config['personality']['sad_num_epochs']
        if not self._has_support_network_for(factor):
            logging.warning("%d epochs with no activity -> sad", self._epoch.inactive_for)
            self._view.on_sad()
            plugins.on('sad', self)
        else:
            logging.info("unit is grateful instead of sad")
            self.set_grateful()

    def set_angry(self, factor):
        if not self._has_support_network_for(factor):
            logging.warning("%d epochs with no activity -> angry", self._epoch.inactive_for)
            self._view.on_angry()
            plugins.on('angry', self)
        else:
            logging.info("unit is grateful instead of angry")
            self.set_grateful()

    def set_excited(self):
        logging.warning("%d epochs with activity -> excited", self._epoch.active_for)
        self._view.on_excited()
        plugins.on('excited', self)

    def set_rebooting(self):
        self._view.on_rebooting()
        plugins.on('rebooting', self)

    def wait_for(self, t, sleeping=True):
        plugins.on('sleep' if sleeping else 'wait', self, t)
        self._view.wait(t, sleeping)
        self._epoch.track(sleep=True, inc=t)

    def is_stale(self):
        return self._epoch.num_missed > self._config['personality']['max_misses_for_recon']

    def any_activity(self):
        return self._epoch.any_activity

    # --- AI AUTO-TOGGLE HELPER ---
    def _restore_default_personality(self):
        # only log (and only once, right when it actually happens) the fields
        # that differ from baseline -- this runs every epoch while paused, and
        # after the first restore there's nothing left to change, so logging
        # unconditionally would just spam "[AUTO] setting new policy:" forever
        changed = {
            name: (self._config['personality'].get(name), value)
            for name, value in self._default_personality.items()
            if self._config['personality'].get(name) != value
        }

        self._config['personality'].update(self._default_personality)

        if changed:
            logging.info("[AUTO] setting new policy:")
            for name, (old, new) in changed.items():
                logging.info("[AUTO] ! %s: %s -> %s" % (name, old, new))

        # bettercap doesn't re-read the config dict on its own for these three —
        # they were pushed to it live by on_ai_policy(), so they need to be
        # pushed back the same way or bettercap stays on a stale/bad AI value
        self.run('set wifi.ap.ttl %d' % self._config['personality']['ap_ttl'])
        self.run('set wifi.sta.ttl %d' % self._config['personality']['sta_ttl'])
        self.run('set wifi.rssi.min %d' % self._config['personality']['min_rssi'])

    def _snapshot_environment(self):
        return {ap['mac'] for ap in self._access_points}

    def _environment_changed_enough(self):
        # compares what's visible right now against the snapshot taken the
        # moment the AI went bored -- e.g. sitting still at home, your own
        # AP and a few neighbors' get snapshotted; a stranger's hotspot
        # passing by doesn't touch that set at all (still 100% present), but
        # walking away drops the ORIGINAL APs out of range one by one. Once
        # enough of the original set is gone, that's a real location change,
        # regardless of whatever new APs have or haven't shown up in the
        # meantime.
        current = self._snapshot_environment()
        if not self._env_snapshot_at_bored:
            # bored fired with nothing visible at all (a true dead zone) --
            # anything showing up now is unambiguously a change, since there
            # was nothing before for a stray AP to be mistaken for
            return bool(current)
        still_present = self._env_snapshot_at_bored & current
        remaining_fraction = len(still_present) / len(self._env_snapshot_at_bored)
        threshold = self._config['personality'].get('environment_change_threshold', 0.5)
        return remaining_fraction <= (1 - threshold)
    # ------------------------------

    def next_epoch(self):
        logging.debug("agent.next_epoch()")

        was_stale = self.is_stale()
        did_miss = self._epoch.num_missed

        self._epoch.next()

        # --- AI AUTO-TOGGLE MOD ---
        if self._ai_base_enabled:
            # while parked in auto with AI paused, keep personality pinned to
            # the baseline config so it can never drift/get stuck on a bad
            # AI-set value (e.g. min_rssi: -30).
            #
            # Gated on is_training() too, not just is_ai_paused(): pausing
            # only stops the AI worker loop between whole training batches
            # (self._model.learn() runs all epochs_per_episode epochs in one
            # blocking call, only checking the pause flag once it returns),
            # so a batch already in flight when pause was requested keeps
            # calling on_ai_policy() every epoch for however many epochs are
            # left in it. Restoring defaults here on every one of those
            # epochs raced directly against that in-flight batch -- confirmed
            # live on-device: both "[AUTO] setting new policy" and
            # "[ai] setting new policy" firing in the same epoch, each
            # overwriting the other's config/bettercap values. Waiting for
            # is_training() to actually go False means this only ever fires
            # once the AI has genuinely gone idle, matching the same event
            # the "[ai] idle" / on-screen AUTO label switch already wait for
            # in train.py's worker loop.
            if self.mode == 'auto' and self.is_ai_paused() and not self.is_training():
                self._restore_default_personality()

            # home-network guard: whitelisted APs are never attacked, but if any
            # is currently visible we also treat that like being bored -- pause
            # the AI and keep it down until none have been seen for
            # personality.home_absent_epochs epochs in a row
            whitelist = self._config['main']['whitelist']
            home_visible = bool(whitelist) and self.is_whitelisted_ap_visible()
            if whitelist:
                self._home_absent_for = 0 if home_visible else self._home_absent_for + 1
            home_absent_epochs = self._config['personality'].get('home_absent_epochs', 5)
            home_on_cooldown = bool(whitelist) and self._home_absent_for < home_absent_epochs

            if home_visible and not self.is_ai_paused():
                # gated on is_ai_paused() rather than mode == 'ai': mode can still be
                # stuck on 'auto' here if the home network was already visible at
                # boot, before the wake branch below ever got a chance to run
                logging.info("[AI SLEEP] Home network detected. Suspending AI and dropping to AUTO.")
                self.mode = 'auto'
                self.pause_ai()          # stops inference/training -- view label updates once the
                                          # worker actually goes idle (see train.py _ai_worker), not here,
                                          # since a training batch already in flight runs to completion first

            elif self.mode == 'ai' and self._epoch.bored_for >= 1:
                logging.info("[AI SLEEP] Pwnagotchi is Bored. Suspending AI and dropping to AUTO.")
                self.mode = 'auto'
                self._env_snapshot_at_bored = self._snapshot_environment()
                self.pause_ai()          # stops inference/training -- see comment above

            elif self.mode == 'auto' and not home_visible and not home_on_cooldown \
                    and self._epoch.inactive_for == 0 and self._epoch.active_for >= self._ai_wake_epochs \
                    and self._environment_changed_enough():
                logging.info("[AI WAKE] Target engaged! Resuming AI mode.")
                self.mode = 'ai'
                self._view.set('mode', '  AI')
                self.resume_ai()         # resumes inference/training
        # --------------------------

        # after X misses during an epoch, set the status to lonely or angry
        if was_stale:
            factor = did_miss / self._config['personality']['max_misses_for_recon']
            if factor >= 2.0:
                self.set_angry(factor)
            else:
                logging.warning("agent missed %d interactions -> lonely", did_miss)
                self.set_lonely()
        # after X times being bored, the status is set to sad or angry
        elif self._epoch.sad_for:
            factor = self._epoch.inactive_for / self._config['personality']['sad_num_epochs']
            if factor >= 2.0:
                self.set_angry(factor)
            else:
                self.set_sad()
        # after X times being inactive, the status is set to bored
        elif self._epoch.bored_for:
            self.set_bored()
        # after X times being active, the status is set to happy / excited
        elif self._epoch.active_for >= self._config['personality']['excited_num_epochs']:
            self.set_excited()
        elif self._epoch.active_for >= 5 and self._has_support_network_for(5.0):
            self.set_grateful()

        plugins.on('epoch', self, self._epoch.epoch - 1, self._epoch.data())

        if self._epoch.blind_for >= self._config['main']['mon_max_blind_epochs']:
            logging.critical("%d epochs without visible access points -> rebooting ...", self._epoch.blind_for)
            self._reboot()
            self._epoch.blind_for = 0
