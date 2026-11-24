"""Cara mudah membuat musik untuk video, tanpa perlu paham istilah teknis.

  python buat.py                                  # tanya-jawab langkah demi langkah
  python buat.py --untuk tidur --jumlah 3         # langsung: 3 video musik tidur, 60 menit
  python buat.py --untuk fokus --jumlah 2 --contoh   # buat contoh 2 menit dulu untuk didengar
  python buat.py --lanjut                         # buat versi penuh dari contoh terakhir

Program memilih sendiri kombinasi suasana, nada dasar, bentuk lagu, dan nomor versi
supaya setiap video jelas berbeda: dari satu sama lain DAN dari video yang pernah dibuat
sebelumnya (dicatat di out/katalog.json).
"""
import argparse
import datetime
import json
import os
import sys
import time

import numpy as np

import config
import form
import judul
import mirip
import settings
from compose import compose

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out", "video")
KATALOG = os.path.join(ROOT, "out", "katalog.json")
RENCANA = os.path.join(ROOT, "out", "rencana_terakhir.json")

TUJUAN = {
    "tidur":    ("untuk Tidur", ["deep_sleep", "starlight_lullaby", "solitude"]),
    "fokus":    ("untuk Fokus", ["drift", "deep_space", "orbit"]),
    "belajar":  ("untuk Belajar", ["orbit", "drift", "aurora"]),
    "santai":   ("untuk Bersantai", ["nebula", "aurora", "solitude"]),
    "meditasi": ("untuk Meditasi", ["meditation", "deep_space", "solitude"]),
    "campur":   ("", ["nebula", "aurora", "orbit", "drift", "deep_space", "solitude",
                      "starlight_lullaby", "deep_sleep", "meditation"]),
}
SUASANA = {"lydian": "luas & melayang", "dorian": "sendu & hangat", "aeolian": "gelap & tenang",
           "ionian": "cerah & manis", "mixolydian": "ringan & santai", "phrygian": "misterius"}
BENTUK = {"arc": "naik-turun lembut", "rise": "tumbuh perlahan", "valley": "menenang di tengah",
          "calm": "datar & tenang", "journey": "berpindah suasana"}
MELODI = {"glass": "bel kaca", "kalimba": "kalimba", "piano": "piano jauh", "soft": "nada lembut",
          "-": "tanpa melodi"}
NADA = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BATAS_MIRIP = 0.60


# ---------- katalog: video yang pernah dibuat ----------
def baca_katalog():
    if not os.path.exists(KATALOG):
        return []
    with open(KATALOG) as f:
        return json.load(f)


def simpan_katalog(items):
    os.makedirs(os.path.dirname(KATALOG), exist_ok=True)
    with open(KATALOG, "w") as f:
        json.dump(items, f, indent=1)


def _feat_to_json(f):
    return {"pc": [round(x, 5) for x in f["pc"]], "bigrams": [[a, b, n] for (a, b), n in f["bigrams"].items()],
            "timbre": f["timbre"], "form": f["form"], "bands": f.get("bands")}


def _feat_from_json(d):
    from collections import Counter
    return {"pc": np.array(d["pc"]), "bigrams": Counter({(a, b): n for a, b, n in d["bigrams"]}),
            "timbre": d["timbre"], "form": d["form"], "bands": d.get("bands")}


# ---------- perencanaan ----------
def kandidat(preset, tonic, seed, menit):
    raw = settings.load(os.path.join(ROOT, "presets", f"{preset}.toml"), [f'key.tonic="{tonic}"'])
    r = settings.resolve(raw, seed)
    r["duration_min"] = menit
    settings.apply(r)
    total = menit * 60
    config.SHAPE = form.make_shape(total, seed, r["form"])
    config.SECTIONS = form.Sections(total, seed, config.VARIATION, config.MELODY["level"] > 0) \
        if config.VARIATION > 0 else None
    feat = mirip.features(r, compose(total, seed, with_melody=True))
    return r, feat


