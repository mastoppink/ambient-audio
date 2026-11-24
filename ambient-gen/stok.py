"""Versi edit untuk stock music: potongan 30 detik, 60 detik, dan loop mulus dari satu track.

Dipakai oleh album.py (--stok). Bisa juga dipanggil langsung untuk file WAV 48 kHz yang sudah ada
beserta file .events.json-nya:

  python stok.py out/album/.../resep/01_satellite_D_12345     # stem tanpa ekstensi (perlu .wav + .events.json)

Cara kerja:
  - Potongan 30/60 detik mulai tepat saat chord berganti (bukan di tengah nada), setelah pembukaan,
    di bagian yang volumenya mendekati rata-rata lagu. Masuk 1,5 detik, keluar dengan fade 3-5 detik.
  - Loop: potongan sepanjang L + X detik; X detik terakhirnya di-crossfade (equal-power) ke awal.
    Hasilnya L detik yang bisa diputar berulang tanpa sambungan terdengar, karena sampel terakhir
    langsung bersambung ke sampel pertama.
  - Setiap edit disamakan volumenya dengan track (LUFS), puncak dijaga di bawah -1 dBTP.
"""
import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from loudness import LoudnessMeter

SR = 48_000
CEILING = -1.0


def _lufs(x):
    m = LoudnessMeter(SR)
    m.add(x)
    return m.integrated()


def _true_peak_db(x):
    return 20 * np.log10(np.abs(resample_poly(x, 4, 1, axis=0)).max() + 1e-12)


def _level(x, target):
    """Samakan loudness dengan target, lalu turunkan kalau puncak melewati batas."""
    g = 10 ** ((target - _lufs(x)) / 20)
    x = x * g
    tp = _true_peak_db(x)
    if tp > CEILING:
        x = x * 10 ** ((CEILING - 0.1 - tp) / 20)
    return x


def _ramp(n, naik=True):
    t = np.linspace(0, 1, n)
    w = np.sin(t * np.pi / 2) ** 2
    return (w if naik else w[::-1])[:, None]


def titik_mulai(x, events, panjang, intro=20.0):
    """Saat chord berganti (setelah pembukaan) yang memberi potongan paling mendekati rata-rata lagu."""
    total = len(x) / SR
    starts = sorted({round(e["start"], 3) for e in events if e["layer"] == "pad"})
    calon = [s for s in starts if intro <= s <= total - panjang - 15]
    if not calon:   # track terlalu pendek: ambil setelah pembukaan
        return min(intro, max(0.0, total - panjang - 5))
    rata = np.sqrt(np.mean(x[int(intro * SR): int((total - 15) * SR)] ** 2))
    terbaik = min(calon, key=lambda s: abs(np.log(np.sqrt(np.mean(
        x[int(s * SR): int((s + panjang) * SR)] ** 2)) / rata + 1e-9)))
    return terbaik + 0.5   # sedikit setelah chord baru mulai: serangan pad sudah lewat


def potongan(x, events, detik, target):
    a = titik_mulai(x, events, detik)
    seg = x[int(a * SR): int(a * SR) + int(detik * SR)].copy()
    fin, fout = int(1.5 * SR), int(min(5.0, detik / 8) * SR)
    seg[:fin] *= _ramp(fin)
    seg[-fout:] *= _ramp(fout, naik=False)
    return _level(seg, target)


def loop(x, events, detik, target, xfade=4.0):
    a = titik_mulai(x, events, detik + xfade)
    L, X = int(detik * SR), int(xfade * SR)
    seg = x[int(a * SR): int(a * SR) + L + X]
    out = seg[:L].copy()
    t = np.linspace(0, 1, X)[:, None]
    out[:X] = seg[:X] * np.sin(t * np.pi / 2) + seg[L:L + X] * np.cos(t * np.pi / 2)
    return _level(out, target)


def ke_wav16(x, path, tag=()):
    """48 kHz float -> WAV 16-bit 44,1 kHz (soxr + dither TPDF), sama seperti track album."""
    tmp = path + ".tmp.wav"
    sf.write(tmp, x.astype(np.float32), SR, subtype="FLOAT")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", tmp, "-af",
                    "aresample=44100:resampler=soxr:precision=28:dither_method=triangular",
                    "-c:a", "pcm_s16le", *tag, path], check=True)
    os.remove(tmp)


def buat_semua(stem, folder, nama, target, tag=(), log=print):
    """Tulis '<nama> (30s).wav', '(60s)', dan '(Loop 60s)' ke folder. Mengembalikan daftar file."""
    x, sr = sf.read(stem + ".wav", dtype="float64")
    assert sr == SR
    with open(stem + ".events.json") as f:
        events = json.load(f)
    os.makedirs(folder, exist_ok=True)
    hasil = []
    for label, y in (("30s", potongan(x, events, 30, target)), ("60s", potongan(x, events, 60, target)),
                     ("Loop 60s", loop(x, events, 60, target))):
        p = os.path.join(folder, f"{nama} ({label}).wav")
        ke_wav16(y, p, tag)
        hasil.append(p)
    log(f"  stok: 30s, 60s, loop 60s  -> {os.path.relpath(folder)}")
    return hasil


if __name__ == "__main__":
    for s in sys.argv[1:]:
        s = s[:-4] if s.endswith(".wav") else s
        buat_semua(s, os.path.join(os.path.dirname(s), "stok"), os.path.basename(s), -14.0)
