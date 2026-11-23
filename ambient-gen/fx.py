"""Rantai efek: chorus, delay, reverb konvolusi, limiter."""
import numpy as np
from pedalboard import Pedalboard, Chorus, Delay, HighpassFilter
from scipy.signal import oaconvolve, butter, sosfilt

import config

SR = config.SAMPLE_RATE


def make_ir(decay, predelay, rng, hp=180.0, early=0.5, width=1.0):
    """IR reverb sintetis.

    - Pantulan awal (early reflections): 14 pantulan 8-80 ms, beda posisi L/R -> kesan ruang.
    - Ekor difus: noise dengan decay berbeda per pita frekuensi (bass sedikit lebih pendek supaya tidak menumpuk,
      treble jauh lebih cepat, seperti ruang nyata), muncul bertahap (build-up 120 ms).
    - Kanal L/R tidak berkorelasi -> stereo lebar. width < 1 mempersempit.
    """
    n = int((decay * 1.25 + predelay) * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal((n, 2))
    # pecah noise jadi 4 pita, masing-masing dengan waktu decay sendiri
    edges = [(None, 300, 0.9), (300, 2000, 1.0), (2000, 6000, 0.55), (6000, None, 0.28)]
    tail = np.zeros_like(noise)
    for lo, hi, k in edges:
        if lo is None:
            sos = butter(4, hi, btype="low", fs=SR, output="sos")
        elif hi is None:
            sos = butter(4, lo, btype="high", fs=SR, output="sos")
        else:
            sos = butter(2, [lo, hi], btype="band", fs=SR, output="sos")
        env = 10 ** (-3 * t / (decay * k))       # -60 dB pada t = decay*k
        tail += sosfilt(sos, noise, axis=0) * env[:, None]
    build = int(0.12 * SR)
    tail[:build] *= (np.sin(np.linspace(0, np.pi / 2, build)) ** 2)[:, None]
    tail /= np.sqrt((tail**2).sum(axis=0, keepdims=True))
    # pantulan awal
    er = np.zeros((int(0.09 * SR), 2))
    for i in range(14):
        d = rng.uniform(0.008, 0.08)
        g = 0.9 * (1 - d / 0.09) * rng.uniform(0.5, 1.0)
        pan = rng.uniform(0.1, 0.9)
        j = int(d * SR)
        er[j, 0] += g * np.cos(pan * np.pi / 2)
        er[j, 1] += g * np.sin(pan * np.pi / 2)
    er = sosfilt(butter(1, 5000, fs=SR, output="sos"), er, axis=0)
    er *= early / (np.sqrt((er**2).sum()) + 1e-12)
    ir = tail.copy()
    ir[: len(er)] += er
    if width < 1.0:   # campur sebagian kanal -> lebih sempit
        m = ir.mean(axis=1, keepdims=True)
        ir = m + (ir - m) * width
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


# ---------- EQ (biquad RBJ) per lapisan, streaming ----------
def _rbj(kind, f, gain_db=0.0, q=0.7071):
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f / SR
    cw, sw = np.cos(w0), np.sin(w0)
    al = sw / (2 * q)
    if kind == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + al, -2 * cw, 1 - al]
    elif kind == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + al, -2 * cw, 1 - al]
    elif kind == "peak":
        b = [1 + al * A, -2 * cw, 1 - al * A]
        a = [1 + al / A, -2 * cw, 1 - al / A]
    elif kind in ("lowshelf", "highshelf"):
        s = 2 * np.sqrt(A) * al
        if kind == "lowshelf":
            b = [A * ((A + 1) - (A - 1) * cw + s), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - s)]
            a = [(A + 1) + (A - 1) * cw + s, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - s]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + s), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - s)]
            a = [(A + 1) - (A - 1) * cw + s, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - s]
    else:
        raise ValueError(kind)
    b, a = np.array(b) / a[0], np.array(a) / a[0]
    return np.concatenate([b, a])


class StreamEQ:
    """bands: daftar (jenis, frekuensi, gain_db, q). Jenis: hp, lp, peak, lowshelf, highshelf."""

    def __init__(self, bands):
        self.sos = np.array([_rbj(k, f, g, q) for k, f, g, q in bands]) if bands else None
        self.zi = np.zeros((len(bands), 2, 2)) if bands else None

    def __call__(self, x):
        if self.sos is None:
            return x
        y, self.zi = sosfilt(self.sos, x, axis=0, zi=self.zi)
        return y


class OctaveUp:
    """Pitch shifter delay-line (2 tap bersilang, jendela sin^2), rasio 2 = +12 semitone.
    Streaming dan deterministik. Kualitasnya sederhana, tapi cukup untuk shimmer di dalam reverb."""

    def __init__(self, ratio=2.0, window=0.06):
        self.r = ratio
        self.D = int(window * SR)
        self.hist = np.zeros((self.D + 2, 2))
        self.n0 = 0

    def __call__(self, x):
        n = len(x)
        buf = np.vstack([self.hist, x])
        H = len(self.hist)
        idx = self.n0 + np.arange(n)
        y = np.zeros_like(x)
        for k in (0.0, 0.5):
            ph = ((self.r - 1) * idx / self.D + k) % 1.0
            d = (1 - ph) * self.D                 # jarak baca ke belakang
            pos = H + np.arange(n) - d - 1
            i = np.floor(pos).astype(int)
            fr = (pos - i)[:, None]
            w = np.sin(np.pi * ph) ** 2
            y += (buf[i] * (1 - fr) + buf[i + 1] * fr) * w[:, None]
        self.hist = buf[-H:]
        self.n0 += n
        return y


def stream_wet_chorus():
    """Modulasi pelan pada ekor reverb (konvolusi sendiri statis) -> ekor terasa hidup."""
    return StreamBoard(Pedalboard([Chorus(rate_hz=0.07, depth=0.25, centre_delay_ms=14,
                                          feedback=0.0, mix=0.5)]))
