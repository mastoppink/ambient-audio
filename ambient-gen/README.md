# ambient-gen

Generator ambient "Spacenight". Lihat `../plan.md` untuk rencana lengkap.

## Pemakaian (sejak milestone 3.5)
```bash
python generate.py presets/nebula.toml                       # render sesuai preset
python generate.py presets/drift.toml --preview 120 --variations 8   # coba 8 versi pendek
python generate.py out/drift_s3005_120s.toml --duration 60   # versi panjang dari yang disukai
python generate.py presets/deep_sleep.toml --set key.mode=dorian --set pad.brightness=0.4
python generate.py presets/nebula.toml --dry-run --variations 3     # lihat nilai final tanpa render
```
Setiap render menulis `.wav`, `.mp3`, `.events.json`, dan `.toml` berisi semua nilai final.
File `.toml` itu bisa dipakai lagi sebagai preset dan menghasilkan audio yang identik.

### Isi preset
| Bagian | Kunci | Arti |
|---|---|---|
| (atas) | `name`, `seed`, `duration_min` | |
| `[key]` | `tonic`, `mode` | mode: ionian, dorian, phrygian, lydian, mixolydian, aeolian |
| `[mix]` | `drone`, `pad`, `melody`, `texture` | level tiap lapisan (0 = mati) |
| `[pad]` | `brightness`, `width`, `movement` | 0..1: gelap→terang, sempit→lebar, statis→bergerak |
| | `life` | 0..1: kaku/digital → "analog" (pitch drift + timbre bernapas) |
| | `chord_seconds`, `chord_weights` | durasi tiap chord; bobot chord I, II, iii, V, vi, vii (0 = tidak dipakai) |
| `[drone]` | `brightness`, `sub` | 0..1; sub = sinus satu oktaf di bawah drone terendah |
| `[texture]` | `brightness` | 0..1 |
| `[melody]` | `density`, `decay`, `register` | 0..1 jarang→sering; detik; 0..1 rendah→tinggi |
| | `timbre`, `phrases` | `soft` / `glass` (bel kaca) / `kalimba` / `piano` (jauh & lembut); 0..1 peluang frasa 2-3 nada |
| | `consonance` | 0 = bebas / 1 = melodi menghindari nada 1 semiton dari chord & drone, juga saat chord berganti |
| `[space]` | `reverb_decay`, `reverb_mix`, `delay_feedback` | detik; 0..1; 0..0.6 |
| | `early`, `width`, `motion`, `shimmer` | 0..1: pantulan awal, lebar stereo reverb, modulasi ekor, kilau oktaf atas |
| `[form]` | `amount`, `period_min`, `intro_min`, `outro_min`, `bright` | bentuk makro: seberapa kuat & seberapa lambat intensitas naik-turun |
| `[master]` | `target_lufs` | mis. -16 (umum) atau -18 (tidur) |
| `[qc]` | `profile` | `default` atau `sleep` (target spektrum lebih gelap) |

Variasi: angka boleh ditulis `[min, max]` dan daftar teks `["E", "A"]`; nilainya dipilih per seed.
Seed yang sama selalu memberi hasil yang sama, dan preview adalah awal yang persis dari versi panjangnya.

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

## Milestone 4: render panjang yang cepat + bentuk makro
```bash
python generate.py presets/nebula.toml --duration 60          # ~3 menit di 4 core
python generate.py presets/nebula.toml --duration 75 --workers 2 --no-mp3
```
- Sintesis per segmen 30 detik, paralel di semua core (`pipeline.py`, `render.render_segment`).
  Tiap suara bisa di-render mulai titik mana pun dengan hasil identik, jadi segmen tidak berpengaruh ke suara.
- Efek streaming dengan state dibawa antar segmen: chorus, delay, reverb konvolusi overlap-add, HPF.
- Dua pass: (1) pra-master ke WAV float sementara + ukur loudness (`loudness.py`, BS.1770);
  (2) gain ke target LUFS + limiter streaming → WAV 24-bit. RAM ~1,6 GB berapa pun durasinya.
- Bentuk makro (`form.py`): kurva intensitas 0..1 (intro, dua gelombang lambat, outro) yang membuka
  filter pad, menambah kepadatan melodi, dan menaikkan tekstur saat intens. Level keseluruhan tetap rata.
- Disk: WAV 24-bit 60 menit ≈ 1 GB (+ ~1,4 GB sementara selama render), MP3 192k ≈ 86 MB.

