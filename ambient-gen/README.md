# ambient-gen

Generator ambient "Spacenight". Lihat `../plan.md` untuk rencana lengkap.

## Setup
```bash
pip install -r requirements.txt
```

## Milestone 1: satu nada pad
```bash
python milestone1.py                 # D3, 30 detik -> out/milestone1_pad.wav
python milestone1.py --chord         # D-A-E
python milestone1.py --seed 7 --midi 45 --dur 40
python -m pytest -q tests
```
Ubah karakter suara di `config.py` → `PAD` (detune, cutoff, attack/release, periode LFO).
