"""Judul, deskripsi, chapter, dan tag YouTube yang sesuai dengan audio yang dihasilkan.

  python judul.py out/video/.../deep_sleep_C_66951.toml       # dari hasil render (pakai .events.json & .qc.json)

Judul dibangun dari hal yang memang ada di audio:
  - suasana tangga nada (lydian -> "Weightless", dorian -> "Wistful", ...)
  - kecerahan terukur (laporan QC) -> citra terang/netral/gelap (Aurora / Orbit / Deep Space)
  - suara melodi (bel kaca, kalimba, piano, tanpa melodi) dan seberapa sering melodi muncul
  - tujuan (tidur/fokus/belajar/santai/meditasi): dari buat.py, atau ditebak dari profil & isi lagu
  - durasi, bentuk lagu, dan babak (-> chapter YouTube)
Tidak pernah memakai klaim yang tidak benar (432 Hz, binaural, healing, ...): lihat "terlarang".
Hasilnya deterministik per nomor versi (seed).
"""
import json
import os
import sys
import tomllib

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(ROOT, "judul_kata.json"), encoding="utf-8") as _f:
    KATA = json.load(_f)
NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAX_LEN = 100   # batas judul YouTube


def durasi_label(menit):
    menit = int(round(menit))
    if menit % 60 == 0 and menit >= 60:
        j = menit // 60
        return (f"{j} Hour" + ("s" if j > 1 else "")), f"{j} Jam"
    return f"{menit} Minutes", f"{menit} Menit"


def ciri(r, events=None, qc=None):
    """Ringkasan ciri audio yang dipakai untuk judul."""
    mode = str(r["key"]["mode"]).lower()
    mel_on = r["mix"].get("melody", 0) > 0
    timbre = r["melody"]["timbre"] if mel_on else "-"
    menit = float(r.get("duration_min", 60))
    n_mel = None
    if events is not None:
        ev = [e if isinstance(e, dict) else e.__dict__ for e in events]
        total = max((e["start"] + e["dur"] for e in ev), default=menit * 60)
        n_mel = sum(e["layer"] == "melody" for e in ev) / max(total / 3600, 1e-6)
    # kecerahan: dari laporan QC kalau ada (pita presence relatif pink), kalau tidak dari pengaturan pad
    if qc and "bands_vs_pink_db" in qc:
        pres = qc["bands_vs_pink_db"]["presence"]
        terang = "terang" if pres > -12 else "gelap" if pres < -17 else "netral"
    else:
        b = float(r["pad"]["brightness"])
        terang = "terang" if b > 0.58 else "gelap" if b < 0.4 else "netral"
    profil = r.get("qc", {}).get("profile", "default")
    return dict(mode=mode, timbre=timbre, menit=menit, mel_per_jam=n_mel, terang=terang, profil=profil,
                bentuk=r["form"]["type"], tonic=r["key"]["tonic"], lufs=r["master"]["target_lufs"])


def tebak_tujuan(c):
    if c["profil"] == "sleep" or c["lufs"] <= -16:
        return "tidur"
    if c["timbre"] == "-":
        return "meditasi"
    if c["profil"] == "calm":
        return "santai" if c["mode"] != "phrygian" else "fokus"
    if c["mel_per_jam"] is not None and c["mel_per_jam"] > 120:
        return "belajar"
    return "fokus" if c["mode"] in ("dorian", "phrygian", "mixolydian") else "santai"


def _aman(t):
    low = t.lower()
    return all(w not in low for w in KATA["terlarang"]) and len(t) <= MAX_LEN


def _isi(tpl, d):
    t = tpl.format(**d)
    if len(t) > MAX_LEN:   # pendekkan: buang bagian durasi dalam kurung
        t = t.replace(f" ({d['durasi']})", "")
    return " ".join(t.split())


