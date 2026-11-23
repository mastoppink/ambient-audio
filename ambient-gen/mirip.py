"""Seberapa mirip dua lagu? Untuk memastikan tiap video cukup berbeda sebelum diunggah.

  python mirip.py out/a.toml out/b.toml        # bandingkan dua hasil render (pakai .events.json & .qc.json)
  python mirip.py out/                         # bandingkan semua hasil di folder, tampilkan yang terlalu mirip

Skor 0-100%:
  < 60%  jelas berbeda
  60-75% agak mirip (masih wajar untuk satu channel dengan gaya yang sama)
  > 75%  terlalu mirip: pilih nada dasar / preset / bentuk lain

Yang dibandingkan (dan bobotnya):
  nada yang dipakai sepanjang lagu (termasuk nada dasar) 35%
  urutan chord (pasangan chord berurutan)                 20%
  keseimbangan suara per pita frekuensi (kalau ada audio) 25%
  suara melodi sama?                                     10%
  bentuk lagu sama?                                      10%
"""
import glob
import itertools
import json
import os
import sys
import tomllib
from collections import Counter

import numpy as np


def features(resolved, events):
    """resolved: preset final (dict). events: daftar event (dict atau Event)."""
    ev = [e if isinstance(e, dict) else e.__dict__ for e in events]
    pc = np.zeros(12)
    for e in ev:
        if e["layer"] in ("pad", "melody", "drone"):
            pc[e["midi"] % 12] += e["dur"] * (0.5 if e["layer"] == "drone" else 1.0)
    pads = sorted({(e["start"], e["label"]) for e in ev if e["layer"] == "pad"})
    # label chord + nada akar, mis. "II(E)": nada dasar ikut menentukan
    seq = [lab for _, lab in pads]
    bigrams = Counter(zip(seq, seq[1:]))
    return {"pc": pc / (np.linalg.norm(pc) + 1e-12), "bigrams": bigrams,
            "timbre": resolved.get("melody", {}).get("timbre") if resolved.get("mix", {}).get("melody", 1) > 0 else "-",
            "form": resolved.get("form", {}).get("type"), "bands": None}


def load_render(stem):
    """stem = path tanpa ekstensi (mis. out/nebula_s2001_3600s)."""
    with open(stem + ".toml", "rb") as f:
        r = tomllib.load(f)
    with open(stem + ".events.json") as f:
        ev = json.load(f)
    feat = features(r, ev)
    if os.path.exists(stem + ".qc.json"):
        with open(stem + ".qc.json") as f:
            feat["bands"] = json.load(f).get("bands_vs_pink_db")
    feat["name"] = os.path.basename(stem)
    return feat


def _cos_counter(a, b):
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    va = np.array([a.get(k, 0) for k in keys], float)
    vb = np.array([b.get(k, 0) for k in keys], float)
    return float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-12))


def similarity(fa, fb):
    """Skor kemiripan 0..1 dan rinciannya."""
    parts = {
        "nada": (0.35, float(np.clip(fa["pc"] @ fb["pc"], 0, 1))),
        "urutan chord": (0.20, _cos_counter(fa["bigrams"], fb["bigrams"])),
        "suara melodi": (0.10, 1.0 if fa["timbre"] == fb["timbre"] else 0.0),
        "bentuk lagu": (0.10, 1.0 if fa["form"] == fb["form"] else 0.0),
    }
    if fa.get("bands") and fb.get("bands"):
        d = np.mean([abs(fa["bands"][k] - fb["bands"][k]) for k in fa["bands"] if k in fb["bands"]])
        parts["warna suara"] = (0.25, float(np.exp(-d / 4)))
    tot_w = sum(w for w, _ in parts.values())
    score = sum(w * v for w, v in parts.values()) / tot_w
    return score, {k: v for k, (w, v) in parts.items()}


def verdict(score):
    if score > 0.75:
        return "TERLALU MIRIP"
    if score >= 0.60:
        return "agak mirip"
    return "jelas berbeda"


def main():
    args = sys.argv[1:]
    if len(args) == 1 and os.path.isdir(args[0]):
        stems = sorted(p[:-len(".events.json")] for p in glob.glob(os.path.join(args[0], "**", "*.events.json"),
                                                                    recursive=True)
                       if os.path.exists(p[:-len(".events.json")] + ".toml"))
    else:
        stems = [os.path.splitext(a)[0] for a in args]
    if len(stems) < 2:
        print(__doc__)
        return
    feats = [load_render(s) for s in stems]
    rows = []
    for a, b in itertools.combinations(feats, 2):
        score, parts = similarity(a, b)
        rows.append((score, a["name"], b["name"], parts))
    rows.sort(reverse=True)
    for score, na, nb, parts in rows:
        detail = ", ".join(f"{k} {v:.0%}" for k, v in parts.items())
        print(f"{score:4.0%}  {verdict(score):14s} {na}  <->  {nb}\n       ({detail})")


if __name__ == "__main__":
    main()
