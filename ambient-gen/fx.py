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


# ---------- versi streaming (milestone 4): state dibawa antar potongan ----------
class StreamReverb:
    """Reverb konvolusi overlap-add: ekor dari potongan sebelumnya dibawa ke berikutnya."""

    def __init__(self, ir):
        self.ir = ir
        self.tail = np.zeros((len(ir) - 1, 2))

    def __call__(self, x):
        n = len(x)
        y = np.stack([oaconvolve(x[:, c], self.ir[:, c]) for c in range(2)], axis=1)
        k = min(n, len(self.tail))
        y[:k] += self.tail[:k]
        rest = self.tail[k:]
        new_tail = y[n:].copy()
        if len(rest):
            new_tail[: len(rest)] += rest
        self.tail = new_tail
        return y[:n]


class StreamBoard:
    """Pedalboard yang dipanggil per potongan tanpa reset state (chorus, delay)."""

    def __init__(self, board):
        self.board = board

    def __call__(self, x):
        return self.board(x.T.astype(np.float32), SR, reset=False).T.astype(np.float64)


def stream_chorus():
    return StreamBoard(Pedalboard([Chorus(rate_hz=0.12, depth=0.15, centre_delay_ms=9,
                                          feedback=0.0, mix=0.35)]))


def stream_delay(p):
    return StreamBoard(Pedalboard([Delay(delay_seconds=p["delay_seconds"],
                                         feedback=p["delay_feedback"], mix=p["delay_mix"])]))


class StreamHighpass:
    def __init__(self, fc=30.0):
        self.sos = butter(2, fc, btype="high", fs=SR, output="sos")
        self.zi = np.zeros((self.sos.shape[0], 2, 2))

    def __call__(self, x):
        y, self.zi = sosfilt(self.sos, x, axis=0, zi=self.zi)
        return y


class StreamLimiter:
    """Sama dengan limiter(), tapi per potongan. Membutuhkan `ahead` sampel dari potongan
    berikutnya (lookahead), jadi keluaran tertunda: panggil push() lalu flush() di akhir."""

    def __init__(self, ceiling_db=-1.0, lookahead=0.005, release=0.25):
        from scipy.ndimage import maximum_filter1d, uniform_filter1d
        self.mf, self.uf = maximum_filter1d, uniform_filter1d
        self.c = 10 ** (ceiling_db / 20)
        self.la = max(1, int(lookahead * SR))
        self.coef = np.exp(-1 / (release * 1000))
        self.hop = SR // 1000
        self.cur = 0.0
        self.buf = np.zeros((0, 2))
        self.prev = np.zeros((2 * self.la, 2))   # konteks masa lalu untuk filter berjendela

    def _process(self, body, future):
        ctx = np.vstack([self.prev, body, future])
        peak = self.mf(np.abs(ctx).max(axis=1), size=2 * self.la + 1)
        g = np.minimum(1.0, self.c / np.maximum(peak, 1e-9))
        p0 = len(self.prev)
        gb = g[p0:p0 + len(body)]
        r = 1 - gb[:: self.hop]
        env = np.empty_like(r)
        cur = self.cur
        for i, v in enumerate(r):
            cur = v if v > cur else cur * self.coef
            env[i] = cur
        self.cur = cur
        g[p0:p0 + len(body)] = np.minimum(gb, 1 - np.repeat(env, self.hop)[: len(body)])
        g = self.uf(g, size=self.la)
        out = np.clip(body * g[p0:p0 + len(body), None], -self.c, self.c)
        self.prev = np.vstack([self.prev, body])[-2 * self.la:]
        return out

    def push(self, x):
        self.buf = np.vstack([self.buf, x])
        keep = 2 * self.la
        n = (len(self.buf) - keep) // self.hop * self.hop
        if n <= 0:
            return np.zeros((0, 2))
        body, self.buf = self.buf[:n], self.buf[n:]
        return self._process(body, self.buf[:keep])

    def flush(self):
        body, self.buf = self.buf, np.zeros((0, 2))
        return self._process(body, np.zeros((0, 2))) if len(body) else body
