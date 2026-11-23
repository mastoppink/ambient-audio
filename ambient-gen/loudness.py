"""Pengukur loudness terintegrasi (ITU-R BS.1770-4 / EBU R128) yang bisa diumpan per potongan.
pyloudnorm butuh seluruh audio di memori; ini tidak."""
import numpy as np
from scipy.signal import lfilter, lfilter_zi

# koefisien K-weighting untuk 48 kHz (BS.1770)
_B1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
_A1 = [1.0, -1.69065929318241, 0.73248077421585]
_B2 = [1.0, -2.0, 1.0]
_A2 = [1.0, -1.99004745483398, 0.99007225036621]


class LoudnessMeter:
    def __init__(self, sr=48_000, channels=2):
        assert sr == 48_000, "koefisien K-weighting di sini khusus 48 kHz"
        self.step = sr // 10                 # sub-blok 100 ms; blok gating 400 ms = 4 sub-blok
        self.z1 = np.zeros((2, channels))
        self.z2 = np.zeros((2, channels))
        self.rest = np.zeros((0, channels))
        self.sub = []                        # energi tiap sub-blok 100 ms (jumlah antar kanal)

    def add(self, x):
        y, self.z1 = lfilter(_B1, _A1, x, axis=0, zi=self.z1)
        y, self.z2 = lfilter(_B2, _A2, y, axis=0, zi=self.z2)
        y = np.vstack([self.rest, y])
        k = len(y) // self.step
        if k:
            blocks = y[: k * self.step].reshape(k, self.step, -1)
            self.sub.extend((blocks**2).mean(axis=1).sum(axis=1))
        self.rest = y[k * self.step:]

    def integrated(self):
        e = np.asarray(self.sub)
        if len(e) < 4:
            return -np.inf
        blocks = np.convolve(e, np.ones(4) / 4, mode="valid")    # blok 400 ms, overlap 75%
        lk = -0.691 + 10 * np.log10(blocks + 1e-20)
        g = blocks[lk > -70]
        if not len(g):
            return -np.inf
        rel = -0.691 + 10 * np.log10(g.mean()) - 10
        g = blocks[(lk > -70) & (lk > rel)]
        return -0.691 + 10 * np.log10(g.mean())

    # --- statistik tambahan untuk laporan QC ---
    def short_term(self):
        """Loudness jangka pendek (jendela 3 s, langkah 100 ms), LUFS."""
        e = np.asarray(self.sub)
        if len(e) < 30:
            return np.array([])
        st = np.convolve(e, np.ones(30) / 30, mode="valid")
        return -0.691 + 10 * np.log10(st + 1e-20)

    def lra(self):
        """Loudness range (EBU Tech 3342): sebaran loudness jangka pendek, 10%..95%."""
        st = self.short_term()
        st = st[st > -70]
        if not len(st):
            return 0.0
        e = 10 ** ((st + 0.691) / 10)
        rel = -0.691 + 10 * np.log10(e.mean()) - 20
        st = st[st > rel]
        return float(np.percentile(st, 95) - np.percentile(st, 10))
