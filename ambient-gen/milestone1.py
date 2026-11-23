"""Milestone 1: satu nada pad 30 detik.

Pakai:  python milestone1.py [--midi 50] [--dur 30] [--seed 123] [--chord]
"""
import argparse
import numpy as np
import soundfile as sf

import config
from synth import pad_voice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--midi", type=int, default=config.TONIC_MIDI)
    ap.add_argument("--dur", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--chord", action="store_true", help="D-A-E (tonika, kuint, nona)")
    ap.add_argument("--out", default="out/milestone1_pad.wav")
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    notes = [a.midi, a.midi + 7, a.midi + 14] if a.chord else [a.midi]
    mix = sum(pad_voice(m, a.dur, rng, config.PAD) for m in notes)

    mix /= np.max(np.abs(mix)) + 1e-12
    mix *= 10 ** (-3 / 20)  # puncak -3 dBFS (belum ada mastering)
    sf.write(a.out, mix.astype(np.float32), config.SAMPLE_RATE, subtype="PCM_24")
    print(f"tulis {a.out}  ({a.dur:.0f}s, nada {notes}, seed {a.seed})")


if __name__ == "__main__":
    main()
