"""Milestone 3: drone + pad + melodi jarang + tekstur + efek, default 10 menit.

Pakai:  python milestone3.py [--dur 600] [--seed 123] [--stems]
"""
import argparse
import json
import time

import numpy as np
import soundfile as sf

import config
import fx
from compose import compose, to_dicts
from render import render_layers, render_texture

SR = config.SAMPLE_RATE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dur", type=float, default=600.0)
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--stems", action="store_true", help="simpan tiap lapisan (kering)")
    ap.add_argument("--out", default="out/milestone3.wav")
    a = ap.parse_args()
    t0 = time.time()
    rng = np.random.default_rng(a.seed)
    p = config.FX

    events = compose(a.dur, rng, with_melody=True)
    with open(a.out.replace(".wav", ".events.json"), "w") as f:
        json.dump(to_dicts(events), f, indent=1)
    n_mel = sum(e.layer == "melody" for e in events)
    print(f"event: {len(events)} (melodi {n_mel})")

    layers = render_layers(events, a.dur, rng)
    layers["texture"] = render_texture(a.dur, rng)
    print(f"sintesis selesai {time.time() - t0:.0f}s")
    if a.stems:
        for k, v in layers.items():
            sf.write(a.out.replace(".wav", f".{k}.wav"), v.astype(np.float32), SR, subtype="FLOAT")

    # efek per lapisan
    layers["pad"] = fx.chorus(layers["pad"])
    layers["melody"] = fx.delay(layers["melody"], p)

    dry = sum(layers.values())
    send = sum(layers[k] * p["send"][k] for k in layers)
    ir = fx.make_ir(p["reverb_decay"], p["reverb_predelay"], rng, p["reverb_hp"])
    wet = fx.reverb(send, ir)
    mix = dry * 0.75 + wet * 1.0

    fade_out = int(30 * SR)
    mix[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None] ** 2
    mix, lufs = fx.master(mix, p)
    sf.write(a.out, mix.astype(np.float32), SR, subtype="PCM_24")
    print(f"tulis {a.out}  loudness {lufs:.1f} LUFS, peak {20*np.log10(np.abs(mix).max()):.1f} dBFS, "
          f"waktu {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
