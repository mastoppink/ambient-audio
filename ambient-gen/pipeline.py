"""Alur lengkap: komposisi -> sintesis -> efek -> master. Dipakai generate.py."""
import json
import time

import numpy as np
import soundfile as sf

import config
import fx
from compose import compose, to_dicts
from render import render_layers, render_texture

SR = config.SAMPLE_RATE


def produce(total, seed, fade_out=30.0, stems_prefix=None, log=print):
    t0 = time.time()
    p = config.FX
    events = compose(total, seed, with_melody=True)

    layers = render_layers(events, total, seed)
    for k in ("drone", "pad", "melody"):
        layers.setdefault(k, np.zeros((int(total * SR), 2)))
    layers["texture"] = render_texture(total, seed)
    log(f"  sintesis {time.time() - t0:.0f}s")
    if stems_prefix:
        for k, v in layers.items():
            sf.write(f"{stems_prefix}.{k}.wav", v.astype(np.float32), SR, subtype="FLOAT")

    layers["pad"] = fx.chorus(layers["pad"])
    layers["melody"] = fx.delay(layers["melody"], p)

    dry = sum(layers.values())
    send = sum(layers[k] * p["send"][k] for k in layers)
    ir = fx.make_ir(p["reverb_decay"], p["reverb_predelay"], np.random.default_rng([seed, 5]),
                    p["reverb_hp"])
    mix = dry * config.MIX["dry"] + fx.reverb(send, ir) * config.MIX["wet"]

    n_fade = int(min(fade_out, total / 4) * SR)
    mix[-n_fade:] *= np.linspace(1, 0, n_fade)[:, None] ** 2
    mix, lufs = fx.master(mix, p)
    return mix, events, lufs


def save(path_stem, mix, events, resolved_toml, lufs, mp3=True):
    import subprocess, shutil
    wav = f"{path_stem}.wav"
    sf.write(wav, mix.astype(np.float32), SR, subtype="PCM_24")
    with open(f"{path_stem}.toml", "w") as f:
        f.write(f"# loudness terukur: {lufs:.1f} LUFS\n" + resolved_toml)
    with open(f"{path_stem}.events.json", "w") as f:
        json.dump(to_dicts(events), f, indent=1)
    if mp3 and shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-b:a", "192k",
                        f"{path_stem}.mp3"], check=True)
    return wav
