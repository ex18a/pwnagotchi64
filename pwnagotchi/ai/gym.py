import logging
import gymnasium as gym
from gymnasium import spaces
import numpy as np

import pwnagotchi.ai.featurizer as featurizer
import pwnagotchi.ai.reward as reward
from pwnagotchi.ai.parameter import Parameter


class Environment(gym.Env):
    metadata = {'render.modes': ['human']}
    # Ranges narrowed from evilsocket's original general-purpose values to
    # bracket what actually worked well during real walking-speed field
    # testing (see git history), rather than the wide, stationary-use
    # ranges upstream ships with. With as little training data as this
    # device sees, a search space that includes clearly-bad-for-walking
    # extremes (e.g. multi-minute TTLs, 90s recon windows) mostly just
    # slows down converging on values that fit the actual use case.
    params = [
        Parameter('min_rssi', min_value=-200, max_value=-50),
        # 15-600 -> 15-180: a multi-minute memory of a station/AP makes
        # little sense while continuously moving into new coverage areas
        Parameter('ap_ttl', min_value=15, max_value=180),
        Parameter('sta_ttl', min_value=15, max_value=180),

        # widened back to evilsocket's original 5-90 -- narrowing this to
        # 10-45 earlier capped hop_recon_time/recon_time well below what
        # actually worked before: real handshake-conversion data compared
        # July 7 (avg hop_recon_time ~47s, ~33% deauth-to-handshake
        # conversion) against a walking session under the narrowed range
        # (avg ~28s, ~6% conversion) -- the AI simply wasn't allowed to
        # wait long enough for a handshake to land before hopping away.
        # Full range restored so it can learn that longer dwell times pay
        # off when they do, instead of being capped below the values that
        # were already confirmed to work well.
        Parameter('recon_time', min_value=5, max_value=90),
        Parameter('max_inactive_scale', min_value=3, max_value=10),
        # 1-5 -> 1-3 (back to evilsocket's original): a large multiplier
        # means waiting even longer in a dead zone, which just wastes
        # more of a walk that's already producing nothing
        Parameter('recon_inactive_multiplier', min_value=1, max_value=3),
        # see recon_time above -- same reasoning, same data
        Parameter('hop_recon_time', min_value=5, max_value=90),
        Parameter('min_recon_time', min_value=1, max_value=30),
        Parameter('max_interactions', min_value=1, max_value=25),
        Parameter('max_misses_for_recon', min_value=3, max_value=10),
        Parameter('excited_num_epochs', min_value=5, max_value=30),
        Parameter('bored_num_epochs', min_value=5, max_value=30),
        Parameter('sad_num_epochs', min_value=5, max_value=30),
    ]

    def __init__(self, agent, epoch):
        super(Environment, self).__init__()
        self._agent = agent
        self._epoch = epoch
        self._epoch_num = 0
        self._last_render = None

        self._supported_channels = agent.supported_channels()
        self._extended_spectrum = any(ch > 140 for ch in self._supported_channels)
        self._histogram_size, self._observation_shape = featurizer.describe(self._extended_spectrum)

        # instance attribute, not Environment.params -- that's a shared
        # class-level list, and appending the per-device channel params to
        # it in-place would duplicate (or, if supported_channels() came back
        # empty due to the interface not being up yet, permanently omit) them
        # on every subsequent Environment() constructed in the same process
        self.params = Environment.params + [
            Parameter('_channel_%d' % ch, min_value=0, max_value=1, meta=ch + 1) for ch in
            range(self._histogram_size) if ch + 1 in self._supported_channels
        ]

        self.last = {
            'reward': 0.0,
            'observation': None,
            'policy': None,
            'params': {},
            'state': None,
            'state_v': None
        }

        self.action_space = spaces.MultiDiscrete([p.space_size() for p in self.params if p.trainable])
        self.observation_space = spaces.Box(low=0, high=1, shape=self._observation_shape, dtype=np.float32)
        self.reward_range = reward.range

    def policy_size(self):
        return len(list(p for p in self.params if p.trainable))

    def policy_to_params(self, policy):
        num = len(policy)
        params = {}

        assert len(self.params) == num

        channels = []

        for i in range(num):
            param = self.params[i]

            if '_channel' not in param.name:
                params[param.name] = param.to_param_value(policy[i])
            else:
                has_chan = param.to_param_value(policy[i])
                chan = param.meta
                if has_chan:
                    channels.append(chan)

        params['channels'] = channels
        return params

    def _next_epoch(self):
        logging.debug("[ai] waiting for epoch to finish ...")
        return self._epoch.wait_for_epoch_data()

    def _apply_policy(self, policy):
        new_params = self.policy_to_params(policy)
        self.last['policy'] = policy
        self.last['params'] = new_params
        self._agent.on_ai_policy(new_params)

    def step(self, policy):
        self._apply_policy(policy)
        self._epoch_num += 1

        state = self._next_epoch()

        self.last['reward'] = state['reward']
        self.last['state'] = state
        self.last['state_v'] = featurizer.featurize(state, self._epoch_num)

        self._agent.on_ai_step()

        # Gymnasium format: observation, reward, terminated, truncated, info
        terminated = not self._agent.is_training()
        truncated = False
        return self.last['state_v'], self.last['reward'], terminated, truncated, {}

    def reset(self, seed=None, options=None):
        # Gymnasium expects seed routing
        super().reset(seed=seed)
        self._epoch_num = 0
        state = self._next_epoch()
        self.last['state'] = state
        self.last['state_v'] = featurizer.featurize(state, 1)
        
        # Gymnasium format: observation, info
        return self.last['state_v'], {}

    def _render_histogram(self, hist):
        for ch in range(self._histogram_size):
            if hist[ch]:
                logging.info("      CH %d: %s" % (ch + 1, hist[ch]))

    def render(self, mode='human', close=False, force=False):
        if self._last_render == self._epoch_num:
            return

        if not self._agent.is_training() and not force:
            return

        self._last_render = self._epoch_num

        logging.info("[ai] --- training epoch %d/%d ---" % (self._epoch_num, self._agent.training_epochs()))
        logging.info("[ai] REWARD: %f" % self.last['reward'])
        logging.debug("[ai] policy: %s" % ', '.join("%s:%s" % (name, value) for name, value in self.last['params'].items()))
        logging.info("[ai] observation:")
        for name, value in self.last['state'].items():
            if 'histogram' in name:
                logging.info("    %s" % name.replace('_histogram', ''))
                self._render_histogram(value)
