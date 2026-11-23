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

## Milestone 2: drone + pad dengan pergantian chord
```bash
python milestone2.py                 # 3 menit -> out/milestone2.wav + .events.json
python milestone2.py --dur 300 --seed 42
```
- `compose.py` membuat daftar event (chord dipilih berbobot, voice leading ke nada terdekat).
- `render.py` membunyikan event; chord tumpang-tindih `CHORD_OVERLAP` detik sebagai crossfade.
- Pilihan chord dan bobotnya ada di `CHORDS` (compose.py); level dan rentang di `config.py`.

## Milestone 3: lapisan lengkap + efek
```bash
python milestone3.py                 # 10 menit -> out/milestone3.wav (-16 LUFS)
python milestone3.py --dur 120 --stems   # cepat + simpan tiap lapisan kering
```
- Melodi jarang (`MELODY` di config): random walk berbobot, condong ke nada chord yang sedang bunyi, delay panjang.
- Tekstur (`TEXTURE`): pink noise band-pass, digerakkan tiga LFO berperiode prima 17/23/29 detik.
- Efek (`FX`, fx.py): chorus pada pad → reverb konvolusi dengan IR sintetis (decay 11 detik,
  high-pass 180 Hz di jalur reverb, send berbeda tiap lapisan) → HPF 30 Hz → normalisasi -16 LUFS → limiter -1 dBFS.
- Limiter dibuat sendiri karena `Limiter` pedalboard menambah makeup gain sendiri (~+5 dB) sehingga loudness meleset.
