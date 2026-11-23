"""Pemeriksaan sebelum rilis: render setiap preset dan periksa hal-hal yang terdengar oleh pendengar.

  python cek_rilis.py                 # semua preset, 4 menit masing-masing
  python cek_rilis.py --menit 2 --preset nebula deep_sleep
  python cek_rilis.py --wav a.wav b.wav   # periksa file yang sudah ada (mis. ekspor dari Studio web)

Pemeriksaan per file:
  - loudness terintegrasi = target preset (±0,5 LU)
  - true peak WAV dan MP3 <= -1 dBTP
  - awal lagu benar-benar mulai dari hening (detik pertama < -40 dB relatif rata-rata lagu)
  - akhir lagu fade-out (detik terakhir < -30 dB relatif)
  - tidak ada nilai rusak (NaN/inf) dan tidak ada klik (lompatan sampel jauh di atas yang wajar)
  - keseimbangan spektrum sesuai profil QC preset
  - tidak ada nada melodi yang bentrok dengan chord (preset dengan consonance = 1)
"""
import argparse
import glob
import os
import subprocess
import sys
import tomllib

import numpy as np
import soundfile as sf

import qc
import harmony_check

ROOT = os.path.dirname(os.path.abspath(__file__))
SR = 48000


def check_audio(wav, target_lufs, profile, consonance=None, events=None):
    """Kembalikan daftar (lulus: bool, pesan)."""
    out = []
    x, sr = sf.read(wav, dtype="float64")
    ok_num = bool(np.isfinite(x).all())
    out.append((ok_num, "tanpa nilai rusak (NaN/inf)"))
    m = x.mean(axis=1)
    rms = lambda s: 20 * np.log10(np.sqrt((s ** 2).mean()) + 1e-12)
    avg = rms(m)
    first, last = rms(m[:sr]) - avg, rms(m[-sr:]) - avg
    out.append((first < -40, f"awal mulai dari hening: detik pertama {first:.0f} dB relatif rata-rata (batas -40)"))
    out.append((last < -30, f"akhir fade-out: detik terakhir {last:.0f} dB relatif rata-rata (batas -30)"))
    d = np.abs(np.diff(x, axis=0)).max(axis=1)
    typical = np.percentile(d, 99.9)
    out.append((d.max() < max(4 * typical, 0.05), f"tanpa klik: lompatan maks {d.max():.3f} (wajar {typical:.3f})"))
    r = qc.analyze(wav)
    out.append((abs(r["lufs"] - target_lufs) <= 0.5, f"loudness {r['lufs']} LUFS (target {target_lufs})"))
    out.append((r["true_peak_dbtp"] <= -1.0, f"true peak WAV {r['true_peak_dbtp']} dBTP"))
    bad = [msg for s, msg in qc.judge(r, profile) if s != "OK" and "loudness range" not in msg]
    out.append((not bad, "keseimbangan suara sesuai profil '" + profile + "'" + ("" if not bad else ": " + "; ".join(bad))))
    mp3 = os.path.splitext(wav)[0] + ".mp3"
    if os.path.exists(mp3):
        import pipeline
        tp = pipeline._mp3_true_peak(mp3)
        out.append((tp <= -1.0, f"true peak MP3 {tp:.2f} dBTP"))
    if events and consonance:
        n, a, b = harmony_check.check(events)
        out.append((a == 0 and (n == 0 or b / n < 0.03), f"nada sumbang: {a} saat mulai, {b} saat chord berganti (dari {n} nada)"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menit", type=float, default=4.0)
    ap.add_argument("--preset", nargs="*")
    ap.add_argument("--wav", nargs="*", help="periksa file WAV yang sudah ada")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "out", "cek_rilis"))
    a = ap.parse_args()
    gagal = 0
    if a.wav:
        for w in a.wav:
            import re
            name = re.match(r"(.+?)_s\d+_", os.path.basename(w)).group(1)   # mis. deep_sleep_s1001_120s.wav
            with open(os.path.join(ROOT, "presets", f"{name}.toml"), "rb") as f:
                p = tomllib.load(f)
            target = p.get("master", {}).get("target_lufs", -16.0)
            profile = p.get("qc", {}).get("profile", "default")
            print(f"\n== {w}")
            for ok, msg in check_audio(w, target, profile):
                print(("  [OK]    " if ok else "  [GAGAL] ") + msg)
                gagal += not ok
        print(f"\n{'SEMUA LULUS' if not gagal else f'{gagal} PEMERIKSAAN GAGAL'}")
        sys.exit(1 if gagal else 0)

    presets = a.preset or sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "presets", "*.toml")))
    os.makedirs(a.outdir, exist_ok=True)
    for name in presets:
        print(f"\n== {name} ({a.menit:g} menit)", flush=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "generate.py"), os.path.join(ROOT, "presets", f"{name}.toml"),
                        "--duration", str(a.menit), "--outdir", a.outdir, "--no-qc"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stem = sorted(glob.glob(os.path.join(a.outdir, f"{name}_s*_{int(a.menit * 60)}s.wav")))[-1][:-4]
        with open(stem + ".toml", "rb") as f:
            r = tomllib.load(f)
        res = check_audio(stem + ".wav", r["master"]["target_lufs"], r["qc"]["profile"],
                          consonance=r["melody"].get("consonance", 0) > 0 and r["mix"]["melody"] > 0,
                          events=stem + ".events.json")
        for ok, msg in res:
            print(("  [OK]    " if ok else "  [GAGAL] ") + msg)
            gagal += not ok
    print(f"\n{'SEMUA LULUS' if not gagal else f'{gagal} PEMERIKSAAN GAGAL'}")
    sys.exit(1 if gagal else 0)


if __name__ == "__main__":
    main()
