import numpy as np
import config
import settings
from compose import compose
from render import render_segment
from synth import cloud_segment

SR = 48000


def _setup(over=()):
    settings.apply(settings.resolve(settings.load("presets/nebula.toml", list(over)), 9))
    return compose(300, 9, with_melody=True)


def test_cloud_segments_equal_whole():
    ev = _setup()
    n = 40 * SR
    whole = render_segment(ev, 0, n, 9)["cloud"]
    seg = int(6.7 * SR)
    parts = np.vstack([render_segment(ev, s, min(seg, n - s), 9, i)["cloud"] for i, s in enumerate(range(0, n, seg))])
    assert np.abs(parts - whole).max() < 1e-6 and whole.std() > 0


def test_cloud_only_uses_chord_tones():
    _setup()
    p = dict(config.CLOUD, density=40.0)
    chords = [(0.0, 100.0, "I", [62, 66, 69])]     # D F# A saja
    x = cloud_segment(0.0, 10 * SR, 3, chords, p)[:, 0]
    X = np.abs(np.fft.rfft(x)); f = np.fft.rfftfreq(len(x), 1 / SR)
    peaks = f[np.argsort(X)[-40:]]
    pcs = {int(round(12 * np.log2(pk / 440) + 69)) % 12 for pk in peaks if 150 < pk < 5000}
    assert pcs <= {2, 6, 9}                          # hanya D, F#, A (dan oktafnya/harmoniknya)


def test_cloud_off_is_silent():
    ev = _setup(["mix.cloud=0"])
    assert not render_segment(ev, 0, 5 * SR, 9)["cloud"].any()
