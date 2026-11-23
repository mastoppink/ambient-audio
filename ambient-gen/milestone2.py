"""Milestone 2: drone + pad dengan pergantian chord (default 3 menit).

Pakai:  python milestone2.py [--dur 180] [--seed 123]
"""
import argparse
import json

import numpy as np
import soundfile as sf

import config
from compose import compose, to_dicts
from render import render_events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dur", type=float, default=180.0)
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--out", default="out/milestone2.wav")
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    events = compose(a.dur, rng)
    for start, label in sorted({(e.start, e.label) for e in events if e.layer == "pad"}):
        notes = [e.midi for e in events if e.start == start and e.layer == "pad"]
        print(f"{start:6.1f}s  {label:8s} {notes}")
    with open(a.out.replace(".wav", ".events.json"), "w") as f:
        json.dump(to_dicts(events), f, indent=1)

    mix = render_events(events, a.dur, rng)
    fade = int(5 * config.SAMPLE_RATE)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    mix /= np.max(np.abs(mix)) + 1e-12
    mix *= 10 ** (-3 / 20)
    sf.write(a.out, mix.astype(np.float32), config.SAMPLE_RATE, subtype="PCM_24")
    print(f"tulis {a.out}")


if __name__ == "__main__":
    main()
