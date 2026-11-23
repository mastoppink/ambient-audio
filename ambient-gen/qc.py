"""Laporan kontrol kualitas untuk file audio hasil render.

  python qc.py out/m4/nebula_s2001_3600s.wav            # laporan teks + .qc.json + .qc.png
  python qc.py A.wav --compare B.wav                    # bandingkan dua render

Yang diukur dan kenapa penting:
- Loudness terintegrasi (LUFS) dan rentangnya (LRA): konsistensi volume. Musik tidur
  sebaiknya rata (LRA kecil) supaya tidak ada bagian yang tiba-tiba keras.
- True peak (dBTP): puncak setelah oversampling 4x. Di atas -1 dBTP bisa distorsi
  saat dikonversi ke MP3/AAC.
- Keseimbangan spektrum per pita, dibandingkan dengan "pink" (energi sama tiap oktaf).
  Ambient yang enak biasanya sedikit lebih gelap dari pink di atas 4 kHz, dan tidak
  menumpuk di 150-400 Hz (sumber suara "keruh").
- Kecocokan mono: berapa dB yang hilang saat L+R dijumlah (speaker HP, speaker bluetooth).
- Kecerahan (spectral centroid) dari waktu ke waktu.
"""
import argparse
import json
import sys

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from loudness import LoudnessMeter

BANDS = [  # (nama, lo, hi, keterangan)
    ("sub", 20, 60, "sub-bass"),
    ("bass", 60, 150, "bass / drone"),
    ("lowmid", 150, 400, "low-mid (rawan keruh)"),
    ("mid", 400, 2000, "mid (badan pad)"),
    ("presence", 2000, 6000, "presence"),
    ("air", 6000, 16000, "air / desis"),
]
# Target relatif terhadap pink (dB), rentang wajar untuk ambient gelap-luas.
# Ini pedoman praktis (heuristik), bukan standar resmi.
TARGET = {"sub": (-20, 0), "bass": (-3, 6), "lowmid": (-3, 5), "mid": (-4, 3),
          "presence": (-15, -3), "air": (-32, -12)}


def third_octave(freqs, psd):
    centers = 1000 * 2 ** (np.arange(-17, 14) / 3)       # ~20 Hz .. 20 kHz
    lv = []
    for c in centers:
        m = (freqs >= c * 2 ** (-1 / 6)) & (freqs < c * 2 ** (1 / 6))
        lv.append(10 * np.log10(psd[m].sum() + 1e-30))
    return centers, np.array(lv)


