"""Rantai efek: reverb konvolusi, chorus, delay, EQ, shimmer, limiter (streaming).

reverb() dan limiter() versi sekaligus dipertahankan sebagai pembanding di tes."""
import numpy as np
from pedalboard import Pedalboard, Chorus, Delay
from scipy.signal import oaconvolve, butter, sosfilt, lfilter

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


# ---------- reverb algoritmik: FDN 8 jalur dengan modulasi ----------
class FDNReverb:
    """Feedback Delay Network 8 jalur (jenis reverb hardware/plugin studio), streaming.

    - Difusi awal: 4 allpass berseri per kanal -> serangan nada tidak terdengar sebagai gema terpisah.
    - 8 delay line (panjang saling prima 29-97 ms x `size`) dicampur matriks Householder (ortogonal,
      energi terjaga) -> ekor padat dan halus.
    - Tiap delay line dibaca dengan posisi yang bergoyang pelan (LFO 0,07-0,5 Hz, kedalaman
      `mod_depth` ms) -> ekor berkilau dan bergerak, tidak statis seperti reverb konvolusi.
    - Peredam per jalur: treble meluruh lebih cepat (`hf_ratio` x RT60) seperti ruangan nyata.
    - Pantulan awal: FIR pendek (90 ms) seperti make_ir, dicampur dengan `early`.
    Diproses per blok yang lebih pendek dari delay line terpendek, jadi bisa vektor numpy.
    Keluaran dinormalkan ke energi impuls = 1 per kanal (setara IR konvolusi), supaya mix tidak berubah.
    """

    BASE_MS = (29.7, 37.1, 41.1, 43.7, 53.3, 61.9, 71.3, 97.1)

    def __init__(self, decay, rng, predelay=0.03, hp=180.0, early=0.5, width=1.0, size=1.0,
                 mod_depth=0.5, hf_ratio=0.4, normalize=True):
        sr = SR
        self.L = np.array([int(ms * size * sr / 1000) | 1 for ms in self.BASE_MS])
        n = len(self.L)
        depth = mod_depth * sr / 1000
        self.depth = depth
        self.B = int(self.L.min() - depth - 4)
        self.S = 1 << int(np.ceil(np.log2(self.L.max() + depth + self.B + 8)))
        self.buf = np.zeros((n, self.S))
        self.w = 0
        self.n = 0
        # gain per putaran untuk RT60 = decay; peredam one-pole agar treble RT60 = hf_ratio x decay
        self.g = 10 ** (-3 * self.L / (decay * sr))
        g_hf = 10 ** (-3 * self.L / (decay * hf_ratio * sr))
        # one-pole lowpass y = (1-a) x + a y1 dengan gain di Nyquist = g_hf/g -> (1-a)/(1+a) = r
        r = np.clip(g_hf / self.g, 1e-4, 1.0)
        self.a = (1 - r) / (1 + r)
        self.zi = np.zeros(n)
        self.lfo_f = rng.uniform(0.07, 0.5, n)
        self.lfo_ph = rng.uniform(0, 2 * np.pi, n)
        # tap keluaran & injeksi stereo dari baris matriks Hadamard yang saling tegak lurus ->
        # kanal kiri/kanan tidak berkorelasi (stereo lebar), energi terbagi rata ke semua jalur
        from scipy.linalg import hadamard
        H = hadamard(n).astype(float)
        self.out_l, self.out_r = H[1] / np.sqrt(n), H[2] / np.sqrt(n)
        self.in_l, self.in_r = H[3] / np.sqrt(n / 2), H[5] / np.sqrt(n / 2)
        self.width = width
        # difusi awal: allpass y[n] = -g x[n] + x[n-D] + g y[n-D] (lfilter dengan state)
        self.ap = []
        for ch in range(2):
            stages = []
            for ms, gg in ((4.77, 0.7), (3.59, 0.7), (12.73, 0.6), (9.31, 0.6)):
                D = int(ms * sr / 1000 * (1.07 if ch else 1.0))
                b = np.zeros(D + 1); b[0] = -gg; b[D] = 1.0
                a = np.zeros(D + 1); a[0] = 1.0; a[D] = -gg
                stages.append([b, a, np.zeros(D)])
            self.ap.append(stages)
        self.pre = np.zeros((int(predelay * sr), 2))
        self.hp = StreamEQ([("hp", hp, 0, 0.6)])
        # pantulan awal (sama seperti make_ir)
        er = np.zeros((int(0.09 * sr), 2))
        for _ in range(14):
            d = rng.uniform(0.008, 0.08)
            gain = 0.9 * (1 - d / 0.09) * rng.uniform(0.5, 1.0)
            pan = rng.uniform(0.1, 0.9)
            er[int(d * sr), 0] += gain * np.cos(pan * np.pi / 2)
            er[int(d * sr), 1] += gain * np.sin(pan * np.pi / 2)
        er = sosfilt(butter(1, 5000, fs=sr, output="sos"), er, axis=0)
        self.er = er * early / (np.sqrt((er ** 2).sum()) + 1e-12)
        self.er_tail = np.zeros((len(self.er) - 1, 2))
        self.gain = 1.0
        if normalize:
            self.gain = self._impulse_gain(decay)

    def _impulse_gain(self, decay):
        """Ukur energi respons impuls dengan salinan baru, lalu kembalikan pengali normalisasi."""
        import copy
        probe = copy.deepcopy(self)
        probe.gain = 1.0
        n = int(decay * 1.3 * SR)
        x = np.zeros((n, 2)); x[0] = 1.0
        y = probe(x)
        e = (y ** 2).sum(axis=0)
        return 1.0 / np.sqrt(e.mean() + 1e-20)

    def _diffuse(self, x):
        if _allpass_numba is not None:
            out = np.empty_like(x)
            for ch in range(2):
                y = np.ascontiguousarray(x[:, ch])
                for st in self.ap[ch]:
                    gg, D = -st[0][0], len(st[2])
                    if len(st) < 4:     # buffer melingkar untuk versi numba
                        st.append(np.zeros(D)); st.append(np.zeros(D)); st.append(0)
                    y = _allpass_numba(y, gg, st[3], st[4], st[5])
                    st[5] = (st[5] + len(y)) % D
                out[:, ch] = y
            return out
        out = np.empty_like(x)
        for ch in range(2):
            y = x[:, ch]
            for st in self.ap[ch]:
                y, st[2] = lfilter(st[0], st[1], y, zi=st[2])
            out[:, ch] = y
        return out

    def _fdn(self, x):
        if _fdn_numba is not None:
            out = np.zeros_like(x)
            self.w, self.n = _fdn_numba(np.ascontiguousarray(x), out, self.buf, self.w, self.n, self.L,
                                        self.depth, self.lfo_f, self.lfo_ph, self.a, self.g, self.zi,
                                        self.in_l, self.in_r, self.out_l, self.out_r, float(SR))
            if self.width < 1.0:
                mid = out.mean(axis=1, keepdims=True)
                out = mid + (out - mid) * self.width
            return out
        return self._fdn_numpy(x)

    def _fdn_numpy(self, x):
        n_lines, B, S = len(self.L), self.B, self.S
        out = np.zeros_like(x)
        k = np.arange(B)
        for s in range(0, len(x), B):
            m = min(B, len(x) - s)
            kk = k[:m]
            t = (self.n + kk) / SR
            # posisi baca bergoyang (interpolasi linier), selalu di masa lalu
            mod = self.depth * (0.5 + 0.5 * np.sin(2 * np.pi * self.lfo_f[:, None] * t + self.lfo_ph[:, None]))
            pos = (self.w + kk)[None, :] - self.L[:, None] - mod
            i0 = np.floor(pos).astype(np.int64)
            fr = pos - i0
            rows = np.arange(n_lines)[:, None]
            d = self.buf[rows, i0 % S] * (1 - fr) + self.buf[rows, (i0 + 1) % S] * fr
            # peredam (one-pole per jalur) + gain decay
            y = np.empty_like(d)
            for i in range(n_lines):
                y[i], zf = lfilter([1 - self.a[i]], [1, -self.a[i]], d[i], zi=[self.zi[i]])
                self.zi[i] = zf[0]
            y *= self.g[:, None]
            # Householder: y - (2/N) * jumlah
            fb = y - (2.0 / n_lines) * y.sum(axis=0, keepdims=True)
            inj = fb + self.in_l[:, None] * x[s:s + m, 0][None, :] + self.in_r[:, None] * x[s:s + m, 1][None, :]
            self.buf[:, (self.w + kk) % S] = inj
            out[s:s + m, 0] = self.out_l @ d
            out[s:s + m, 1] = self.out_r @ d
            self.w = (self.w + m) % S
            self.n += m
        if self.width < 1.0:
            mid = out.mean(axis=1, keepdims=True)
            out = mid + (out - mid) * self.width
        return out

    def __call__(self, x):
        # predelay
        buf = np.vstack([self.pre, x])
        self.pre = buf[len(x):] if len(self.pre) else self.pre
        x = buf[:len(x)]
        x = self.hp(x)
        tail = self._fdn(self._diffuse(x))
        # pantulan awal (FIR pendek, overlap-add)
        er = np.stack([oaconvolve(x[:, c], self.er[:, c]) for c in range(2)], axis=1)
        er[:len(self.er_tail)] += self.er_tail[:len(er)]
        if len(self.er_tail) > len(x):
            rest = self.er_tail[len(x):]
            new_tail = er[len(x):].copy()
            new_tail[:len(rest)] += rest
            self.er_tail = new_tail
        else:
            self.er_tail = er[len(x):].copy()
        return (tail + er[:len(x)]) * self.gain


