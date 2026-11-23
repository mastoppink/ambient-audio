"""Membunyikan daftar event menjadi audio stereo, per lapisan."""
import numpy as np

import config
from synth import pad_voice, bell_voice, texture

SR = config.SAMPLE_RATE
LAYERS = {
    "drone": (config.DRONE, config.DRONE_LEVEL),
    "pad": (config.PAD, config.PAD_LEVEL),
}


def render_layers(events, total, rng):
    """-> dict nama_lapisan -> array (n, 2), belum ada efek."""
    n = int(total * SR)
    out = {}
    for e in events:
        buf = out.setdefault(e.layer, np.zeros((n, 2)))
        if e.layer == "melody":
            p = config.MELODY
            x = bell_voice(e.midi, e.dur, rng, p["attack"], p["decay"],
                           pan=rng.uniform(0.2, 0.8)) * p["level"]
        else:
            params, level = LAYERS[e.layer]
            if e.layer == "pad":
                # crossfade: release chord lama berjalan selama chord baru masuk
                params = dict(params, attack=config.CHORD_OVERLAP, release=config.CHORD_OVERLAP)
            x = pad_voice(e.midi, e.dur, rng, params) * level
        s = int(e.start * SR)
        k = min(len(x), n - s)
        buf[s:s + k] += x[:k]
    return out


def render_events(events, total, rng):
    """Mix kering semua lapisan (dipakai milestone 2)."""
    return sum(render_layers(events, total, rng).values())


def render_texture(total, rng):
    x = texture(total, rng, config.TEXTURE) * config.TEXTURE["level"]
    fade = int(20 * SR)
    x[:fade] *= np.linspace(0, 1, fade)[:, None]
    return x
