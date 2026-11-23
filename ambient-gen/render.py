"""Membunyikan daftar event menjadi audio stereo."""
import numpy as np

import config
from synth import pad_voice

SR = config.SAMPLE_RATE
LAYERS = {
    "drone": (config.DRONE, config.DRONE_LEVEL),
    "pad": (config.PAD, config.PAD_LEVEL),
}


def render_events(events, total, rng):
    out = np.zeros((int(total * SR), 2))
    for e in events:
        params, level = LAYERS[e.layer]
        if e.layer == "pad":
            # crossfade: release chord lama berjalan selama chord baru masuk
            params = dict(params, attack=config.CHORD_OVERLAP, release=config.CHORD_OVERLAP)
        x = pad_voice(e.midi, e.dur, rng, params) * level
        s = int(e.start * SR)
        n = min(len(x), len(out) - s)
        out[s:s + n] += x[:n]
    return out
