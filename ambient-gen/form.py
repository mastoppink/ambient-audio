"""Bentuk makro: kurva intensitas 0..1 sepanjang lagu, dan pembagian lagu menjadi babak.

Kurva intensitas menggerakkan kecerahan pad, kepadatan melodi, dan level tekstur angin.
Jenis bentuk (form.type):
  arc     - intro tenang, dua gelombang naik-turun, outro (bentuk asli)
  rise    - tumbuh perlahan sampai ~2/3 lagu, lalu turun lembut
  valley  - mulai sedang, menipis di tengah, mengembang lagi menjelang akhir
  calm    - hampir datar dan rendah (paling cocok untuk tidur/meditasi)
  journey - beberapa "dataran" dengan tingkat berbeda, berpindah perlahan

Babak (sections): lagu dibagi menjadi bagian 8-18 menit. Tiap babak punya karakter sendiri:
melodi lebih ramai/sepi atau istirahat sama sekali, melodi lebih tinggi/rendah, angin lebih
kuat/lemah, dan chord favorit. Banyaknya perubahan diatur oleh variation.amount (0 = mati).
"""
import numpy as np

FORM_TYPES = ("arc", "rise", "valley", "calm", "journey")
CHORD_NAMES = ("I", "II", "iii", "V", "vi", "vii", "IV", "Isus", "I6")


def _smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def make_shape(total, seed, f):
    """f = bagian [form] dari preset yang sudah di-resolve. Mengembalikan fungsi t(detik) -> 0..1."""
    amount = float(f.get("amount", 0.6))
    kind = str(f.get("type", "arc"))
    if kind not in FORM_TYPES:
        raise ValueError(f"form.type {kind!r} tidak dikenal; pilih: {', '.join(FORM_TYPES)}")
    rng = np.random.default_rng([seed, 6])
    p1, p2 = (rng.uniform(*sorted(f.get("period_min", [12, 25]))) * 60 for _ in range(2))
    ph1, ph2 = rng.uniform(0, 2 * np.pi, 2)
    intro = float(f.get("intro_min", 3)) * 60
    outro = float(f.get("outro_min", 5)) * 60
    low = 0.2
    # journey: tingkat tiap "dataran" (diambil dari sumber acak terpisah agar tipe lain tidak berubah)
    jr = np.random.default_rng([seed, 12])
    plateau_len = jr.uniform(8, 14) * 60
    levels = jr.uniform(0.25, 0.85, size=int(total / plateau_len) + 3)

    def base(t):
        wave = 0.5 + 0.32 * np.sin(2 * np.pi * t / p1 + ph1) + 0.18 * np.sin(2 * np.pi * t / p2 + ph2)
        small = 0.5 + 0.5 * np.sin(2 * np.pi * t / p1 + ph1)
        u = t / max(total, 1)
        if kind == "arc":
            return wave
        if kind == "rise":
            return 0.2 + 0.65 * _smooth(u / 0.68) - 0.25 * _smooth((u - 0.75) / 0.25) + 0.12 * (small - 0.5)
        if kind == "valley":
            return 0.72 - 0.5 * np.sin(np.pi * np.clip(u, 0, 1)) ** 2 + 0.12 * (small - 0.5)
        if kind == "calm":
            return 0.32 + 0.08 * (small - 0.5)
        # journey: interpolasi halus antar dataran (perpindahan 2 menit)
        k = t / plateau_len
        i = np.floor(k).astype(int)
        frac = _smooth((k - i) * plateau_len / 120.0)
        return levels[np.clip(i, 0, len(levels) - 1)] * (1 - frac) + levels[np.clip(i + 1, 0, len(levels) - 1)] * frac

    def shape(t):
        t = np.asarray(t, float)
        c = 0.5 + amount * (base(t) - 0.5)
        wi = np.clip(t / intro, 0, 1) if intro > 0 else 1.0
        wo = np.clip((total - t) / outro, 0, 1) if outro > 0 else 1.0
        w = np.minimum(np.sin(wi * np.pi / 2) ** 2, np.sin(wo * np.pi / 2) ** 2)
        return np.clip(low + (c - low) * w, 0, 1)

    return shape


class Sections:
    """Pembagian lagu menjadi babak dengan karakter berbeda."""

    def __init__(self, total, seed, amount, allow_rest=True):
        rng = np.random.default_rng([seed, 11])
        a = float(amount)
        self.list = []
        t = 0.0
        first = True
        while t < total:
            length = rng.uniform(8, 18) * 60
            rest = (not first) and allow_rest and rng.random() < 0.18 * a
            mel = 0.0 if rest else float(rng.uniform(1 - 0.5 * a, 1 + 0.6 * a))
            self.list.append(dict(
                start=t, end=t + length,
                melody=mel,                                            # pengali kepadatan melodi
                register=int(round(rng.uniform(-3, 3) * a)),           # geser melodi (langkah tangga nada)
                texture=float(rng.uniform(1 - 0.6 * a, 1 + 0.9 * a)),  # pengali level angin
                favor=str(rng.choice(CHORD_NAMES[:6])),                # chord favorit babak ini
                favor_boost=1 + 2 * a,
            ))
            if first:   # babak pertama: tanpa geser register, supaya awal tetap mirip preset
                self.list[0]["register"] = 0
                first = False
            t += length

    def at(self, t):
        for s in self.list:
            if s["start"] <= t < s["end"]:
                return s
        return self.list[-1]

    def texture_mult(self, t):
        """Pengali angin dengan perpindahan halus 40 detik di batas babak."""
        t = np.asarray(t, float)
        out = np.full(t.shape, self.list[0]["texture"])
        for s in self.list[1:]:
            k = _smooth((t - s["start"] + 20) / 40)
            out = out * (1 - k) + s["texture"] * k
        return out
