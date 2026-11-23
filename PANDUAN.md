# Panduan Spacenight

Program ini membuat musik ambient bertema luar angkasa berdurasi panjang (misalnya 60 menit) secara otomatis. Hasilnya MP3 yang sudah dimastering dan siap dipakai untuk video YouTube.

---

## 1. Persiapan (sekali saja)

Yang dibutuhkan:
- **Python 3.11 atau lebih baru**: [python.org/downloads](https://www.python.org/downloads/)
- **ffmpeg**: untuk membuat MP3
  - Windows: `winget install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`

Ambil program dan pasang komponennya:
```bash
git clone -b claude/stoic-clarke-qaxnin https://github.com/mastoppink/luar-angkasa.git
cd luar-angkasa/ambient-gen
pip install -r requirements.txt
```

Semua perintah di bawah dijalankan dari folder `ambient-gen`.

---

## 2. Membuat lagu

```bash
python generate.py presets/nebula.toml
```

Hasilnya muncul di folder `out/`. Lama render sekitar 5–6 menit untuk 60 menit musik, tergantung kecepatan komputer.

| File | Kegunaan |
|---|---|
| **`.mp3`** | **Untuk diupload / dipakai di aplikasi video** (320 kbps, sudah dimastering) |
| `.wav` | Kualitas penuh (24-bit), untuk arsip |
| `.toml` | "Resep" lagu ini: bisa dipakai untuk membuat ulang hasil yang persis sama |
| `.qc.txt`, `.qc.png` | Laporan kualitas suara (volume, puncak, keseimbangan nada) |
| `.events.json` | Daftar nada (teknis, boleh diabaikan) |

---

## 3. Pilihan preset

| Preset | Suasana | Cocok untuk |
|---|---|---|
| `nebula` | Luas dan terang, bel kaca berkilau | Umum, santai |
| `aurora` | Hangat dan penuh harapan | Pagi, bersantai |
| `orbit` | Ringan dan melayang, kalimba | Belajar, kerja |
| `drift` | Sendu dan hangat, kalimba | Fokus |
| `deep_space` | Misterius dan gelap, gema panjang | Fokus malam |
| `solitude` | Sendu dan reflektif, sangat lambat | Merenung |
| `meditation` | Statis, tanpa melodi | Meditasi, yoga |
| `starlight_lullaby` | Lembut dan manis, piano jauh | Tidur anak, menenangkan diri |
| `deep_sleep` | Gelap dan lambat, piano jauh | Tidur |

Contoh: `python generate.py presets/orbit.toml`

---

## 4. Alur kerja yang disarankan

Setiap preset bisa menghasilkan ribuan versi berbeda. Cara termudah untuk mendapatkan yang paling enak:

**Langkah 1.** Buat beberapa versi pendek, misalnya 8 versi masing-masing 2 menit:
```bash
python generate.py presets/orbit.toml --preview 120 --variations 8
```

**Langkah 2.** Dengarkan MP3-nya di folder `out/`, lalu pilih yang paling enak, misalnya `orbit_s6003_120s.mp3`.

**Langkah 3.** Buat versi 60 menit dari pilihan itu dengan memakai file `.toml`-nya:
```bash
python generate.py out/orbit_s6003_120s.toml --duration 60
```
Bagian awal versi 60 menit akan sama persis dengan preview yang kamu pilih.

---

## 5. Opsi perintah

| Opsi | Contoh | Fungsi |
|---|---|---|
| `--duration` | `--duration 90` | Durasi dalam menit |
| `--seed` | `--seed 1234` | Versi lain dari preset yang sama (angka bebas) |
| `--preview` | `--preview 120` | Render pendek (detik) untuk mencoba |
| `--variations` | `--variations 5` | Buat beberapa versi sekaligus |
| `--set` | `--set melody.density=0.3` | Ubah pengaturan tanpa mengedit file |
| `--flac16` | | Juga simpan FLAC 16-bit (lossless, lebih kecil) |
| `--flac` | | Juga simpan FLAC 24-bit |
| `--no-mp3` | | Jangan buat MP3 |
| `--outdir` | `--outdir hasil` | Folder hasil (bawaan: `out`) |
| `--dry-run` | | Tampilkan pengaturan akhir tanpa render |

---

## 6. Mengubah karakter suara

Pakai `--set`, boleh lebih dari satu:
```bash
python generate.py presets/nebula.toml --set pad.brightness=0.8 --set melody.density=0.3
```

Pengaturan yang paling berguna:

| Pengaturan | Nilai | Efek |
|---|---|---|
| `pad.brightness` | 0 – 1 | Suara latar gelap → terang |
| `pad.width` | 0 – 1 | Sempit → lebar (stereo) |
| `pad.movement` | 0 – 1 | Statis → bergerak |
| `melody.density` | 0 – 1 | Melodi jarang → sering |
| `melody.timbre` | `glass`, `kalimba`, `piano`, `soft` | Jenis suara melodi |
| `melody.phrases` | 0 – 1 | Seberapa sering melodi memainkan 2–3 nada berurutan |
| `mix.melody` | `0` = tanpa melodi | Volume melodi |
| `mix.texture` | mis. `0.03` | Volume suara "angin" |
| `space.reverb_mix` | 0 – 1 | Kering → sangat luas |
| `space.shimmer` | 0 – 1 | Kilau halus di gema |
| `key.tonic` | `C`, `D`, `F#`, … | Nada dasar |
| `key.mode` | `ionian`, `dorian`, `phrygian`, `lydian`, `mixolydian`, `aeolian` | Suasana: lydian = luas, dorian = sendu, aeolian = gelap, ionian = manis |
| `master.target_lufs` | `-14` YouTube, `-16` tidur | Volume akhir |

Untuk perubahan permanen, salin file preset, misalnya `presets/nebula.toml` menjadi `presets/milikku.toml`, lalu ubah angkanya dengan editor teks biasa. Setiap baris di file preset sudah diberi keterangan.

Tips: di file preset, angka boleh ditulis sebagai rentang `[0.4, 0.6]`, dan program akan memilih nilai di antaranya untuk setiap seed. Ini cara mudah membuat variasi otomatis.

---

## 7. Tips untuk YouTube

- **Satu video, satu seed.** Gunakan seed atau preset berbeda untuk setiap video (`--seed 2002`, `--seed 2003`, …). Dengan begitu setiap video unik, dan itu penting untuk aturan YouTube tentang konten berulang.
- **Volume sudah diatur.** Preset memakai −14 LUFS (standar YouTube) atau −16 LUFS (untuk tidur). Jangan aktifkan normalisasi atau penguat volume di aplikasi video.
- **Ekspor video:** audio AAC 320–384 kbps, 48 kHz.
- **Menyimpan resep.** Simpan file `.toml` setiap video yang diupload, supaya bisa dibuat ulang kapan saja.

---

## 8. Kalau ada masalah

| Gejala | Solusi |
|---|---|
| `ModuleNotFoundError` | Jalankan lagi `pip install -r requirements.txt` |
| MP3 tidak dibuat | ffmpeg belum terpasang (lihat bagian 1) |
| Render lama / komputer berat | Tambahkan `--workers 2` supaya hanya memakai 2 core |
| Disk penuh | Render 60 menit butuh sekitar 2,5 GB sementara; hapus isi `out/` yang tidak dipakai |
| `.qc.txt` berisi `[CEK]` | Hanya catatan; dengarkan dulu, kalau enak abaikan saja |

Penjelasan teknis lengkap ada di `ambient-gen/README.md`.
