import numpy as np
from scipy.signal import butter, sosfilt
import fx

SR = 48000


def _rt60(sig):
    e = np.cumsum((sig ** 2)[::-1])[::-1]
    db = 10 * np.log10(e / e[0] + 1e-30)
    return (np.argmax(db < -35) - np.argmax(db < -5)) / SR * 2


def _ir(decay, **kw):
    rv = fx.FDNReverb(decay, np.random.default_rng(1), **kw)
    x = np.zeros((int(SR * decay * 1.4), 2)); x[0] = 1
    return np.vstack([rv(x[i:i + SR]) for i in range(0, len(x), SR)])


def test_fdn_decay_time_and_treble_damping():
    ir = _ir(8.0)
    mid = _rt60(sosfilt(butter(4, [500, 2000], btype="band", fs=SR, output="sos"), ir[:, 0]))
    hi = _rt60(sosfilt(butter(4, [4000, 8000], btype="band", fs=SR, output="sos"), ir[:, 0]))
    assert 0.8 * 8 < mid < 1.15 * 8
    assert hi < 0.7 * mid            # treble meluruh lebih cepat


def test_fdn_normalized_and_wide():
    ir = _ir(6.0)
    e = (ir ** 2).sum(axis=0)
    assert np.all(np.abs(e - 1) < 0.1)                      # setara IR konvolusi (energi 1)
    assert abs(np.corrcoef(ir[:, 0], ir[:, 1])[0, 1]) < 0.2  # kiri/kanan tidak berkorelasi


def test_fdn_chunking_invariant():
    sig = np.random.default_rng(4).standard_normal((SR * 3, 2))
    a = fx.FDNReverb(5.0, np.random.default_rng(3), normalize=False)
    b = fx.FDNReverb(5.0, np.random.default_rng(3), normalize=False)
    ya = np.vstack([a(sig[i:i + 7777]) for i in range(0, len(sig), 7777)])
    yb = np.vstack([b(sig[i:i + 30000]) for i in range(0, len(sig), 30000)])
    assert np.abs(ya - yb).max() < 1e-9
