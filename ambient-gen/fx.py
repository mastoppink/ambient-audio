"""Rantai efek: chorus, delay, reverb konvolusi, limiter."""
import numpy as np
from pedalboard import Pedalboard, Chorus, Delay, HighpassFilter
from scipy.signal import oaconvolve, butter, sosfilt

import config

SR = config.SAMPLE_RATE


def make_ir(decay, predelay, rng, hp=180.0):
    """IR reverb sintetis: noise stereo dengan decay eksponensial yang makin gelap.

    Freeverb bawaan pedalboard tidak bisa mencapai decay 8-15 detik dengan halus,
    jadi dipakai konvolusi dengan IR buatan sendiri.
    """
    n = int((decay * 1.2 + predelay) * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal((n, 2))
    # frekuensi tinggi meluruh lebih cepat: campur noise terang (decay pendek) + gelap
    dark = sosfilt(butter(2, 2500, fs=SR, output="sos"), ir, axis=0)
    env_long = 10 ** (-3 * t / decay)          # -60 dB pada t = decay
    env_short = 10 ** (-3 * t / (decay * 0.35))
    ir = dark * env_long[:, None] + 0.4 * (ir - dark) * env_short[:, None]
    fade_in = int(0.08 * SR)                    # onset lembut, tanpa "klik" awal
    ir[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    ir = np.vstack([np.zeros((int(predelay * SR), 2)), ir])
    ir = sosfilt(butter(2, hp, btype="high", fs=SR, output="sos"), ir, axis=0)
    return ir / np.sqrt((ir**2).sum(axis=0, keepdims=True))


def reverb(x, ir):
    return np.stack([oaconvolve(x[:, c], ir[:, c])[: len(x)] for c in range(2)], axis=1)


def _board(board, x):
    return board(x.T.astype(np.float32), SR).T.astype(np.float64)


def chorus(x):
    return _board(Pedalboard([Chorus(rate_hz=0.12, depth=0.15, centre_delay_ms=9, feedback=0.0, mix=0.35)]), x)


def delay(x, p):
    return _board(Pedalboard([Delay(delay_seconds=p["delay_seconds"], feedback=p["delay_feedback"],
                                    mix=p["delay_mix"])]), x)


def limiter(x, ceiling_db=-1.0, lookahead=0.005, release=0.25):
    """Limiter lookahead sederhana. Tanpa makeup gain (Limiter pedalboard menaikkan level
    sendiri sehingga loudness meleset)."""
    from scipy.ndimage import maximum_filter1d, uniform_filter1d
    c = 10 ** (ceiling_db / 20)
    la = max(1, int(lookahead * SR))
    peak = maximum_filter1d(np.abs(x).max(axis=1), size=2 * la + 1)
    g = np.minimum(1.0, c / np.maximum(peak, 1e-9))
    # release: reduksi gain ditahan lalu meluruh pelan (dihitung per 1 ms)
    hop = SR // 1000
    r = 1 - g[::hop]
    coef = np.exp(-1 / (release * 1000))
    env = np.empty_like(r)
    cur = 0.0
    for i, v in enumerate(r):
        cur = v if v > cur else cur * coef
        env[i] = cur
    g = np.minimum(g, 1 - np.repeat(env, hop)[: len(g)])
    g = uniform_filter1d(g, size=la)  # haluskan transisi
    return np.clip(x * g[:, None], -c, c)


def master(x, p):
    import pyloudnorm as pyln
    x = _board(Pedalboard([HighpassFilter(30.0)]), x)
    meter = pyln.Meter(SR)
    for _ in range(3):  # limiter mengubah loudness sedikit; ulangi sampai pas
        x = x * 10 ** ((p["target_lufs"] - meter.integrated_loudness(x)) / 20)
        x = limiter(x, p["ceiling_db"])
    return x, meter.integrated_loudness(x)
