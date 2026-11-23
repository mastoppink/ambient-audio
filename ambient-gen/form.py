"""Bentuk makro: kurva intensitas 0..1 sepanjang lagu.

Intensitas naik-turun pelan (gabungan dua gelombang dengan periode belasan menit),
diawali intro yang tenang dan diakhiri outro yang menurun. Kurva ini menggerakkan:
- kecerahan pad (filter sedikit lebih terbuka saat intens)
- kepadatan melodi (lebih banyak nada saat intens)
- level tekstur angin
"""
import numpy as np


def make_shape(total, seed, f):
    """f = bagian [form] dari preset yang sudah di-resolve. Mengembalikan fungsi t(detik) -> 0..1."""
    amount = float(f.get("amount", 0.6))
    rng = np.random.default_rng([seed, 6])
    p1, p2 = (rng.uniform(*sorted(f.get("period_min", [12, 25]))) * 60 for _ in range(2))
    ph1, ph2 = rng.uniform(0, 2 * np.pi, 2)
    intro = float(f.get("intro_min", 3)) * 60
    outro = float(f.get("outro_min", 5)) * 60
    low = 0.2

    def shape(t):
        t = np.asarray(t, float)
        wave = 0.5 + 0.32 * np.sin(2 * np.pi * t / p1 + ph1) + 0.18 * np.sin(2 * np.pi * t / p2 + ph2)
        c = 0.5 + amount * (wave - 0.5)
        # intro/outro: tarik ke nilai rendah dengan kurva halus
        wi = np.clip(t / intro, 0, 1) if intro > 0 else 1.0
        wo = np.clip((total - t) / outro, 0, 1) if outro > 0 else 1.0
        w = np.minimum(np.sin(wi * np.pi / 2) ** 2, np.sin(wo * np.pi / 2) ** 2)
        return low + (c - low) * w

    return shape


def flat(t):
    return np.full(np.shape(t), 0.5)
