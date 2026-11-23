import numpy as np
from scipy.signal import hilbert
import fx

SR = 48000


def _sine(f, sec, amp=0.2):
    t = np.arange(int(SR * sec)) / SR
    return np.stack([np.sin(2 * np.pi * f * t) * amp] * 2, axis=1)


def test_saturation_adds_gentle_harmonics_and_scales_with_amount():
    def h2(a):
        w = fx.Warmth(a, 0, 0, np.random.default_rng(1)); w.tone = None
        y = w(_sine(220, 4))[SR * 2:, 0]
        Y = np.abs(np.fft.rfft(y * np.hanning(len(y)))); f = np.fft.rfftfreq(len(y), 1 / SR)
        return 20 * np.log10(Y[np.argmin(abs(f - 440))] / Y[np.argmin(abs(f - 220))])
    assert h2(0.3) < h2(1.0) < -30          # makin hangat makin banyak harmonik, tetap halus


def test_zero_warmth_is_transparent():
    x = np.random.default_rng(2).standard_normal((SR, 2)) * 0.1
    w = fx.Warmth(0, 0, 0, np.random.default_rng(1))
    assert np.array_equal(w(x), x)


def test_wow_depth_in_cents():
    w = fx.Warmth(0, 1.0, 0, np.random.default_rng(2))
    y = w(_sine(1000, 20))[SR:, 0]
    fi = np.diff(np.unwrap(np.angle(hilbert(y)))) * SR / (2 * np.pi)
    c = 1200 * np.log2(np.convolve(fi, np.ones(480) / 480, mode="valid")[2000:-2000] / 1000)
    assert 2.0 < c.max() < 4.0 and -4.0 < c.min() < -2.0


def test_chunking_invariant():
    x = np.random.default_rng(5).standard_normal((SR * 3, 2)) * 0.1
    a = fx.Warmth(0.6, 0.6, 0, np.random.default_rng(7))
    b = fx.Warmth(0.6, 0.6, 0, np.random.default_rng(7))
    ya = np.vstack([a(x[i:i + 9999]) for i in range(0, len(x), 9999)])
    yb = np.vstack([b(x[i:i + 40000]) for i in range(0, len(x), 40000)])
    assert np.abs(ya - yb).max() < 1e-9
