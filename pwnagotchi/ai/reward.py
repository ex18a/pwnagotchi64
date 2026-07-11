import pwnagotchi.mesh.wifi as wifi

range = (-.7, 1.22)
fuck_zero = 1e-20


class RewardFunction(object):
    def __call__(self, epoch_n, state):
        tot_epochs = epoch_n + fuck_zero
        tot_interactions = max(state['num_deauths'] + state['num_associations'], state['num_handshakes']) + fuck_zero
        h = state['num_handshakes'] / tot_interactions
        a = .2 * (state['active_for_epochs'] / tot_epochs)
        # a channel-hop-count reward term used to live here, rewarding more
        # hops per epoch -- meaningful in the original design, where
        # do_auto_mode() attacks every channel a scan turns up in one
        # epoch, so num_hops varies a lot. This fork's do_auto_mode()
        # only ever attacks the single busiest channel per epoch (see
        # bin/pwnagotchi), so num_hops collapsed to essentially always 0
        # or 1 -- contributing almost no real learning signal, just noise.
        b = -.3 * (state['blind_for_epochs'] / tot_epochs)
        m = -.3 * (state['missed_interactions'] / tot_interactions)
        i = -.2 * (state['inactive_for_epochs'] / tot_epochs)
        # include emotions if state >= 5 epochs
        _sad = state['sad_for_epochs'] if state['sad_for_epochs'] >= 5 else 0
        _bored = state['bored_for_epochs'] if state['bored_for_epochs'] >= 5 else 0
        # mirror of _sad/_bored on the positive side
        _excited = state['active_for_epochs'] if state['active_for_epochs'] >= 5 else 0
        s = -.2 * (_sad / tot_epochs)
        l = -.1 * (_bored / tot_epochs)
        e = .2 * (_excited / tot_epochs)
        return h + a + b + i + m + s + l + e
