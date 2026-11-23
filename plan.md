# Spacenight — Rencana Ambient Generatif

Membuat musik ambient luar angkasa berdurasi panjang secara programatik dengan Python, dari sintesis sampai video.

## Fase 1: Konsep dan parameter
- **Skala:** D Lydian (D E F# G# A B C#). Lydian terdengar "luas"; D Dorian sebagai alternatif yang lebih gelap.
- **Durasi:** prototipe 10 menit → final 60–75 menit.
- **Tanpa beat.** Gerakan hanya dari perubahan tekstur yang pelan.
- **Seed tetap** (`numpy.random.default_rng(seed)`) supaya hasil bisa diulang.
- **Sample rate:** 48 kHz (standar video/YouTube).

## Fase 2: Synth
Satu suara pad:
- 3–5 oscillator saw/triangle, detune ±5–12 cent, fase awal acak
- Sub sinus satu oktaf di bawah
- Envelope: attack 8–15 s, release 10–20 s
- Low-pass filter, cutoff digerakkan LFO lambat (periode 30–90 s)
- Oscillator saw dibuat band-limited (PolyBLEP atau aditif) agar tidak aliasing

## Fase 3: Komposisi generatif

| Lapisan | Isi | Perubahan |
|---|---|---|
| Drone | D2 + A2 | Hampir statis |
| Pad | Chord dari skala, 60–120 s per chord | Crossfade pelan antar chord |
| Melodi jarang | Satu nada acak tiap 15–40 s, reverb banyak | Probabilistik |

- Panjang loop tiap lapisan berbeda dan prima (17, 23, 29 s) agar pola tidak terdengar berulang.
- Pergantian chord memakai voice leading (pindah nada terdekat), bukan lompat acak.
- Melodi pakai random walk berbobot (lebih sering melangkah dekat) dan panning acak pelan.

## Fase 4: Tekstur
- Pink noise → band-pass → cutoff digerakkan LFO (angin/ruang)
- Opsional: shimmer (pitch-shift +12 st di jalur reverb)

## Fase 5: Rantai efek
EQ high-pass 30 Hz → chorus → delay panjang → reverb (decay 8–15 s, mix tinggi) → limiter (ceiling −1 dBTP).
Target loudness: −16 s.d. −14 LUFS.

## Fase 6: Render
- Render per blok 5–10 menit; state synth (fase, filter, LFO) dibawa antar blok
- Ekor reverb tiap blok di-overlap ke blok berikutnya
- Simpan WAV 24-bit → konversi ke FLAC/MP3
- Fade-in 20–30 s, fade-out 30–60 s

## Fase 7: Video (opsional)
Gambar statis milik sendiri + `zoompan` pelan di `ffmpeg`, gabung dengan audio.

## Fase 8: Kontrol kualitas
- Dengarkan di speaker dan headphone, termasuk volume pelan
- Cek spektrogram: tidak ada clipping, tidak ada penumpukan di 200–500 Hz
- Cek mono-compatibility (chorus dan detune bisa saling meniadakan)
- Iterasi seed dan parameter

## Stack
```
Python 3.11+
numpy, scipy   → sintesis dan DSP
pedalboard     → reverb, chorus, delay, limiter
soundfile      → baca/tulis WAV
pyloudnorm     → ukur loudness
ffmpeg         → konversi dan video
```

## Struktur proyek
```
ambient-gen/
├── config.py       # key, skala, durasi, seed, sample rate
├── synth.py        # oscillator, envelope, filter, LFO
├── compose.py      # chord, loop, nada acak → daftar event
├── fx.py           # rantai efek pedalboard
├── render.py       # render per blok + overlap
├── master.py       # loudness + fade
├── make_video.sh   # ffmpeg
└── tests/          # cek panjang, tidak ada NaN, peak < 0 dBFS
```

## Milestone
1. ✅ Satu nada pad 30 detik terdengar bagus
2. ✅ Drone + pad 3 menit dengan pergantian chord
3. ✅ Ketiga lapisan + tekstur + FX, 10 menit
3.5. ✅ Preset TOML, kontrol makro, mode, variasi per seed
4. ✅ Render blok paralel + master streaming + bentuk makro, 60 menit (~3 menit render)
5. Video