def rencanakan(tujuan, jumlah, menit, rng, log=print):
    _, daftar = TUJUAN[tujuan]
    lama = [_feat_from_json(k["fitur"]) for k in baca_katalog()]
    terpakai = {(k["preset"], k["nada"]) for k in baca_katalog()}
    rencana, fitur_rencana = [], []
    mulai = int(rng.integers(len(daftar)))
    for i in range(jumlah):
        preset = daftar[(mulai + i) % len(daftar)]
        terbaik = None
        for percobaan in range(30):
            tonic = NADA[int(rng.integers(12))]
            if (preset, tonic) in terpakai and percobaan < 20:
                continue
            seed = int(rng.integers(1000, 99999))
            r, f = kandidat(preset, tonic, seed, menit)
            pembanding = lama + fitur_rencana
            skor = max((mirip.similarity(f, g)[0] for g in pembanding), default=0.0)
            if terbaik is None or skor < terbaik[0]:
                terbaik = (skor, preset, tonic, seed, r, f)
            if skor < BATAS_MIRIP:
                break
        skor, preset, tonic, seed, r, f = terbaik
        terpakai.add((preset, tonic))
        fitur_rencana.append(f)
        timbre = r["melody"]["timbre"] if r["mix"]["melody"] > 0 else "-"
        hindari = [k.get("judul", "") for k in baca_katalog()] + [v["judul"] for v in rencana]
        jd = judul.buat(r, None, None, tujuan if tujuan != "campur" else None, hindari=hindari)
        rencana.append({
            "no": i + 1, "preset": preset, "nama": r["name"], "nada": tonic, "seed": seed, "menit": menit,
            "suasana": SUASANA.get(r["key"]["mode"], r["key"]["mode"]),
            "bentuk": BENTUK.get(r["form"]["type"], r["form"]["type"]),
            "melodi": MELODI.get(timbre, timbre),
            "kemiripan_maks": round(skor, 3),
            "judul": jd["judul_en"][0], "judul_id": jd["judul_id"][0],
            "tujuan": tujuan if tujuan != "campur" else jd["tujuan"],
            "resep": r, "fitur": _feat_to_json(f),
        })
    return rencana


def tampilkan(rencana, log=print):
    log("")
    for v in rencana:
        log(f"  Video {v['no']}: {v['nama']}, nada {v['nada']} ({v['suasana']})")
        log(f"           melodi: {v['melodi']} · bentuk: {v['bentuk']} · {v['menit']} menit")
        log(f"           kemiripan dengan video lain: {v['kemiripan_maks']:.0%} "
            f"({mirip.verdict(v['kemiripan_maks'])})")
        log(f"           judul: {v['judul']}")
    log("")


# ---------- render ----------
def render(rencana, contoh=False, log=print, simpan_wav=False):
    from generate import render_resolved
    katalog = baca_katalog()
    hasil = []
    for v in rencana:
        menit = 2 if contoh else v["menit"]
        folder = os.path.join(OUT, ("contoh_" if contoh else "") +
                              f"{datetime.date.today():%Y%m%d}_{v['no']:02d}_{v['preset']}_{v['nada'].replace('#', 'is')}")
        os.makedirs(folder, exist_ok=True)
        stem = os.path.join(folder, f"{v['preset']}_{v['nada'].replace('#', 'is')}_{v['seed']}")
        log(f"\n[{v['no']}/{len(rencana)}] {v['judul']}" + ("  (contoh 2 menit)" if contoh else ""))
        r = json.loads(json.dumps(v["resep"]))
        _, _, _ = render_resolved(r, v["seed"], menit * 60, v["menit"] * 60, stem, log=log, keep_wav=simpan_wav)
        # judul final memakai audio yang sudah jadi (kecerahan terukur, jumlah nada, babak -> chapter)
        hindari = [k.get("judul", "") for k in katalog]
        jd = judul.dari_file(stem + ".toml", v.get("tujuan"), hindari=hindari)
        v["judul"], v["judul_id"] = jd["judul_en"][0], jd["judul_id"][0]
        with open(os.path.join(folder, "info.txt"), "w", encoding="utf-8") as f:
            f.write(info_text(v, contoh) + "\n" + judul.teks(jd))
        hasil.append(folder)
        if not contoh:
            # catat fitur lengkap (termasuk warna suara dari laporan kualitas)
            feat = mirip.load_render(stem)
            katalog.append({"tanggal": f"{datetime.datetime.now():%Y-%m-%d %H:%M}", "preset": v["preset"],
                            "nada": v["nada"], "seed": v["seed"], "folder": os.path.relpath(folder, ROOT),
                            "judul": v["judul"], "fitur": _feat_to_json(feat)})
            simpan_katalog(katalog)
    return hasil