def buat(r, events=None, qc=None, tujuan=None, sections=None, n=5, hindari=()):
    """Kembalikan dict: judul_en, judul_id (daftar, terbaik dulu), deskripsi_en/id, chapter, tag, hashtag."""
    seed = int(r.get("seed", 0))
    rng = np.random.default_rng([seed, 30])
    c = ciri(r, events, qc)
    tujuan = tujuan or tebak_tujuan(c)
    T = KATA["tujuan"][tujuan]
    dur_en, dur_id = durasi_label(c["menit"])
    mood = KATA["mode"].get(c["mode"], KATA["mode"]["lydian"])
    cit = KATA["citra"][c["terang"]]
    mel = KATA["melodi"][c["timbre"]]
    hindari = {h.lower() for h in hindari}
    awal_terpakai = {" ".join(h.split()[:2]) for h in hindari}

    def kandidat(lang):
        out, pola_terpakai = [], set()
        tpls = KATA["templat"][lang]
        for _ in range(80):
            m = list(mood[lang]); rng.shuffle(m)
            ext = KATA["terang" if c["terang"] == "terang" else "gelap"][lang] if c["terang"] != "netral" else []
            ti = int(rng.integers(len(tpls)))
            if ti in pola_terpakai and len(pola_terpakai) < len(tpls):
                continue                      # tiap pola judul dipakai sekali dulu -> kandidat beragam
            citra = str(rng.choice(cit[lang]))
            if "{mood} {citra}" in tpls[ti] and len(citra.split()) > 1:
                continue                      # hindari "Dark Far Side of the Moon"
            if "Cosmic Drones" in tpls[ti] and c["timbre"] == "-":
                continue                      # hindari "Pure Drones & Cosmic Drones"
            d = dict(citra=citra, mood=m[0], mood2=m[1 % len(m)] if not ext else str(rng.choice(ext)),
                     melodi=mel[lang], tujuan=str(rng.choice(T[lang])), verb=T["verb_en"],
                     durasi=dur_en if lang == "en" else dur_id)
            kata_citra = {w.lower() for w in citra.split()}
            if d["mood"].lower() in kata_citra or d["mood2"].lower() in kata_citra or d["mood"] == d["mood2"]:
                continue                      # hindari "Dark Matter — Dark Ambient"
            t = _isi(tpls[ti], d)
            if lang == "id":
                t = t.replace("yang " + d["mood"], "yang " + d["mood"].lower())
            key = t.lower()
            if (_aman(t) and key not in hindari and " ".join(key.split()[:2]) not in awal_terpakai
                    and t not in out):
                out.append(t)
                pola_terpakai.add(ti)
            if len(out) >= n:
                break
        # paling disukai: panjang 50-80 karakter (lengkap tapi tidak terpotong di layar HP)
        return sorted(out, key=lambda t: abs(len(t) - 65))

    judul_en, judul_id = kandidat("en"), kandidat("id")
    chapter = chapters(c["menit"] * 60, sections, rng)
    bentuk = KATA["bentuk"].get(c["bentuk"], KATA["bentuk"]["arc"])
    kunci = f"{c['tonic']} {c['mode']}"
    frasa_en = {"glass": "glass bells", "kalimba": "kalimba notes", "piano": "soft piano notes", "soft": "soft tones"}
    mel_en = ("Sparse " + frasa_en.get(c["timbre"], "notes") + " drift above slow pads and deep drones" if c["timbre"] != "-"
              else "Slow pads and deep drones with no melody, so nothing pulls your attention")
    mel_id = (mel["id"].capitalize() + " sesekali terdengar di atas pad yang pelan dan dengung yang dalam" if c["timbre"] != "-"
              else "Pad yang pelan dan dengung yang dalam tanpa melodi, sehingga tidak ada yang menarik perhatian")
    vol_en = "kept quieter for sleep" if c["lufs"] <= -16 else "at a steady volume"
    vol_id = "dibuat lebih pelan untuk tidur" if c["lufs"] <= -16 else "dengan volume yang stabil"
    chap_txt = "\n".join(f"{ts} {nm_en}" for ts, nm_en, _ in chapter)
    chap_txt_id = "\n".join(f"{ts} {nm_id}" for ts, _, nm_id in chapter)
    tag_tujuan = {"tidur": ("sleep music", "#sleepmusic"), "fokus": ("focus music", "#focusmusic"),
                  "belajar": ("study music", "#studymusic"), "santai": ("relaxing music", "#relaxingmusic"),
                  "meditasi": ("meditation music", "#meditationmusic")}[tujuan]
    deskripsi_en = (
        f"{dur_en} of {mood['en'][0].lower()} space ambient for {T['en'][0].lower()}. {mel_en}. "
        f"The music is {bentuk['en']}, in {kunci}, mastered {vol_en} with no sudden changes.\n\n"
        "Made with original synthesizers and a generative process. No samples or stock music.\n"
        + (f"\nChapters\n{chap_txt}\n" if chapter else ""))
    deskripsi_id = (
        f"{dur_id} musik ambient luar angkasa yang {mood['id'][0].lower()} untuk {T['id'][0].lower()}. {mel_id}. "
        f"Musiknya {bentuk['id']}, dalam nada {kunci}, {vol_id} tanpa perubahan mendadak.\n\n"
        "Dibuat dengan synth dan proses generatif buatan sendiri, tanpa sampel atau musik orang lain.\n"
        + (f"\nBabak\n{chap_txt_id}\n" if chapter else ""))
    tag = ["ambient", "space ambient", "ambient music", tag_tujuan[0], mel["en"].lower(), "space music",
           "calm music", f"{dur_en.lower()} ambient"]
    hashtag = ["#ambient", "#spacemusic", tag_tujuan[1]]
    return dict(tujuan=tujuan, judul_en=judul_en, judul_id=judul_id, deskripsi_en=deskripsi_en,
                deskripsi_id=deskripsi_id, chapter=chapter, tag=tag, hashtag=hashtag, ciri=c)


