# ambient-gen

Generator ambient "Spacenight" (teknis). Panduan pemakaian ada di [`../PANDUAN.md`](../PANDUAN.md).

```bash
pip install -r requirements.txt     # + ffmpeg untuk MP3
python generate.py presets/nebula.toml --duration 60
python -m pytest -q tests
```

## Struktur

| File | Isi |
|---|---|
| `generate.py` | CLI: preset → render → MP3/FLAC → laporan QC |
| `settings.py` | Muat preset TOML, override `--set`, rentang acak per seed, terjemahan kontrol makro → parameter teknis |
| `config.py` | Nilai teknis default (diubah oleh `settings.apply`), EQ per lapisan |
| `compose.py` | Komposisi → daftar event: progresi chord (voice leading), melodi (random walk, frasa, `consonance`) |
| `form.py` | Kurva intensitas sepanjang lagu (intro, gelombang lambat, outro) |
| `synth.py` | Pad (wavetable band-limited, pitch drift, filter bergerak), melodi (soft/glass/kalimba/piano), tekstur angin |
| `render.py` | Render satu segmen waktu untuk semua lapisan |
| `fx.py` | Efek streaming: reverb konvolusi (IR sintetis), chorus, delay, EQ, shimmer, limiter |
| `pipeline.py` | Render paralel per segmen 30 s → efek → loudness → limiter → WAV/MP3/FLAC |
| `loudness.py` | Meter loudness BS.1770 streaming (integrated, short-term, LRA) |
| `qc.py` | Laporan kualitas: LUFS, LRA, true peak, mono, keseimbangan spektrum 1/3 oktaf vs pink |
| `harmony_check.py` | Hitung nada melodi yang bentrok (1 semiton) dengan chord |
| `buat.py` | Antarmuka mudah: tujuan → rencana beberapa video yang saling berbeda → render, dengan katalog riwayat |
| `mirip.py` | Skor kemiripan dua lagu (nada, urutan chord, warna suara, timbre, bentuk) |
| `presets/*.toml` | Sembilan preset |
| `export_web.py` | Ekspor preset + EQ ke `../web/presets.json` (jalankan setelah mengubah preset; dicek oleh tes) |

## Cara kerja

1. **Komposisi** (`compose.py`): chord dipilih berbobot dari template derajat skala (I, II, iii, V, vi, vii),
   voice leading ke nada terdekat, tumpang tindih `CHORD_OVERLAP` detik sebagai crossfade. Melodi:
   random walk berbobot, condong ke nada chord; dengan `consonance = 1` tidak pernah 1 semiton dari
   chord/drone yang sedang bunyi, yang sedang memudar, atau yang akan datang selama nada berdengung.
2. **Determinisme**: tiap lapisan dan tiap event punya sumber acak sendiri yang hanya bergantung pada seed.
   Hasil: seed sama → audio identik, dan preview = awal yang persis dari versi panjang.
3. **Sintesis per segmen**: setiap suara bisa di-render mulai dari sampel mana pun dengan hasil identik
   (fungsi waktu absolut, pitch drift analitik, filter dipanaskan dengan pre-roll pada grid blok absolut),
   jadi segmen 30 s disintesis paralel di semua core.
4. **Efek & master streaming**: chorus/delay/EQ/reverb (overlap-add) membawa state antar segmen.
   Pass 1 menulis pra-master float + mengukur loudness; pass 2 menerapkan gain ke target LUFS,
   limiter lookahead, dither TPDF → WAV 24-bit. RAM ~1,6 GB berapa pun durasinya.
5. **MP3**: 320 kbps CBR / 48 kHz; setelah encode didekode dan true peak diukur, volume dikoreksi
   kalau > -1 dBTP.
6. **QC**: setiap render menulis `.qc.txt/.json/.png`. Profil target spektrum: `default`, `calm`, `sleep`.

## Kunci preset

| Bagian | Kunci | Arti |
|---|---|---|
| (atas) | `name`, `seed`, `duration_min` | |
| `[key]` | `tonic`, `mode` | ionian, dorian, phrygian, lydian, mixolydian, aeolian |
| `[mix]` | `drone`, `pad`, `melody`, `texture` | level tiap lapisan (0 = mati) |
| `[pad]` | `brightness`, `width`, `movement`, `life` | 0..1 |
| | `chord_seconds`, `chord_weights` | durasi chord [min, max]; bobot I, II, iii, V, vi, vii (0 = tidak dipakai) |
| `[drone]` | `brightness`, `sub` | 0..1 |
| `[melody]` | `timbre`, `density`, `decay`, `register`, `phrases`, `consonance` | soft/glass/kalimba/piano; 0..1; detik; 0..1; 0..1; 0/1 |
| `[texture]` | `brightness` | 0..1 |
| `[space]` | `reverb_decay`, `reverb_mix`, `delay_feedback`, `early`, `width`, `motion`, `shimmer` | detik; 0..1 |
| `[form]` | `type`, `amount`, `period_min`, `intro_min`, `outro_min`, `bright` | bentuk lagu (arc/rise/valley/calm/journey) & kurva intensitas |
| `[variation]` | `amount` | 0..1: babak 8-18 menit (kepadatan & register melodi, angin, chord favorit), chord tambahan IV/Isus/I6, bobot chord per seed |
| `[master]` | `target_lufs` | -14 (YouTube), -16 (tidur) |
| `[qc]` | `profile` | default / calm / sleep |

Angka boleh ditulis `[min, max]` dan teks sebagai daftar `["E", "A"]`: nilainya dipilih per seed.
File `.toml` yang ditulis di samping setiap render berisi semua nilai final dan bisa dipakai lagi sebagai preset.

## Kinerja (4 core)

60 menit: ~5 menit sintesis + master, ~1 menit MP3. Disk sementara ~2,5 GB.

## Versi web (`../web`)

Spacenight Studio: port JavaScript (Web Audio) untuk mencoba suara secara langsung dan mengekspor `.toml`.
Diterbitkan ke GitHub Pages oleh `.github/workflows/pages.yml` setiap push yang mengubah `web/`.

| File | Isi |
|---|---|
| `web/js/music.js` | RNG ber-seed, preset → parameter (port `settings.py`), komposisi (port `compose.py`) |
| `web/js/engine.js` | Graf Web Audio: pad/drone, melodi, tekstur, EQ, chorus, delay, reverb; real-time & offline |
| `web/js/dsp.js` | IR reverb sintetis, pink noise, loudness BS.1770, limiter, penulis WAV |
| `web/js/app.js` | Antarmuka, volume otomatis ke target LUFS, ekspor WAV & `.toml` |

Diukur dengan `qc.py` (Nebula, 60 s): keseimbangan spektrum per pita dalam ±1,6 dB dari versi Python.
Belum ada di web: shimmer, timbre "bernapas" pada pad. Urutan nada berbeda dari Python untuk seed yang sama;
ekspor `.toml` menulis nilai yang sudah dipilih untuk seed itu, jadi warna suaranya sama.