def info_text(v, contoh):
    return f"""{v['judul']}
{'=' * len(v['judul'])}
{'CONTOH 2 MENIT. Versi penuh: python buat.py --lanjut' if contoh else ''}
Suasana : {v['suasana']} (nada dasar {v['nada']})
Melodi  : {v['melodi']}
Bentuk  : {v['bentuk']}
Durasi  : {v['menit']} menit
Nomor versi (seed): {v['seed']}

File untuk aplikasi video: file .mp3 di folder ini.
Resep untuk membuat ulang persis: file .toml di folder ini
  (python generate.py <file>.toml --duration {v['menit']})
"""


# ---------- tanya-jawab ----------
def tanya(prompt, pilihan=None, bawaan=None):
    while True:
        teks = input(f"{prompt}" + (f" [{bawaan}]" if bawaan is not None else "") + ": ").strip().lower()
        if not teks and bawaan is not None:
            return bawaan
        if pilihan is None or teks in pilihan:
            return teks
        print(f"  Pilih salah satu: {', '.join(pilihan)}")


def interaktif():
    print("\nSpacenight - pembuat musik untuk video\n")
    print("Musik untuk apa?")
    kunci = list(TUJUAN)
    for i, k in enumerate(kunci, 1):
        print(f"  {i}. {k}" + ("  (semua jenis)" if k == "campur" else ""))
    p = tanya("Nomor pilihan", [str(i) for i in range(1, len(kunci) + 1)], "1")
    tujuan = kunci[int(p) - 1]
    jumlah = int(tanya("Berapa video?", None, "1") or 1)
    menit = int(tanya("Berapa menit per video? (60 = 1 jam, 120 = 2 jam, 180 = 3 jam)", None, "60") or 60)
    contoh = tanya("Buat contoh 2 menit dulu untuk didengar? (y/t)", ["y", "t"], "y") == "y"
    return tujuan, jumlah, menit, contoh


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--untuk", choices=list(TUJUAN), help="tidur / fokus / belajar / santai / meditasi / campur")
    ap.add_argument("--jumlah", type=int, default=1, help="jumlah video")
    ap.add_argument("--menit", type=int, default=60, help="durasi tiap video (menit)")
    ap.add_argument("--contoh", action="store_true", help="buat contoh 2 menit dulu")
    ap.add_argument("--lanjut", action="store_true", help="buat versi penuh dari rencana/contoh terakhir")
    ap.add_argument("--ya", action="store_true", help="jangan minta konfirmasi")
    ap.add_argument("--simpan-wav", action="store_true", help="simpan juga WAV 24-bit (bawaan: hanya MP3)")
    a = ap.parse_args()

    if a.lanjut:
        if not os.path.exists(RENCANA):
            sys.exit("Belum ada rencana. Jalankan dulu: python buat.py --contoh")
        with open(RENCANA) as f:
            rencana = json.load(f)
        print("Membuat versi penuh dari rencana terakhir:")
        tampilkan(rencana)
        render(rencana, simpan_wav=a.simpan_wav)
        print(f"\nSelesai. Hasil ada di {OUT}")
        return

    if a.untuk:
        tujuan, jumlah, menit, contoh = a.untuk, a.jumlah, a.menit, a.contoh
    else:
        tujuan, jumlah, menit, contoh = interaktif()

    print("\nMenyusun rencana supaya tiap video berbeda...")
    rng = np.random.default_rng(int(time.time() * 1000) % 2**32)
    rencana = rencanakan(tujuan, jumlah, menit, rng)
    tampilkan(rencana)
    if not a.ya and a.untuk is None and tanya("Lanjut membuat? (y/t)", ["y", "t"], "y") != "y":
        return
    os.makedirs(os.path.dirname(RENCANA), exist_ok=True)
    with open(RENCANA, "w") as f:
        json.dump(rencana, f, indent=1)
    t0 = time.time()
    render(rencana, contoh=contoh, simpan_wav=a.simpan_wav)
    print(f"\nSelesai dalam {(time.time() - t0) / 60:.1f} menit. Hasil ada di {OUT}")
    if contoh:
        print("Dengarkan contohnya. Kalau suka, buat versi penuh dengan:  python buat.py --lanjut")


if __name__ == "__main__":
    main()
