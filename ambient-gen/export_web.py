"""Ekspor preset + tabel EQ ke web/presets.json, supaya versi web memakai sumber yang sama.

  python export_web.py        # jalankan setiap kali preset atau config.EQ berubah
"""
import json
import pathlib

import config
import settings

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT.parent / "web" / "presets.json"

# urut per fungsi: tidur, meditasi, fokus, santai
ORDER = ["deep_sleep", "starlight_lullaby", "lunar_haze", "meditation", "deep_space",
         "orbit", "drift", "satellite", "nebula", "aurora", "solitude"]


def build():
    presets = {}
    files = sorted((ROOT / "presets").glob("*.toml"), key=lambda p: (ORDER.index(p.stem)
                   if p.stem in ORDER else 99, p.stem))
    for f in files:
        presets[f.stem] = settings.load(f)        # nilai mentah: rentang [min, max] dipertahankan
    return {"defaults": settings.DEFAULTS, "presets": presets, "eq": config.EQ,
            "melody_attack": config.MELODY["attack"], "delay_seconds": config.FX["delay_seconds"],
            "delay_mix": config.FX["delay_mix"], "reverb_hp": config.FX["reverb_hp"],
            "reverb_predelay": config.FX["reverb_predelay"], "send": config.FX["send"],
            "pad_base": {k: config.PAD[k] for k in ("n_osc", "attack", "release")},
            "drone_base": {k: config.DRONE[k] for k in ("n_osc", "detune_cents", "saw_mix",
                                                        "attack", "release", "lfo_period")},
            "texture_base": {"lfo_periods": list(config.TEXTURE["lfo_periods"])},
            "judul": json.load(open(ROOT / "judul_kata.json", encoding="utf-8"))}


def main():
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False))
    print(f"tulis {OUT}")


if __name__ == "__main__":
    main()
