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
                # a clean load proves the saved model is compatible right
                # now, so any mismatch noted on a previous boot was
                # transient after all -- clear it rather than letting it
                # sit around and wrongly count as "confirmed twice" against
                # some unrelated mismatch much later
                pending_path = config['path'] + '.mismatch-pending'
                if os.path.exists(pending_path):
                    try:
                        os.remove(pending_path)
                    except Exception:
                        pass
            except ValueError as e:
                if "do not match" not in str(e):
                    raise
                # SB3's own check_for_correct_spaces() raises exactly this
                # ValueError, with "... do not match: ..." in the message,
                # whenever the env's action/observation space doesn't match
                # the saved model's. Two different causes look identical
                # here, and confirmed on-device that BOTH really happen:
                #
                # 1. A genuine, permanent structural change (a gym.py
                #    Parameter's min/max range changed, or one was added/
                #    removed) -- retrying the exact same load will fail
                #    identically every time, no matter how many attempts,
                #    so there's no point keeping the old model around.
                #
                # 2. A transient boot-time race: supported_channels() came
                #    back empty because mon0/bettercap hadn't finished
                #    coming up yet at the exact instant this env was built,
                #    so the action space is missing all its per-channel
                #    dimensions -- confirmed on-device this can take well
                #    over a minute after a rapid string of restarts, not
                #    just "a moment". Wrongly treating this as case 1
                #    destroys a perfectly good, previously-trained model
                #    for no reason other than bad timing.
                #
                # Only agent.supported_channels() being empty right now can
                # actually tell these apart. If it's empty, don't touch the
                # saved model at all -- return False so AsyncTrainer's own
                # retry loop (train.py, built for exactly this) tries again
                # once channels are actually known, instead of silently
                # "succeeding" with a fresh model on the very first attempt
                # and never giving that retry loop a chance to run.
                if not agent.supported_channels():
                    logging.warning("[ai] %s -- supported_channels() is currently empty (mon0/bettercap "
                                     "likely still coming up), deferring judgment instead of discarding "
                                     "the saved model" % e)
                    return False
                # Channels are confirmed known, so this really does look like
                # a genuine, permanent structural change -- but a single
                # occurrence still isn't proof, since anything we haven't
                # already anticipated (an odd race, a weird bettercap state)
                # could in principle produce the same symptom once. Discarding
                # a trained model is expensive and can't be undone, so require
                # this to reproduce across an actual restart (a fresh process,
                # fresh bettercap connection, fresh channel query) before ever
                # acting on it -- a persistent marker (survives even a full
                # reboot, not just a service restart) records the first
                # occurrence, and only the second one within a restart of it
                # actually discards.
                pending_path = config['path'] + '.mismatch-pending'
                if not os.path.exists(pending_path):
                    try:
                        with open(pending_path, 'w') as fp:
                            fp.write(str(e))
                    except Exception as marker_err:
                        logging.error("[ai] failed to write mismatch marker: %s" % marker_err)
                    logging.warning("[ai] %s -- channels are known but the saved model still doesn't "
                                     "match; noting this and waiting to see if it reproduces after a "
                                     "restart before touching brain.nn" % e)
                    return False
                # a2c already holds the freshly-created model from a few
                # lines above (env, **config['params']) -- leave it as
                # that and move the incompatible saved file out of the way,
                # into the same brain-backups folder everything else lands
                # in (train.py's periodic rolling/permanent snapshots)
                # rather than cluttering the directory brain.nn itself
                # lives in.
                logging.warning("[ai] %s -- saved model is incompatible with the current "
                                 "action/observation space (confirmed again after a restart), starting "
                                 "a fresh one instead" % e)
                backup_dir = os.path.join(os.path.dirname(config['path']), 'brain-backups', 'incompatible')
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                except Exception as mkdir_err:
                    logging.error("[ai] failed to create incompatible-backup dir: %s" % mkdir_err)
                backup_path = os.path.join(backup_dir, os.path.basename(config['path']) + ".incompatible")
                try:
                    os.replace(config['path'], backup_path)
                    logging.info("[ai] backed up incompatible model to %s" % backup_path)
                except Exception as backup_err:
                    logging.error("[ai] failed to back up incompatible model: %s" % backup_err)
                # brain.json (Stats: born_at/epochs_lived/epochs_trained/
                # best_reward/worst_reward) belongs to the model being
                # replaced, not the fresh one -- if it's left in place, the
                # fresh model's counters would misleadingly carry on from the
                # old one's. Back it up rather than deleting outright, same
                # as brain.nn itself, so both can be restored together if
                # this ever turns out to have been the wrong call after all.
                json_path = os.path.splitext(config['path'])[0] + '.json'
                if os.path.exists(json_path):
                    json_backup_path = os.path.join(backup_dir, os.path.basename(json_path) + ".incompatible")
                    try:
                        os.replace(json_path, json_backup_path)
                        logging.info("[ai] backed up incompatible stats to %s" % json_backup_path)
                    except Exception as json_backup_err:
                        logging.error("[ai] failed to back up incompatible stats: %s" % json_backup_err)
                try:
                    os.remove(pending_path)
                except Exception:
                    pass
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