try:   # inti FDN per sampel dikompilasi numba (puluhan kali lebih cepat); tanpa numba -> versi numpy
    from numba import njit

    @njit(cache=True, fastmath=True)
    def _fdn_numba(x, out, buf, w, n, L, depth, lfo_f, lfo_ph, a, g, zi, in_l, in_r, out_l, out_r, sr):
        N = L.shape[0]
        S = buf.shape[1]
        mask = S - 1
        d = np.empty(N)
        y = np.empty(N)
        two_pi = 2.0 * np.pi
        for k in range(x.shape[0]):
            t = (n + k) / sr
            ssum = 0.0
            for i in range(N):
                pos = w - L[i] - depth * (0.5 + 0.5 * np.sin(two_pi * lfo_f[i] * t + lfo_ph[i]))
                i0 = int(np.floor(pos))
                fr = pos - i0
                v = buf[i, i0 & mask] * (1.0 - fr) + buf[i, (i0 + 1) & mask] * fr
                d[i] = v
                zi[i] = (1.0 - a[i]) * v + a[i] * zi[i]
                y[i] = zi[i] * g[i]
                ssum += y[i]
            xl = x[k, 0]
            xr = x[k, 1]
            ol = 0.0
            orr = 0.0
            for i in range(N):
                buf[i, w & mask] = y[i] - (2.0 / N) * ssum + in_l[i] * xl + in_r[i] * xr
                ol += out_l[i] * d[i]
                orr += out_r[i] * d[i]
            out[k, 0] = ol
            out[k, 1] = orr
            w = (w + 1) & mask
        return w, n + x.shape[0]
    @njit(cache=True, fastmath=True)
    def _allpass_numba(x, g, xb, yb, w):
        """Allpass Schroeder y[n] = -g x[n] + x[n-D] + g y[n-D], buffer melingkar (state dibawa)."""
        D = xb.shape[0]
        out = np.empty_like(x)
        for k in range(x.shape[0]):
            j = (w + k) % D
            y = -g * x[k] + xb[j] + g * yb[j]
            xb[j] = x[k]
            yb[j] = y
            out[k] = y
        return out
except ImportError:  # pragma: no cover
    _fdn_numba = None
    _allpass_numba = None
