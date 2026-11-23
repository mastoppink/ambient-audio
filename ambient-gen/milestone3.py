"""Milestone 3: drone + pad + melodi jarang + tekstur + efek, default 10 menit.
(Sejak milestone 3.5 cukup pakai generate.py; skrip ini dipertahankan untuk perbandingan.)

Pakai:  python milestone3.py [--dur 600] [--seed 123] [--stems]
"""
import argparse

import config
import pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dur", type=float, default=600.0)
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--stems", action="store_true", help="simpan tiap lapisan (kering)")
    ap.add_argument("--out", default="out/milestone3.wav")
    a = ap.parse_args()
    events, lufs = pipeline.produce(a.out[:-4], a.dur, a.seed, stems=a.stems)
    print(f"tulis {a.out}  loudness {lufs:.1f} LUFS")


if __name__ == "__main__":
    main()
