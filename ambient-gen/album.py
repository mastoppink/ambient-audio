"""Mode album: sekali jalan membuat satu album track pendek yang serasi, siap dijual.

  python album.py                                        # tanya-jawab langkah demi langkah
  python album.py --fungsi tidur --jumlah 10 --menit 4   # langsung
  python album.py --fungsi fokus --nama "Deep Field Work" --artis "Spacenight" --nada D
  python album.py --fungsi santai --rencana              # hanya tampilkan rencana, tanpa render

Satu album = satu fungsi (tidur / meditasi / fokus / santai). Supaya terasa satu karya:
  - nada dasar hanya dari satu "keluarga": nada rumah, kwint (+7), dan kwart (+5) di atasnya
  - volume semua track sama (satu target LUFS untuk seluruh album)
  - preset hanya dari fungsi itu, bergiliran, dengan nomor versi yang dipilih supaya track tidak mirip
Supaya cocok sebagai track (bukan video berjam-jam):
  - pembukaan & penutup lebih singkat, gelombang intensitas dan pergantian chord lebih rapat
  - fade-out 12 detik

Hasil di out/album/<tanggal>_<nama>/:
  NN - Judul.wav         WAV 16-bit 44,1 kHz (format standar distributor: DistroKid, TuneCore, CD Baby, ...)
  NN - Judul.mp3         MP3 320 kbps bertag (judul, artis, album, nomor track)
  album.txt              daftar track, durasi, nada, dan catatan untuk distributor
  resep/                 file .toml tiap track (membuat ulang persis) + laporan kualitas
  stok/                  (dengan --stok) tiap track: (30s), (60s), (Loop 60s) WAV 16-bit 44,1 kHz
  master/                (dengan --master) WAV 24-bit 48 kHz asli
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

import config
import form
import mirip
import settings
from compose import compose

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out", "album")
KATALOG = os.path.join(OUT, "katalog_album.json")
KATA = json.load(open(os.path.join(ROOT, "album_kata.json"), encoding="utf-8"))

FUNGSI = {
    "tidur": ["deep_sleep", "lunar_haze", "starlight_lullaby"],
    "meditasi": ["meditation", "deep_space"],
    "fokus": ["satellite", "drift", "orbit"],
    "santai": ["nebula", "aurora", "solitude"],
}
GENRE = {"tidur": "Ambient", "meditasi": "Ambient", "fokus": "Ambient", "santai": "Ambient"}
NADA = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BATAS_MIRIP = 0.55
FADE_OUT = 12.0


# ---------- penyesuaian preset menjadi track ----------
def jadikan_track(r, menit, target_lufs):
    """Ubah resep video panjang menjadi resep track pendek (dipanggil setelah resolve)."""
    r["duration_min"] = menit
    f = r["form"]
    f["intro_min"] = round(min(0.6, menit * 0.12), 2)
    f["outro_min"] = round(min(1.0, menit * 0.2), 2)
    f["period_min"] = [round(menit * 0.6, 2), round(menit * 1.3, 2)]   # satu gelombang kira-kira sepanjang track
    lo, hi = r["pad"]["chord_seconds"]
    r["pad"]["chord_seconds"] = [max(25, round(lo * 0.55)), max(35, round(hi * 0.55))]
    # penipisan melodi untuk video tidur berjam-jam; di track pendek cukup tipis
    r["melody"]["thin_end"] = min(float(r["melody"].get("thin_end", 0.0)), 0.3)
    r["master"]["target_lufs"] = target_lufs
    return r


def target_album(presets):
    """Satu target loudness untuk seluruh album: yang paling pelan di antara preset-nya."""
    return min(settings.load(os.path.join(ROOT, "presets", f"{p}.toml"))["master"]["target_lufs"]
               for p in presets)


def kandidat(preset, tonic, seed, menit, target):
    raw = settings.load(os.path.join(ROOT, "presets", f"{preset}.toml"), [f'key.tonic="{tonic}"'])
    r = jadikan_track(settings.resolve(raw, seed), menit, target)
    settings.apply(r)
    total = menit * 60
    config.SONG_TOTAL = total
    config.SHAPE = form.make_shape(total, seed, r["form"])
    config.SECTIONS = form.Sections(total, seed, config.VARIATION, config.MELODY["level"] > 0) \
        if config.VARIATION > 0 else None
    return r, mirip.features(r, compose(total, seed, with_melody=True))


# ---------- katalog nama (supaya nama track tidak pernah dipakai dua kali) ----------
def baca_katalog():
    if os.path.exists(KATALOG):
        with open(KATALOG, encoding="utf-8") as f:
            return json.load(f)
    return []


def nama_terpakai():
    return {t["judul"] for a in baca_katalog() for t in a["track"]} | {a["album"] for a in baca_katalog()}


def pilih_nama(pool, terpakai, rng, n):
    sisa = [x for x in pool if x not in terpakai]
    if len(sisa) < n:   # bank habis: pakai ulang dengan angka romawi
        sisa += [f"{x} II" for x in pool if f"{x} II" not in terpakai]
    idx = rng.permutation(len(sisa))[:n]
    return [sisa[i] for i in idx]


# ---------- rencana ----------
def rencanakan(fungsi, jumlah, menit, rng, nada=None, nama=None, log=print):
    presets = FUNGSI[fungsi]
    target = target_album(presets)
    rumah = NADA.index(nada.upper()) if nada else int(rng.integers(12))
    keluarga = [NADA[rumah], NADA[(rumah + 7) % 12], NADA[(rumah + 5) % 12]]
    terpakai = nama_terpakai()
    judul = pilih_nama(KATA["track"][fungsi], terpakai, rng, jumlah)
    album = nama or pilih_nama(KATA["album"][fungsi], terpakai, rng, 1)[0]
    rencana, fitur = [], []
    kombinasi = set()
    for i in range(jumlah):
        preset = presets[i % len(presets)]
        # nada: berputar di keluarga, geser supaya pasangan preset+nada tidak berulang selama masih ada
        k = (i + i // len(presets)) % 3   # track berurutan beda nada
        urut = keluarga[k:] + keluarga[:k]
        tonic = next((t for t in urut if (preset, t) not in kombinasi), urut[0])
        kombinasi.add((preset, tonic))
        terbaik = None
        for _ in range(12):
            seed = int(rng.integers(1000, 99999))
            r, f = kandidat(preset, tonic, seed, menit, target)
            skor = max((mirip.similarity(f, g)[0] for g in fitur), default=0.0)
            if terbaik is None or skor < terbaik[0]:
                terbaik = (skor, seed, r, f)
            if skor < BATAS_MIRIP:
                break
        skor, seed, r, f = terbaik
        fitur.append(f)
        rencana.append({"preset": preset, "nama_preset": r["name"], "nada": tonic, "seed": seed,
                        "menit": menit, "kemiripan_maks": round(skor, 3), "terang": float(r["pad"]["brightness"]),
                        "resep": r})
    # urutan: album tidur/meditasi makin gelap menuju akhir; fokus/santai tetap bergiliran
    if fungsi in ("tidur", "meditasi"):
        rencana.sort(key=lambda v: -v["terang"])
    for i, v in enumerate(rencana):
        v["no"], v["judul"] = i + 1, judul[i]
    return {"album": album, "fungsi": fungsi, "target_lufs": target, "keluarga_nada": keluarga, "track": rencana}


def tampilkan(rc, log=print):
    log(f"\nAlbum  : {rc['album']}  ({rc['fungsi']}, {len(rc['track'])} track)")
    log(f"Nada   : {', '.join(rc['keluarga_nada'])} (satu keluarga)   Volume: {rc['target_lufs']:.0f} LUFS semua track")
    for v in rc["track"]:
        log(f"  {v['no']:2d}. {v['judul']:<24s} {v['nama_preset']:<18s} nada {v['nada']:<3s} "
            f"{v['menit']} menit   kemiripan {v['kemiripan_maks']:.0%}")
    log("")


# ---------- render & ekspor ----------
def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()


def _aman(s):
    return re.sub(r'[\\/:*?"<>|]', "", s)


def _durasi(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


def render(rc, artis, master=False, stok=False, log=print):
    from generate import render_resolved
    from pipeline import _mp3_true_peak
    folder = os.path.join(OUT, f"{datetime.date.today():%Y%m%d}_{_slug(rc['album'])}")
    resep = os.path.join(folder, "resep")
    os.makedirs(resep, exist_ok=True)
    if master:
        os.makedirs(os.path.join(folder, "master"), exist_ok=True)
    n = len(rc["track"])
    for v in rc["track"]:
        nama = f"{v['no']:02d} - {_aman(v['judul'])}"
        stem = os.path.join(resep, f"{v['no']:02d}_{v['preset']}_{v['nada'].replace('#', 'is')}_{v['seed']}")
        log(f"\n[{v['no']}/{n}] {v['judul']}  ({v['nama_preset']}, nada {v['nada']})")
        r = json.loads(json.dumps(v["resep"]))
        render_resolved(r, v["seed"], v["menit"] * 60, v["menit"] * 60, stem, log=log, keep_wav=True,
                        fade_out=FADE_OUT, titles=False)
        tag = ["-metadata", f"title={v['judul']}", "-metadata", f"artist={artis}",
               "-metadata", f"album_artist={artis}", "-metadata", f"album={rc['album']}",
               "-metadata", f"track={v['no']}/{n}", "-metadata", f"genre={GENRE[rc['fungsi']]}",
               "-metadata", f"date={datetime.date.today():%Y}"]
        wav16 = os.path.join(folder, nama + ".wav")
        # 48 kHz/24-bit -> 44,1 kHz/16-bit: resampler soxr presisi tinggi + dither segitiga (TPDF)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", stem + ".wav", "-af",
                        "aresample=44100:resampler=soxr:precision=28:dither_method=triangular",
                        "-c:a", "pcm_s16le", *tag, wav16], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", stem + ".mp3", "-c", "copy",
                        "-id3v2_version", "3", *tag, os.path.join(folder, nama + ".mp3")], check=True)
        os.remove(stem + ".mp3")
        if stok:   # versi edit untuk stock music: 30 detik, 60 detik, loop mulus
            import stok as stok_mod
            stok_mod.buat_semua(stem, os.path.join(folder, "stok"), nama, rc["target_lufs"],
                                tag[2:8] + tag[10:], log=log)
        if master:
            shutil.move(stem + ".wav", os.path.join(folder, "master", nama + " (24-bit 48 kHz).wav"))
        else:
            os.remove(stem + ".wav")
        v["true_peak_wav16"] = round(_mp3_true_peak(wav16), 2)
        v["durasi_detik"] = round(_durasi(wav16), 1)
        log(f"  -> {nama}.wav / .mp3   (true peak WAV 16-bit {v['true_peak_wav16']:.1f} dBTP)")
    with open(os.path.join(folder, "album.txt"), "w", encoding="utf-8") as f:
        f.write(album_txt(rc, artis))
    with open(os.path.join(resep, "rencana.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in rc.items()}, f, indent=1, ensure_ascii=False)
    kat = baca_katalog()
    kat.append({"tanggal": f"{datetime.datetime.now():%Y-%m-%d %H:%M}", "album": rc["album"],
                "fungsi": rc["fungsi"], "folder": os.path.relpath(folder, ROOT),
                "track": [{"judul": v["judul"], "preset": v["preset"], "nada": v["nada"], "seed": v["seed"]}
                          for v in rc["track"]]})
    with open(KATALOG, "w", encoding="utf-8") as f:
        json.dump(kat, f, indent=1, ensure_ascii=False)
    return folder


def _mmss(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def album_txt(rc, artis):
    total = sum(v.get("durasi_detik", v["menit"] * 60) for v in rc["track"])
    baris = [f"{rc['album']}", "=" * len(rc["album"]), "",
             f"Artis   : {artis}", f"Genre   : {GENRE[rc['fungsi']]} (sub-genre: space ambient, {rc['fungsi']})",
             f"Track   : {len(rc['track'])}  ·  total {_mmss(total)}",
             f"Volume  : {rc['target_lufs']:.0f} LUFS terintegrasi tiap track, true peak di bawah -1 dBTP",
             f"Nada    : keluarga {', '.join(rc['keluarga_nada'])}", "", "Daftar track", "------------"]
    for v in rc["track"]:
        baris.append(f"{v['no']:2d}. {v['judul']:<26s} {_mmss(v.get('durasi_detik', v['menit'] * 60))}"
                     f"   ({v['nama_preset']}, nada {v['nada']}, seed {v['seed']})")
    baris += ["", "Catatan untuk distributor", "-------------------------",
              "- Unggah file .wav (16-bit, 44,1 kHz, stereo). File .mp3 untuk didengar atau dibagikan.",
              "- Semua suara dibuat dari sintesis (tanpa sampel, tanpa vokal, tanpa karya orang lain).",
              "- Kalau ditanya soal AI: musik ini dibuat dengan program sintesis algoritmik buatan sendiri,",
              "  bukan model AI generatif. Tetap baca kebijakan distributor terbaru sebelum mengunggah.",
              "- Folder stok/ (kalau ada): versi 30 detik, 60 detik, dan loop 60 detik untuk situs stock music.",
              "  File Loop bisa diputar berulang tanpa sambungan terdengar.",
              "- Sampul album (cover) minimal 3000x3000 piksel, dibuat terpisah.",
              "- Membuat ulang satu track persis: python generate.py resep/<file>.toml"]
    return "\n".join(baris) + "\n"


# ---------- tanya-jawab ----------
def tanya(prompt, pilihan=None, bawaan=None):
    while True:
        teks = input(f"{prompt}" + (f" [{bawaan}]" if bawaan is not None else "") + ": ").strip()
        if not teks and bawaan is not None:
            return bawaan
        if pilihan is None or teks.lower() in pilihan:
            return teks
        print(f"  Pilih salah satu: {', '.join(pilihan)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fungsi", choices=list(FUNGSI), help="tidur / meditasi / fokus / santai")
    ap.add_argument("--jumlah", type=int, default=10, help="jumlah track (bawaan 10)")
    ap.add_argument("--menit", type=float, default=4, help="durasi tiap track dalam menit (bawaan 4)")
    ap.add_argument("--nama", help="nama album (bawaan: dipilih otomatis)")
    ap.add_argument("--artis", default="Spacenight", help="nama artis di tag file")
    ap.add_argument("--nada", choices=NADA + [n.lower() for n in NADA], help="nada rumah album (bawaan: acak)")
    ap.add_argument("--stok", action="store_true", help="buat juga versi 30 detik, 60 detik, dan loop untuk stock music")
    ap.add_argument("--master", action="store_true", help="simpan juga WAV 24-bit 48 kHz asli")
    ap.add_argument("--rencana", action="store_true", help="hanya tampilkan rencana, tanpa render")
    ap.add_argument("--ya", action="store_true", help="jangan minta konfirmasi")
    a = ap.parse_args()

    if not a.fungsi:
        print("\nSpacenight - mode album\n\nAlbum untuk apa?")
        kunci = list(FUNGSI)
        for i, k in enumerate(kunci, 1):
            print(f"  {i}. {k}")
        a.fungsi = kunci[int(tanya("Nomor pilihan", [str(i) for i in range(1, 5)], "1")) - 1]
        a.jumlah = int(tanya("Berapa track?", None, "10"))
        a.menit = float(tanya("Berapa menit per track?", None, "4"))
        a.nama = tanya("Nama album (kosongkan = otomatis)", None, "") or None
        a.artis = tanya("Nama artis", None, a.artis)

    print("\nMenyusun rencana album...")
    rng = np.random.default_rng(int(time.time() * 1000) % 2**32)
    rc = rencanakan(a.fungsi, a.jumlah, a.menit, rng, nada=a.nada, nama=a.nama)
    tampilkan(rc)
    if a.rencana:
        return
    if not a.ya and sys.stdin.isatty() and tanya("Lanjut membuat? (y/t)", ["y", "t"], "y").lower() != "y":
        return
    t0 = time.time()
    folder = render(rc, a.artis, master=a.master, stok=a.stok)
    print(f"\nSelesai dalam {(time.time() - t0) / 60:.1f} menit. Hasil ada di {folder}")


if __name__ == "__main__":
    main()
