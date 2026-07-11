import os
import time
import logging
def load(config, agent, epoch, from_disk=True):
    config = config['ai']
    if not config['enabled']:
        logging.info("ai disabled")
        return False
    try:
        begin = time.time()
        logging.info("[ai] bootstrapping PyTorch dependencies ...")
        start = time.time()
        from stable_baselines3 import A2C
        logging.debug("[ai] A2C imported in %.2fs" % (time.time() - start))
        start = time.time()
        from stable_baselines3.common.vec_env import DummyVecEnv
        logging.debug("[ai] DummyVecEnv imported in %.2fs" % (time.time() - start))
        start = time.time()
        import pwnagotchi.ai.gym as wrappers
        logging.debug("[ai] gym wrapper imported in %.2fs" % (time.time() - start))
        env = wrappers.Environment(agent, epoch)
        env = DummyVecEnv([lambda: env])
        logging.info("[ai] creating model ...")
        start = time.time()
        a2c = A2C("MlpPolicy", env, **config['params'])
        logging.debug("[ai] A2C created in %.2fs" % (time.time() - start))
        if from_disk and os.path.exists(config['path']):
            logging.info("[ai] loading %s ..." % config['path'])
            start = time.time()
            try:
                a2c = A2C.load(config['path'], env=env)
                logging.debug("[ai] A2C loaded in %.2fs" % (time.time() - start))
            except ValueError as e:
                if "do not match" not in str(e):
                    raise
                # a2c already holds the freshly-created model from a few
                # lines above (env, **config['params']) -- leave it as
                # that and move the incompatible saved file out of the
                # way, rather than raising and letting AsyncTrainer's
                # retry loop retry an identical load 5 times. That retry
                # logic exists for genuinely transient failures (e.g. the
                # channel list being empty for a moment right after
                # boot); this is not one -- it's a permanent, structural
                # mismatch between the saved model's action/observation
                # space and gym.py's current Parameter definitions (a
                # min/max range changed, or a parameter was added or
                # removed), and retrying the exact same load will fail
                # identically every time, no matter how many attempts.
                # SB3's own check_for_correct_spaces() raises exactly
                # this ValueError, with "... do not match: ..." in the
                # message, which is what's matched on above. Confirmed
                # via a real crash: this is the same failure mode as the
                # "Action spaces do not match" crash fixed in agent.py's
                # supported_channels() -- same underlying cause class,
                # just triggered by a code change instead of a boot-time
                # race.
                logging.warning("[ai] %s -- saved model is incompatible with the current "
                                 "action/observation space, starting a fresh one instead" % e)
                backup_path = config['path'] + ".incompatible"
                try:
                    os.replace(config['path'], backup_path)
                    logging.info("[ai] backed up incompatible model to %s" % backup_path)
                except Exception as backup_err:
                    logging.error("[ai] failed to back up incompatible model: %s" % backup_err)
        else:
            logging.info("[ai] new model created:")
            for key, value in config['params'].items():
                logging.info("      %s: %s" % (key, value))
        logging.debug("[ai] total loading time is %.2fs" % (time.time() - begin))
        return a2c
    except Exception as e:
        logging.exception("error while starting AI (%s)", e)
    logging.warning("[ai] AI not loaded!")
    return False
