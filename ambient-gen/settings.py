"""Preset: muat TOML, gabung dengan default, terapkan override, lalu terjemahkan
kontrol makro (brightness, width, density, ...) ke parameter teknis di `config`.

Aturan nilai:
- angka biasa           -> dipakai apa adanya
- [min, max] pada angka -> dipilih acak (seragam) berdasarkan seed
  (kecuali kunci yang memang berupa rentang, lihat RANGE_KEYS)
- ["a", "b", ...] teks   -> salah satu dipilih acak berdasarkan seed
"""
import copy
import tomllib

import numpy as np

import config

MODES = {  # hanya mode dengan kuint murni, supaya drone tonika+kuint selalu konsonan
    "ionian":     [0, 2, 4, 5, 7, 9, 11],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "phrygian":   [0, 1, 3, 5, 7, 8, 10],
    "lydian":     [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "aeolian":    [0, 2, 3, 5, 7, 8, 10],
}
NOTES = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6,
         "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}

DEFAULTS = {
    "name": "Default",
    "seed": config.SEED,
    "duration_min": 10,
    "key": {"tonic": "D", "mode": "lydian"},
    "mix": {"drone": 0.8, "pad": 0.55, "melody": 0.22, "texture": 0.05},
    "pad": {
        "brightness": 0.55,          # 0 gelap .. 1 terang (cutoff + kadar saw)
        "width": 0.5,                # 0 sempit .. 1 lebar (detune + stereo)
        "movement": 0.5,             # 0 statis .. 1 bergerak (kecepatan LFO filter)
        "chord_seconds": [50, 80],
        "chord_weights": {},         # mis. {II = 4.0, vii = 0}
    },
    "drone": {"brightness": 0.3},
    "melody": {
        "density": 0.67,             # 0 sangat jarang .. 1 cukup sering
        "decay": 9.0,
        "register": 0.5,             # 0 rendah .. 1 tinggi
    },
    "texture": {"brightness": 0.5},
    "space": {
        "reverb_decay": 11.0,        # detik
        "reverb_mix": 0.5,           # 0 kering .. 1 sangat basah
        "delay_feedback": 0.3,
    },
    "master": {"target_lufs": -16.0},
}
RANGE_KEYS = {("pad", "chord_seconds")}


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_override(text):
    """'melody.density=0.5' -> ({'melody': {'density': 0.5}})"""
    key, _, raw = text.partition("=")
    if not _:
        raise ValueError(f"override harus berbentuk kunci=nilai: {text!r}")
    try:
        value = tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        value = raw  # teks biasa, mis. mode=dorian
    d = node = {}
    parts = key.strip().split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value
    return d


def load(path=None, overrides=()):
    preset = {}
    if path:
        with open(path, "rb") as f:
            preset = tomllib.load(f)
    s = deep_merge(DEFAULTS, preset)
    for o in overrides:
        s = deep_merge(s, parse_override(o))
    return s


def resolve(s, seed):
    """Pilih nilai acak untuk setiap [min, max]; hasilnya hanya angka. Deterministik per seed."""
    rng = np.random.default_rng([seed, 0])

    def walk(node, path):
        out = {}
        for k, v in node.items():
            p = path + (k,)
            if isinstance(v, dict) and k != "chord_weights":
                out[k] = walk(v, p)
            elif (isinstance(v, list) and len(v) == 2 and p not in RANGE_KEYS
                  and all(isinstance(x, (int, float)) for x in v)):
                out[k] = round(float(rng.uniform(*sorted(v))), 4)
            elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                out[k] = str(v[rng.integers(len(v))])   # daftar teks -> pilih satu
            else:
                out[k] = v
        return out

    r = walk(s, ())
    r["seed"] = seed
    return r


def _lerp_log(lo, hi, x):
    return lo * (hi / lo) ** x


def apply(r):
    """Terjemahkan preset yang sudah di-resolve ke parameter teknis di modul config."""
    mode = str(r["key"]["mode"]).lower()
    tonic = str(r["key"]["tonic"]).upper()
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} tidak dikenal; pilih: {', '.join(MODES)}")
    if tonic not in NOTES:
        raise ValueError(f"tonika {tonic!r} tidak dikenal")
    pc = NOTES[tonic]
    t = 48 + pc if pc <= 5 else 36 + pc        # tonika di rentang F#2..F3 -> pad tidak terlalu tinggi
    t += 12 if t < 46 else 0                    # tapi tidak terlalu rendah (keruh)
    config.TONIC_MIDI = t
    config.SCALE = MODES[mode]
    config.DRONE_NOTES = [t - 12, t - 5]
    config.PAD_RANGE = (t + 2, t + 24)

    mix = r["mix"]
    pad = r["pad"]
    b, w, mv = pad["brightness"], pad["width"], pad["movement"]
    cut_max = _lerp_log(900, 4500, b)
    config.PAD = dict(config.PAD,
                      cutoff_max=cut_max, cutoff_min=cut_max * 0.23,
                      saw_mix=0.25 + 0.5 * b,
                      detune_cents=3 + 12 * w, stereo_spread=0.1 + 0.5 * w,
                      lfo_period=_lerp_log(120, 20, mv))
    config.PAD_LEVEL = mix["pad"]
    config.CHORD_SECONDS = tuple(pad["chord_seconds"])
    config.CHORD_OVERLAP = min(12.0, config.CHORD_SECONDS[0] * 0.3)
    config.CHORD_WEIGHTS = dict(pad.get("chord_weights", {}))

    db = r["drone"]["brightness"]
    dmax = _lerp_log(300, 1500, db)
    config.DRONE = dict(config.DRONE, cutoff_max=dmax, cutoff_min=dmax * 0.28)
    config.DRONE_LEVEL = mix["drone"]

    m = r["melody"]
    mean_gap = 8 + 60 * (1 - m["density"])
    lo = t + 12 + round(12 * m["register"])
    config.MELODY = dict(config.MELODY, gap=(mean_gap * 0.5, mean_gap * 1.5),
                         range=(lo, lo + 24), decay=m["decay"], level=mix["melody"])

    tb = r["texture"]["brightness"]
    config.TEXTURE = dict(config.TEXTURE, level=mix["texture"],
                          band_lo=_lerp_log(120, 600, tb), band_hi=_lerp_log(1500, 7000, tb))

    sp = r["space"]
    config.FX = dict(config.FX, reverb_decay=sp["reverb_decay"], delay_feedback=sp["delay_feedback"],
                     target_lufs=r["master"]["target_lufs"])
    config.MIX = dict(dry=1 - 0.5 * sp["reverb_mix"], wet=2 * sp["reverb_mix"])


def to_toml(d, prefix=""):
    """Penulis TOML minimal (cukup untuk preset: angka, teks, list, tabel bersarang)."""
    def val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return '"' + v.replace('"', '\\"') + '"'
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(val(x) for x in v) + "]"
        if isinstance(v, dict):
            return "{" + ", ".join(f"{k} = {val(x)}" for k, x in v.items()) + "}"
        return repr(v)

    lines, tables = [], []
    for k, v in d.items():
        if isinstance(v, dict) and k != "chord_weights":
            tables.append((k, v))
        else:
            lines.append(f"{k} = {val(v)}")
    for k, v in tables:
        name = f"{prefix}{k}"
        lines.append(f"\n[{name}]")
        lines.append(to_toml(v, name + ".").strip())
    return "\n".join(lines) + "\n"