def analyze(path, block_s=10.0):
    info = sf.info(path)
    sr = info.samplerate
    meter = LoudnessMeter(sr)
    nfft = 16384
    win = np.hanning(nfft)
    psd = np.zeros(nfft // 2 + 1)
    frames = 0
    tp = 0.0
    e_lr = e_mid = 0.0
    cross = e_l = e_r = 0.0
    centroid = []
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    with sf.SoundFile(path) as f:
        for b in f.blocks(blocksize=int(block_s * sr), dtype="float64"):
            meter.add(b)
            up = resample_poly(b, 4, 1, axis=0)
            tp = max(tp, np.abs(up).max())
            m = b.mean(axis=1)
            e_mid += (m**2).sum()
            e_lr += ((b**2).sum(axis=1) / 2).sum()
            cross += (b[:, 0] * b[:, 1]).sum()
            e_l += (b[:, 0] ** 2).sum()
            e_r += (b[:, 1] ** 2).sum()
            blk_psd = np.zeros_like(psd)
            for s in range(0, len(m) - nfft + 1, nfft // 2):
                blk_psd += np.abs(np.fft.rfft(m[s:s + nfft] * win)) ** 2
            psd += blk_psd
            frames += 1
            c = (freqs * blk_psd).sum() / max(blk_psd.sum(), 1e-20)
            centroid.append(c)
    # Energi per pita 1/3 oktaf (pink noise = datar), dinormalkan ke rata-rata 100-2000 Hz.
    centers, levels = third_octave(freqs, psd / frames)
    norm = levels[(centers >= 100) & (centers <= 2000)].mean()
    levels = levels - norm
    band_rel = {}
    for name, lo, hi, _ in BANDS:
        m_ = (centers >= lo) & (centers < hi)
        band_rel[name] = round(float(levels[m_].mean()), 1)
    st = meter.short_term()
    return {
        "file": path,
        "duration_min": round(info.frames / sr / 60, 2),
        "lufs": round(meter.integrated(), 1),
        "lra": round(meter.lra(), 1),
        "short_term_max": round(float(st.max()), 1) if len(st) else None,
        "true_peak_dbtp": round(20 * np.log10(tp + 1e-12), 1),
        "mono_loss_db": round(10 * np.log10(e_mid / max(e_lr, 1e-20)), 1),
        "lr_correlation": round(cross / np.sqrt(e_l * e_r + 1e-20), 2),
        "bands_vs_pink_db": band_rel,
        "centroid_hz_median": round(float(np.median(centroid)), 0),
        "centroid_hz_range": [round(float(np.percentile(centroid, 5))), round(float(np.percentile(centroid, 95)))],
        "_centroid": [round(float(c), 1) for c in centroid],
        "_block_s": block_s,
        "_third": (centers.tolist(), levels.tolist()),
    }


def judge(r):
    """Daftar (status, pesan). status: OK / CEK / MASALAH."""
    out = []
    tp = r["true_peak_dbtp"]
    out.append(("OK" if tp <= -1.0 else "MASALAH", f"true peak {tp} dBTP (batas aman -1)"))
    lra = r["lra"]
    out.append(("OK" if lra <= 8 else "CEK", f"loudness range {lra} LU (musik tidur idealnya <= 8)"))
    ml = r["mono_loss_db"]
    out.append(("OK" if ml >= -3 else "CEK", f"kehilangan saat mono {ml} dB (aman >= -3)"))
    for name, lo, hi, desc in BANDS:
        v = r["bands_vs_pink_db"][name]
        a, b = TARGET[name]
        if v > b:
            s, hint = "CEK", "terlalu banyak"
        elif v < a:
            s, hint = "CEK", "terlalu sedikit"
        else:
            s, hint = "OK", "wajar"
        out.append((s, f"{desc:24s} {lo:>5}-{hi:<5} Hz  {v:+6.1f} dB vs pink  ({hint}; target {a:+}..{b:+})"))
    return out


def report(r, other=None):
    lines = [f"QC: {r['file']}  ({r['duration_min']} menit)",
             f"  loudness {r['lufs']} LUFS, LRA {r['lra']} LU, short-term maks {r['short_term_max']} LUFS",
             f"  true peak {r['true_peak_dbtp']} dBTP, korelasi L/R {r['lr_correlation']}, "
             f"centroid {r['centroid_hz_median']:.0f} Hz ({r['centroid_hz_range'][0]}-{r['centroid_hz_range'][1]})"]
    for s, msg in judge(r):
        lines.append(f"  [{s:7s}] {msg}")
    if other:
        lines.append(f"\nBandingkan dengan {other['file']}:")
        for k in ("lufs", "lra", "true_peak_dbtp", "mono_loss_db", "lr_correlation", "centroid_hz_median"):
            lines.append(f"  {k:20s} {other[k]!s:>8} -> {r[k]!s:>8}")
        for k in r["bands_vs_pink_db"]:
            a, b = other["bands_vs_pink_db"][k], r["bands_vs_pink_db"][k]
            lines.append(f"  pita {k:15s} {a:+8.1f} -> {b:+8.1f}  ({b - a:+.1f})")
    return "\n".join(lines)


def plot(r, png, other=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(13, 4))
    for rr, lab, ls in ((other, "sebelum", "--"), (r, "sesudah" if other else "spektrum", "-")):
        if rr is None:
            continue
        c, lv = map(np.asarray, rr["_third"])
        ax[0].semilogx(c, lv, ls, marker=".", label=lab)
        t = np.arange(len(rr["_centroid"])) * rr["_block_s"] / 60
        ax[1].plot(t, rr["_centroid"], ls, label=lab)
    for name, lo, hi, _ in BANDS:
        ax[0].axvline(lo, c="gray", lw=0.5)
        ax[0].text(np.sqrt(lo * hi), 21, name, ha="center", fontsize=8)
    ax[0].set_ylim(-45, 25)
    ax[0].axhline(0, c="k", lw=0.6)
    ax[0].set_xlim(20, 20000)
    ax[0].set_title("level per 1/3 oktaf, relatif pink (0 = rata-rata 100-2000 Hz)")
    ax[0].set_xlabel("Hz")
    ax[0].legend()
    ax[1].set_title("kecerahan (spectral centroid)")
    ax[1].set_xlabel("menit")
    ax[1].set_ylabel("Hz")
    ax[1].legend()
    plt.tight_layout()
    plt.savefig(png, dpi=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--compare", help="render pembanding (mis. versi sebelum perubahan)")
    a = ap.parse_args()
    r = analyze(a.wav)
    other = analyze(a.compare) if a.compare else None
    stem = a.wav[:-4]
    with open(stem + ".qc.json", "w") as f:
        json.dump({k: v for k, v in r.items() if not k.startswith("_")}, f, indent=1)
    plot(r, stem + ".qc.png", other)
    print(report(r, other))


if __name__ == "__main__":
    sys.exit(main())
