import numpy as np

import fx

SR = fx.SR


def test_comfort_segment_invariant():
    x = np.random.default_rng(0).standard_normal((SR * 3, 2)) * 0.05
    a = fx.Comfort(0.6, 12, 0.8, np.random.default_rng(1))(x)
    c = fx.Comfort(0.6, 12, 0.8, np.random.default_rng(1))
    b = np.concatenate([c(x[:7777]), c(x[7777:])])
    assert np.abs(a - b).max() < 1e-12


def test_tame_reduces_sharp_burst_only():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((SR * 8, 2)) * 0.05
    y = x.copy()
    n = np.arange(SR // 2)
    y[5 * SR:5 * SR + SR // 2] += (0.3 * np.sin(2 * np.pi * 4000 * n / SR) * np.exp(-n / SR * 6))[:, None]
    o = fx.Comfort(0, 14, 1.0, np.random.default_rng(1))(y)
    seg = slice(5 * SR, 5 * SR + SR // 10)
    assert np.std(o[seg]) < np.std(y[seg]) * 0.8          # denting diredam
    steady = slice(2 * SR, 4 * SR)
    assert abs(np.std(o[steady]) / np.std(y[steady]) - 1) < 0.01   # bagian tenang tidak berubah


def test_off_is_bypass():
    x = np.random.default_rng(0).standard_normal((1000, 2))
    assert fx.Comfort(0, 14, 0, np.random.default_rng(1))(x) is x
