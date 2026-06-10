import _thread
import threading
import time
import random
import os
import json
import logging

import pwnagotchi.plugins as plugins
import pwnagotchi.ai as ai


class Stats(object):
    def __init__(self, path, events_receiver):
        self.path = path
        self.receiver = events_receiver
        self.born_at = time.time()
        self.epochs_lived = 0
        self.epochs_trained = 0
        self.episodes_completed = 0
        self.worst_reward = 0.0
        self.best_reward = 0.0

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'rt') as fp:
                    data = json.load(fp)
                    self.born_at = data['born_at']
                    self.epochs_lived = data['epochs_lived']
                    self.epochs_trained = data['epochs_trained']
                    self.episodes_completed = data['episodes_completed']
                    self.worst_reward = data['rewards']['worst']
                    self.best_reward = data['rewards']['best']
            except Exception as e:
                logging.warning("error while loading %s: %s" % (self.path, e))

    def save(self):
        try:
            with open(self.path, 'wt') as fp:
                json.dump({
                    'born_at': self.born_at,
                    'epochs_lived': self.epochs_lived,
                    'epochs_trained': self.epochs_trained,
                    'episodes_completed': self.episodes_completed,
                    'rewards': {
                        'best': self.best_reward,
                        'worst': self.worst_reward
                    }
                }, fp)
        except Exception as e:
            logging.warning("error while saving %s: %s" % (self.path, e))

    def on_epoch(self, data, training):
        self.epochs_lived += 1
        if training:
            self.epochs_trained += 1
            if self.epochs_trained % 50 == 0:
                self.episodes_completed += 1

        reward = data['reward']
        if reward > self.best_reward:
            self.best_reward = reward
        elif reward < self.worst_reward:
            self.worst_reward = reward

        self.save()


class AsyncTrainer(object):
    def __init__(self, config):
        self._config = config
        self._model = None
        self._is_training = False
        self._training_epochs = 0
        self._nn_path = self._config['ai']['path']
        self._stats = Stats("%s.json" % os.path.splitext(self._nn_path)[0], self)

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

    def _save_ai(self):
        logging.info("[ai] saving model to %s ..." % self._nn_path)
        # Explicitly tell PyTorch to use .zip for the temp file
        temp = "%s.tmp.zip" % self._nn_path
        self._model.save(temp)
        # Safely overwrite the old brain with the new one
        os.replace(temp, "%s.zip" % self._nn_path)

    def on_ai_step(self):
        self._model.env.render()

        if self._is_training:
            self._save_ai()

        self._stats.on_epoch(self._epoch.data(), self._is_training)

    def on_ai_training_step(self, _locals, _globals):
        self._model.env.render()
        plugins.on('ai_training_step', self, _locals, _globals)

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
        self._model = ai.load(self._config, self, self._epoch)

        if self._model:
            self.on_ai_ready()

            epochs_per_episode = self._config['ai']['epochs_per_episode']

            obs = None
            while True:
                self._model.env.render()
                # enter in training mode?
                if random.random() > self._config['ai']['laziness']:
                    logging.info("[ai] learning for %d epochs ..." % epochs_per_episode)
                    try:
                        self.set_training(True, epochs_per_episode)
                        self._model.learn(total_timesteps=epochs_per_episode, callback=self.on_ai_training_step)
                    except Exception as e:
                        logging.exception("[ai] error while training (%s)", e)
                    finally:
                        self.set_training(False)
                        obs = self._model.env.reset()
                # init the first time
                elif obs is None:
                    obs = self._model.env.reset()

                # run the inference
                action, _ = self._model.predict(obs)
                obs, _, _, _ = self._model.env.step(action)
