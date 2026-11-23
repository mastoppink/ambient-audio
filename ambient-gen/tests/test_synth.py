import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
import config
from synth import pad_voice


def test_pad_basic():
    rng = np.random.default_rng(1)
    x = pad_voice(50, 5.0, rng, {**config.PAD, "attack": 1.0, "release": 1.0})
    assert x.shape == (5 * config.SAMPLE_RATE, 2)
    assert np.all(np.isfinite(x))
    assert abs(x[0]).max() < 1e-3 and abs(x[-1]).max() < 1e-3  # mulai/akhir senyap


def test_deterministic():
    a = pad_voice(50, 1.0, np.random.default_rng(7), config.PAD)
    b = pad_voice(50, 1.0, np.random.default_rng(7), config.PAD)
    assert np.array_equal(a, b)