def chapters(total, sections, rng):
    """Chapter YouTube dari babak lagu: mulai 0:00, minimal 3, masing-masing >= 10 detik, nama tidak berulang."""
    if sections is None or total < 10 * 60:
        return []
    starts = [s["start"] for s in sections.list if s["start"] < total - 60]
    if len(starts) < 3:
        return []
    rest = list(range(1, len(KATA["babak"]["en"])))   # 0 = "Arrival"/"Tiba" untuk babak pertama
    rng.shuffle(rest)
    idx = [0] + [rest[i % len(rest)] for i in range(len(starts) - 1)]
    jam = max(starts) >= 3600
    out = []
    for st, j in zip(starts, idx):
        h, m, s = int(st // 3600), int(st % 3600 // 60), int(st % 60)
        ts = f"{h}:{m:02d}:{s:02d}" if jam else f"{m}:{s:02d}"
        out.append((ts, KATA["babak"]["en"][j], KATA["babak"]["id"][j]))
    return out


def teks(hasil):
    """Format siap salin untuk file .judul.txt / info.txt."""
    L = ["JUDUL (Inggris) - pilih salah satu:"] + [f"  {i + 1}. {t}" for i, t in enumerate(hasil["judul_en"])]
    L += ["", "JUDUL (Indonesia):"] + [f"  {i + 1}. {t}" for i, t in enumerate(hasil["judul_id"])]
    L += ["", "DESKRIPSI (Inggris):", hasil["deskripsi_en"], "DESKRIPSI (Indonesia):", hasil["deskripsi_id"],
          "TAG: " + ", ".join(hasil["tag"]), "HASHTAG: " + " ".join(hasil["hashtag"])]
    return "\n".join(L) + "\n"


def dari_file(path_toml, tujuan=None, hindari=()):
    """Judul untuk hasil render yang sudah ada (pakai .events.json & .qc.json di sampingnya)."""
    import config
    import form
    import settings
    stem = os.path.splitext(path_toml)[0]
    with open(path_toml, "rb") as f:
        r = tomllib.load(f)
    events = json.load(open(stem + ".events.json")) if os.path.exists(stem + ".events.json") else None
    qc = json.load(open(stem + ".qc.json")) if os.path.exists(stem + ".qc.json") else None
    settings.apply(r)
    total = float(r.get("duration_min", 60)) * 60
    secs = form.Sections(total, int(r["seed"]), config.VARIATION, r["mix"].get("melody", 0) > 0) if config.VARIATION > 0 else None
    return buat(r, events, qc, tujuan, secs, hindari=hindari)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    print(teks(dari_file(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)))
