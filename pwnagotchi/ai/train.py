import _thread
import threading
import time
import random
import os
import json
import logging
import shutil

import pwnagotchi.plugins as plugins
import pwnagotchi.ai as ai


class Stats(object):
    def __init__(self, path, events_receiver):
        self._lock = threading.Lock()
        self._receiver = events_receiver

        self.path = path
        self.born_at = time.time()
        self.epochs_lived = 0
        self.epochs_trained = 0

        self.worst_reward = 0.0
        self.best_reward = 0.0

        self.load()

    def on_epoch(self, data, training):
        best_r = False
        worst_r = False
        with self._lock:
            reward = data['reward']
            if reward < self.worst_reward:
                self.worst_reward = reward
                worst_r = True

            elif reward > self.best_reward:
                best_r = True
                self.best_reward = reward

            self.epochs_lived += 1
            if training:
                self.epochs_trained += 1

        self.save()

        if best_r:
            self._receiver.on_ai_best_reward(reward)
        elif worst_r:
            self._receiver.on_ai_worst_reward(reward)

    def load(self):
        with self._lock:
            if os.path.exists(self.path) and os.path.getsize(self.path) > 0:
                logging.info("[ai] loading %s" % self.path)
                with open(self.path, 'rt') as fp:
                    obj = json.load(fp)

                self.born_at = obj['born_at']
                self.epochs_lived, self.epochs_trained = obj['epochs_lived'], obj['epochs_trained']
                self.best_reward, self.worst_reward = obj['rewards']['best'], obj['rewards']['worst']

    def save(self):
        with self._lock:
            logging.info("[ai] saving %s" % self.path)

            data = json.dumps({
                'born_at': self.born_at,
                'epochs_lived': self.epochs_lived,
                'epochs_trained': self.epochs_trained,
                'rewards': {
                    'best': self.best_reward,
                    'worst': self.worst_reward
                }
            })

            temp = "%s.tmp" % self.path
            with open(temp, 'wt') as fp:
                fp.write(data)

            os.replace(temp, self.path)


