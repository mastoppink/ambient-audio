"""Generator Spacenight.

Contoh:
  python generate.py presets/deep_sleep.toml
  python generate.py presets/nebula.toml --seed 42 --set melody.density=0.4 --set key.mode=dorian
  python generate.py presets/drift.toml --preview 120 --variations 8
  python generate.py out/deep_sleep_s1007_120s.toml --duration 60     # ulangi hasil yang disukai, versi panjang

File .toml yang ditulis di samping setiap audio berisi semua nilai final (termasuk seed),
jadi bisa dipakai lagi sebagai preset untuk mereproduksi hasil yang persis sama.
"""
import argparse
import os
import re
import time

import settings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preset", nargs="?", help="file preset .toml (kosong = default)")
    ap.add_argument("--seed", type=int, help="ganti seed preset")
    ap.add_argument("--duration", type=float, help="durasi (menit)")
    ap.add_argument("--preview", type=float, metavar="DETIK", help="render pendek untuk mencoba")
    ap.add_argument("--variations", type=int, default=1, help="jumlah versi (seed berurutan)")
    ap.add_argument("--set", action="append", default=[], metavar="KUNCI=NILAI",
                    help="override, mis. pad.brightness=0.3 atau 'pad.width=[0.2,0.8]'")
    ap.add_argument("--stems", action="store_true", help="simpan tiap lapisan kering")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--workers", type=int, help="jumlah proses paralel (default: semua core)")
    ap.add_argument("--no-mp3", action="store_true")
    ap.add_argument("--flac", action="store_true", help="juga simpan FLAC 24-bit (lossless)")
    ap.add_argument("--flac16", action="store_true", help="juga simpan FLAC 16-bit + dither (lebih kecil)")
    ap.add_argument("--no-qc", action="store_true", help="lewati laporan kualitas")
    ap.add_argument("--dry-run", action="store_true", help="tampilkan nilai final tanpa render")
    a = ap.parse_args()

    base = settings.load(a.preset, a.set)
    seed0 = a.seed if a.seed is not None else int(base["seed"])
    total = a.preview if a.preview else (a.duration or base["duration_min"]) * 60
    slug = re.sub(r"[^a-z0-9]+", "_", str(base["name"]).lower()).strip("_") or "spacenight"
    os.makedirs(a.outdir, exist_ok=True)

    for i in range(a.variations):
        seed = seed0 + i
        r = settings.resolve(base, seed)
        r["duration_min"] = round(total / 60, 3)
        if a.preview:   # simpan durasi penuh, supaya .toml preview langsung bisa dipakai untuk versi panjang
            r["duration_min"] = a.duration or base["duration_min"]
        settings.apply(r)
        text = settings.to_toml(r)
        if a.dry_run:
            print(f"# --- seed {seed} ---\n{text}")
            continue
        stem = os.path.join(a.outdir, f"{slug}_s{seed}_{int(total)}s")
        print(f"[{i + 1}/{a.variations}] {base['name']} seed {seed}, {total / 60:.1f} menit, "
              f"{r['key']['tonic']} {r['key']['mode']}")
        t0 = time.time()
        import pipeline  # import di sini: pipeline membaca config yang sudah diterapkan
        full = (a.duration or base["duration_min"]) * 60   # durasi versi panjang
        events, lufs = pipeline.produce(stem, total, seed, form=r.get("form"),
                                        form_total=max(full, total), stems=a.stems,
                                        workers=a.workers)
        qc_text = pipeline.save_meta(stem, events, text, lufs, mp3=not a.no_mp3, flac=a.flac,
                                     qc=not a.no_qc, profile=r["qc"]["profile"],
                                     flac16=a.flac16, seed=seed)
        if qc_text:
            print("\n".join("  " + l for l in qc_text.splitlines()[3:] if "[CEK" in l or "[MASALAH" in l)
                  or "  QC: semua OK")
        ext = "wav" + ("/.mp3" if not a.no_mp3 else "") + ("/.flac" if a.flac else "") \
            + ("/.16bit.flac" if a.flac16 else "")
        print(f"  -> {stem}.{ext}/.toml  ({lufs:.1f} LUFS, {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