## Milestone 5: optimasi kualitas audio
```bash
python qc.py out/x.wav                       # laporan kualitas (+ .qc.png)
python qc.py out/baru.wav --compare out/lama.wav
python generate.py presets/nebula.toml --flac   # juga simpan FLAC
```
Setiap render otomatis membuat `.qc.txt/.qc.json/.qc.png`: loudness & LRA, true peak, kecocokan mono,
dan keseimbangan spektrum per pita (1/3 oktaf, relatif pink) dibanding target per profil.

Perubahan suara (diukur dengan qc.py, preview 4 menit):
- Pad: harmonik sampai ~12 kHz (dulu dipotong di ~2,6 kHz), pitch drift analog per oscillator,
  timbre saw/triangle bernapas, sedikit resonansi filter (`pad.life`).
- Sub dipindah dari tiap nada pad ke drone terendah saja; drone diberi low-shelf.
- EQ per lapisan (`config.EQ`): pad dibersihkan di 260 Hz dan diberi badan di 1 kHz, reverb tanpa bass.
- Reverb: pantulan awal, decay berbeda per pita frekuensi, ekor bermodulasi, opsi shimmer.
- Dither TPDF saat menulis 24-bit.

| Nebula, relatif pink | sebelum | sesudah |
|---|---|---|
| sub 20-60 Hz | -65 | -14 |
| bass 60-150 | +5 | +5 |
| low-mid 150-400 | +4 | +3 |
| mid 400-2k | -10 | -3 |
| presence 2-6k | -25 | -13 |
| air 6-16k | -58 | -35 |

Render sekitar 1,7x lebih lambat dari milestone 4 (harmonik & drift lebih banyak): 60 menit ≈ 5 menit di 4 core.

### Melodi dan target YouTube
- Timbre melodi per preset: Nebula `glass`, Drift `kalimba`, Deep Sleep `piano`; sebagian nada menjadi
  frasa pendek 2-3 nada yang makin pelan (`melody.phrases`).
- Loudness: YouTube menurunkan video yang lebih keras dari ~-14 LUFS tetapi tidak menaikkan yang lebih pelan.
  Nebula & Drift memakai -14 LUFS, Deep Sleep -16 LUFS (konten tidur sedikit lebih pelan).

### Melodi yang menyatu (tidak sumbang)
- Bel kaca & kalimba memakai parsial harmonis (FM 2:1, parsial 4x / 6x). Rasio lama 3,5 / 2,76 / 5,95
  menghasilkan parsial di luar tangga nada yang terdengar sumbang di atas pad.
- `melody.consonance = 1` (Nebula, Drift): tiap nada, termasuk nada frasa, dijaga agar tidak berjarak
  1 semiton dari chord/drone yang sedang bunyi, chord lama yang masih memudar, dan chord berikutnya kalau
  nada masih berdengung saat pergantian. Deep Sleep tidak berubah (consonance 0, hasil identik).
- `python harmony_check.py out/x.events.json` menghitung bentrokan. 5 seed x 60 menit:
  Nebula 13% → 0%, Drift 9% → 0%.

## Daftar preset
| Preset | Kunci | Mood | Melodi | LUFS |
|---|---|---|---|---|
| Nebula | D Lydian | luas, terang | bel kaca + shimmer | -14 |
| Drift | E/A Dorian | sendu, hangat (fokus) | kalimba | -14 |
| Deep Sleep | D Aeolian | gelap, lambat (tidur) | piano jauh | -16 |
| Aurora | F Lydian | hangat, penuh harapan (pagi) | bel kaca + shimmer kuat | -14 |
| Deep Space | C Phrygian | misterius, gelap (fokus malam) | bel kaca sangat jarang, reverb 16 s | -14 |
| Orbit | G Mixolydian | ringan, melayang (belajar/kerja) | kalimba, frasa sering | -14 |
| Starlight Lullaby | A Ionian | lembut, manis (tidur anak) | piano jauh | -16 |
| Solitude | B Aeolian | sendu, reflektif | piano sangat jarang, chord 2-3 menit | -15 |
| Meditation | D Dorian | statis (meditasi/yoga) | tanpa melodi | -15 |

### MP3 siap upload
Setiap render (tanpa `--no-mp3`) membuat MP3 320 kbps CBR / 48 kHz dengan tag judul. Karena encoding MP3
bisa menaikkan puncak, file didekode ulang dan true peak diukur; kalau melewati -1 dBTP, volume
diturunkan secukupnya (biasanya ~0,1 dB) lalu di-encode ulang. 60 menit ≈ 137 MB.