class AsyncTrainer(object):
    # epochs since boot before the first training batch is allowed to start.
    # A batch already in flight only stops between batches (see _ai_worker),
    # so starting one immediately on boot means a home-network (or any other)
    # pause can't actually take effect until that whole first batch finishes.
    # Holding off gives other startup-time pause conditions a window to kick
    # in before the AI ever commits to one.
    MIN_EPOCHS_BEFORE_TRAINING = 10

    # ai.load() can transiently fail for reasons that clear up on their own
    # within seconds -- e.g. supported_channels() coming back empty because
    # mon0 hasn't finished coming up yet at that exact instant, which makes
    # the freshly-built action space not match a saved brain.nn that does
    # have channel dimensions. Confirmed on-device: this happened right as
    # a nexmon/mon0 dropout was being recovered from, and without a retry
    # here the AI simply never started for the rest of that boot -- no
    # crash, no log beyond the one failure, just silently inert.
    #
    # Also confirmed on-device (separately) that bettercap itself can take
    # well over a minute to actually come up after a rapid string of
    # restarts in quick succession -- mon0/wlan0 briefly don't exist yet,
    # bettercap-launcher fails outright, and systemd has to retry it two or
    # three times before it succeeds.
    #
    # Discarding a trained brain.nn is expensive (hours/days of training
    # lost) and this retry loop is the only thing standing between a slow
    # bettercap startup and that happening, so it's deliberately generous:
    # 16 attempts * 60s = 15 minutes before ever giving up and accepting a
    # fresh model. Far longer than any observed bettercap startup, but the
    # cost of waiting a bit longer in the rare genuinely-stuck case is
    # nothing compared to the cost of wrongly discarding a good model.
    AI_LOAD_MAX_ATTEMPTS = 16
    AI_LOAD_RETRY_DELAY = 60

    # Dated, numbered snapshots of the brain -- separate from brain.nn's own
    # in-place saves (which a bad reset, a bug, or a bad config change can
    # still wipe out) and from the .incompatible backup (which only ever
    # holds the single most recent one, getting overwritten by the next
    # reset). Deliberately never pruned/rotated here -- the point is to
    # never lose one, not to save disk space, so this is left growing.
    BRAIN_BACKUP_DIR = "/root/brain-backups"
    BRAIN_BACKUP_INTERVAL_EPOCHS = 100

    def __init__(self, config):
        self._config = config
        self._model = None
        self._is_training = False
        self._training_epochs = 0
        self._nn_path = self._config['ai']['path']
        self._stats = Stats("%s.json" % os.path.splitext(self._nn_path)[0], self)
        self._ai_paused = threading.Event()
    
    def set_training(self, training, for_epochs=0):
        self._is_training = training
        self._training_epochs = for_epochs

        if training:
            plugins.on('ai_training_start', self, for_epochs)
        else:
            plugins.on('ai_training_end', self)

    def is_training(self):
        return self._is_training

    def training_epochs(self):
        return self._training_epochs

    def start_ai(self):
        _thread.start_new_thread(self._ai_worker, ())

    def pause_ai(self):
        if not self._ai_paused.is_set():
            logging.info("[ai] pausing")
            self._ai_paused.set()

    def resume_ai(self):
        if self._ai_paused.is_set():
            logging.info("[ai] resuming")
            self._ai_paused.clear()

    def is_ai_paused(self):
        return self._ai_paused.is_set()

    def _save_ai(self):
        logging.info("[ai] saving model to %s ..." % self._nn_path)
        temp = "%s.tmp" % self._nn_path
        self._model.save(temp)
        os.replace(temp, self._nn_path)

    def _backup_ai(self):
        try:
            os.makedirs(self.BRAIN_BACKUP_DIR, exist_ok=True)
            tag = "epoch%d_%s" % (self._stats.epochs_trained, time.strftime("%Y-%m-%d_%H-%M-%S"))
            nn_backup = os.path.join(self.BRAIN_BACKUP_DIR, "brain_%s.nn" % tag)
            shutil.copy2(self._nn_path, nn_backup)
            json_path = "%s.json" % os.path.splitext(self._nn_path)[0]
            if os.path.exists(json_path):
                shutil.copy2(json_path, os.path.join(self.BRAIN_BACKUP_DIR, "brain_%s.json" % tag))
            logging.info("[ai] backed up brain to %s" % nn_backup)
        except Exception as e:
            logging.error("[ai] failed to back up brain: %s" % e)

    def _render_env_safe(self):
        try:
            if hasattr(self._model.env, 'envs'):
                self._model.env.envs[0].render()
            else:
                self._model.env.render()
        except Exception as e:
            pass

    def on_ai_step(self):
        self._render_env_safe()

        if self._is_training:
            self._save_ai()

        self._stats.on_epoch(self._epoch.data(), self._is_training)

        # epochs_trained is only incremented by the on_epoch() call just
        # above, so check it after -- this must land exactly on each
        # multiple of 100, not just "some time after"
        if self._is_training and self._stats.epochs_trained > 0 \
                and self._stats.epochs_trained % self.BRAIN_BACKUP_INTERVAL_EPOCHS == 0:
            self._backup_ai()

    def on_ai_training_step(self, _locals, _globals):
        self._render_env_safe()
        plugins.on('ai_training_step', self, _locals, _globals)
        return True

    def on_ai_policy(self, new_params):
        plugins.on('ai_policy', self, new_params)
        logging.info("[ai] setting new policy:")
        for name, value in new_params.items():
            if name in self._config['personality']:
                curr_value = self._config['personality'][name]
                if curr_value != value:
                    logging.info("[ai] ! %s: %s -> %s" % (name, curr_value, value))
                    self._config['personality'][name] = value
            else:
                logging.error("[ai] param %s not in personality configuration!" % name)

        self.run('set wifi.ap.ttl %d' % self._config['personality']['ap_ttl'])
        self.run('set wifi.sta.ttl %d' % self._config['personality']['sta_ttl'])
        self.run('set wifi.rssi.min %d' % self._config['personality']['min_rssi'])

    def on_ai_ready(self):
        self._view.on_ai_ready()
        plugins.on('ai_ready', self)

    def on_ai_best_reward(self, r):
        logging.info("[ai] best reward so far: %s" % r)
        self._view.on_motivated(r)
        plugins.on('ai_best_reward', self, r)

    def on_ai_worst_reward(self, r):
        logging.info("[ai] worst reward so far: %s" % r)
        self._view.on_demotivated(r)
        plugins.on('ai_worst_reward', self, r)

    def _ai_worker(self):
        self._model = False

        # ai.load() returning False because ai.enabled=false in config is
        # not a failure worth retrying -- it's never going to succeed by
        # design, so retrying it just burns AI_LOAD_MAX_ATTEMPTS *
        # AI_LOAD_RETRY_DELAY seconds logging a misleading "load attempt
        # failed, retrying" warning for something that isn't actually a
        # transient hiccup at all.
        if not self._config['ai']['enabled']:
            ai.load(self._config, self, self._epoch)  # logs "ai disabled" and returns False
            return

        for attempt in range(1, self.AI_LOAD_MAX_ATTEMPTS + 1):
            self._model = ai.load(self._config, self, self._epoch)
            if self._model:
                break
            if attempt < self.AI_LOAD_MAX_ATTEMPTS:
                logging.warning("[ai] load attempt %d/%d failed, retrying in %ds ..." %
                                 (attempt, self.AI_LOAD_MAX_ATTEMPTS, self.AI_LOAD_RETRY_DELAY))
                time.sleep(self.AI_LOAD_RETRY_DELAY)
            else:
                logging.error("[ai] giving up after %d attempts, AI will not run this boot" %
                               self.AI_LOAD_MAX_ATTEMPTS)

        if self._model:
            self.on_ai_ready()

            epochs_per_episode = self._config['ai']['epochs_per_episode']

            obs = None
            was_paused = False
            while True:
                if self._ai_paused.is_set():
                    if not was_paused:
                        # only reached once any batch that was already in flight has
                        # finished, so this is when the AI has actually gone idle --
                        # update the on-screen label here rather than at the moment
                        # pause was requested, so it doesn't lie about still training
                        logging.info("[ai] idle")
                        self._view.set('mode', 'AUTO')
                        was_paused = True
                    time.sleep(1)
                    continue
                was_paused = False
                self._render_env_safe()

                # this whole block -- including plain predict()/step(), not just
                # learn() -- ends up calling on_ai_policy(), which pushes settings
                # to bettercap over its API. A transient bettercap hiccup there
                # used to raise straight out of this method uncaught; since this
                # runs on a bare _thread (not threading.Thread), an uncaught
                # exception here silently kills the whole AI worker for the rest
                # of the process's life -- no crash log, no restart, nothing (the
                # traceback goes to stderr, which the systemd unit discards) --
                # the AI just permanently stops updating its policy until next
                # boot. Confirmed on-device: a policy set right after boot, then
                # nothing for the next ~24 epochs/38 minutes, until the next
                # restart. predict()/step() run unguarded on every epoch before
                # MIN_EPOCHS_BEFORE_TRAINING is reached (learn() never even gets
                # called yet), so this window is hit on every single boot.
                try:
                    if self._epoch.epoch >= self.MIN_EPOCHS_BEFORE_TRAINING and random.random() > self._config['ai']['laziness']:
                        logging.info("[ai] learning for %d epochs ..." % epochs_per_episode)
                        try:
                            self.set_training(True, epochs_per_episode)
                            self._model.learn(total_timesteps=epochs_per_episode, callback=self.on_ai_training_step)
                        finally:
                            self.set_training(False)
                            obs = self._model.env.reset()

                    elif obs is None:
                        obs = self._model.env.reset()

                    action, _ = self._model.predict(obs)
                    obs, _, _, _ = self._model.env.step(action)
                except Exception as e:
                    logging.exception("[ai] error during AI step (%s)", e)
                    obs = None
                    time.sleep(1)
