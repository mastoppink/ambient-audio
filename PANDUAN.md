# Panduan Spacenight

Program ini membuat musik ambient bertema luar angkasa berdurasi panjang (misalnya 60 menit) secara otomatis. Hasilnya MP3 yang sudah dimastering dan siap dipakai untuk video YouTube.

---

## 0. Spacenight Studio (versi web)

Buka **https://mastoppink.github.io/ambient-audio/** di browser (komputer atau HP). Tidak perlu memasang apa pun.

- Pilih preset, tekan **▶ Putar**, lalu geser slider. Perubahan langsung terdengar.
- **✨ Versi baru** mengganti nomor versi dan nada dasar sekaligus, cara tercepat mendapat hasil yang jelas berbeda.
- Tombol 🎲 hanya mengganti nomor versi (hasilnya masih mirip).
- **Bentuk lagu** dan **Perubahan antar babak** mengatur alur lagu dari awal sampai akhir.
- **Unduh .toml** menyimpan pengaturan yang sedang terdengar. Render versi 60 menit dengan Python
  (bagian 2), atau kirim file itu ke Claude untuk di-render.
- **Render WAV** membuat contoh beberapa menit langsung di browser, sudah dinormalisasi volumenya.

Versi web memakai warna suara yang sama dengan versi Python, tetapi urutan chord dan melodinya berbeda
untuk seed yang sama. Untuk video YouTube 60 menit, tetap pakai versi Python.

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
git clone https://github.com/mastoppink/ambient-audio.git
cd ambient-audio/ambient-gen
pip install -r requirements.txt
```

Semua perintah di bawah dijalankan dari folder `ambient-gen`.

---

## 2. Cara termudah: `buat.py`

Cukup jalankan, lalu jawab pertanyaannya:
```bash
python buat.py
```
Program akan bertanya: musik untuk apa (tidur, fokus, belajar, santai, meditasi, atau campur), berapa video,
berapa menit, dan apakah mau dibuatkan contoh 2 menit dulu.

Atau langsung dalam satu perintah:
```bash
python buat.py --untuk tidur --jumlah 3 --contoh
```
Dengarkan contohnya di `out/video/`. Kalau suka, buat versi penuhnya:
```bash
python buat.py --lanjut
```

**Yang dilakukan program untukmu:**
- Memilih preset, nada dasar, bentuk lagu, dan nomor versi yang berbeda untuk setiap video.
- Mengukur kemiripan setiap video dengan video lain di rencana **dan** dengan semua video yang pernah
  dibuat sebelumnya (dicatat di `out/katalog.json`), supaya tidak ada dua video yang terlalu mirip.
- Setiap video mendapat foldernya sendiri: file `.mp3` untuk aplikasi video, resep `.toml`, dan `info.txt`
  berisi saran judul dan deskripsi YouTube.

**Judul, deskripsi, chapter, dan tag YouTube otomatis.** Setiap video mendapat 5 pilihan judul bahasa Inggris
dan 5 bahasa Indonesia di `info.txt`, disusun dari suara yang benar-benar dihasilkan: suasana, suara melodi,
kecerahan terukur, tujuan, dan durasi. Deskripsinya sudah berisi chapter YouTube dari babak lagu (0:00, 9:38, ...)
dan hashtag. Judul tidak akan sama dengan video yang pernah dibuat, dan tidak pernah memakai klaim yang tidak
benar seperti "432 Hz", "binaural", atau "healing".

Untuk hasil render manual (`generate.py`) file-nya bernama `.judul.txt`, atau buat ulang dengan:
```bash
python judul.py out/nama_file.toml
```
Di Studio web, bagian **05 Judul & deskripsi YouTube** menampilkan judul untuk pengaturan yang sedang terdengar,
lengkap dengan tombol salin.

Untuk mengecek kemiripan hasil yang sudah ada:
```bash
python mirip.py out/video
```
Skor di bawah 60% berarti jelas berbeda. Di atas 75% terlalu mirip.

---

**Video panjang (2–3 jam).** Tambahkan `--menit 180` untuk 3 jam:
```bash
python buat.py --untuk tidur --jumlah 1 --menit 180
```
Render 3 jam butuh sekitar 27 menit di komputer 4 core (termasuk MP3, laporan kualitas, dan judul),
ruang disk kosong sekitar 7 GB selama proses (file sementara dihapus otomatis; yang tersimpan hanya MP3 432 MB),
dan RAM sekitar 1,6 GB, sama seperti video 1 jam. Judul, deskripsi, dan chapter
otomatis menyesuaikan ("3 Hours", chapter dengan format jam). Di Studio web, pilih durasinya di bagian
**03 Resep**.

---

## 3. Membuat satu lagu secara manual

```bash
python generate.py presets/nebula.toml
```

Hasilnya muncul di folder `out/`. Bawaannya hanya MP3 yang disimpan (YouTube toh mengompres ulang audionya);
WAV 24-bit hanya dipakai sementara selama proses. Tambahkan `--simpan-wav` kalau butuh WAV, misalnya untuk diedit. Lama render sekitar 10 menit untuk 60 menit musik di komputer 4 core (termasuk MP3), tergantung kecepatan komputer.

| File | Kegunaan |
|---|---|
| **`.mp3`** | **Untuk diupload / dipakai di aplikasi video** (320 kbps, sudah dimastering) |
| `.toml` | "Resep" lagu ini: bisa dipakai untuk membuat ulang hasil yang persis sama |
| `.judul.txt` | Pilihan judul (Inggris & Indonesia), deskripsi dengan chapter, tag, dan hashtag YouTube |
| `.qc.txt`, `.qc.png` | Laporan kualitas suara (volume, puncak, keseimbangan nada) |
| `.events.json` | Daftar nada (teknis, boleh diabaikan) |

---

## 4. Pilihan preset

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

## 5. Alur kerja manual

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

## 6. Opsi perintah

| Opsi | Contoh | Fungsi |
|---|---|---|
| `--duration` | `--duration 180` | Durasi dalam menit (mis. 60 = 1 jam, 180 = 3 jam) |
| `--seed` | `--seed 1234` | Versi lain dari preset yang sama (angka bebas) |
| `--preview` | `--preview 120` | Render pendek (detik) untuk mencoba |
| `--variations` | `--variations 5` | Buat beberapa versi sekaligus |
| `--set` | `--set melody.density=0.3` | Ubah pengaturan tanpa mengedit file |
| `--flac16` | | Juga simpan FLAC 16-bit (lossless, lebih kecil) |
| `--flac` | | Juga simpan FLAC 24-bit |
| `--simpan-wav` | | Simpan juga WAV 24-bit (bawaan: hanya MP3, supaya hemat ruang) |
| `--no-mp3` | | Jangan buat MP3 (WAV disimpan) |
| `--outdir` | `--outdir hasil` | Folder hasil (bawaan: `out`) |
| `--dry-run` | | Tampilkan pengaturan akhir tanpa render |

---

## 7. Mengubah karakter suara

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
| `space.reverb_type` | `hall`, `classic` | Jenis gema: `hall` = ekor bergerak halus (bawaan), `classic` = gema lama yang statis |
| `space.size` | 0.6 – 1.6 | Ukuran ruang gema: kecil = rapat, besar = lapang |
| `mix.cloud` | mis. `0.18` | Volume lapisan "awan" (butir suara berkilau dari nada chord), 0 = mati |
| `cloud.density` | 2 – 20 | Banyaknya butir per detik |
| `cloud.length` | 0.1 – 1.0 | Panjang butir (detik): pendek = berkilau, panjang = lembut |
| `cloud.register` | 0 – 1 | Tinggi nada awan: rendah = dekat pad, tinggi = berkilau di atas |
| `warmth.amount` | 0 – 1 | Kehangatan "kaset": 0 = bersih digital, 1 = jelas terasa kaset |
| `warmth.tape` | 0 – 1 | Goyangan nada halus seperti pita kaset |
| `warmth.noise` | 0 – 1 | Desis pita (0 = mati) |
| `key.tonic` | `C`, `D`, `F#`, … | Nada dasar |
| `key.mode` | `ionian`, `dorian`, `phrygian`, `lydian`, `mixolydian`, `aeolian` | Suasana: lydian = luas, dorian = sendu, aeolian = gelap, ionian = manis |
| `master.target_lufs` | `-14` YouTube, `-16` tidur | Volume akhir |
| `form.type` | `arc`, `rise`, `valley`, `calm`, `journey` | Bentuk lagu: naik-turun lembut, tumbuh perlahan, menenang di tengah, datar & tenang, berpindah suasana |
| `variation.amount` | 0 – 1 | Seberapa banyak lagu berubah antar babak (setiap 8–18 menit) |

Untuk perubahan permanen, salin file preset, misalnya `presets/nebula.toml` menjadi `presets/milikku.toml`, lalu ubah angkanya dengan editor teks biasa. Setiap baris di file preset sudah diberi keterangan.

Tips: di file preset, angka boleh ditulis sebagai rentang `[0.4, 0.6]`, dan program akan memilih nilai di antaranya untuk setiap seed. Ini cara mudah membuat variasi otomatis.

---

## 8. Tips untuk YouTube

- **Pakai `buat.py`.** Hasil pengukuran: video dengan preset sama yang hanya beda nomor versi masih 80–90% mirip,
  tetapi dengan nada dasar atau preset berbeda turun ke sekitar 40–50%. `buat.py` mengatur ini otomatis.
- **Tambahkan nilai darimu sendiri:** visual milikmu, judul dan deskripsi yang ditulis sungguh-sungguh, dan
  hanya unggah hasil yang sudah kamu dengarkan dan sukai.
- **Volume sudah diatur.** Preset memakai −14 LUFS (standar YouTube) atau −16 LUFS (untuk tidur). Jangan aktifkan normalisasi atau penguat volume di aplikasi video.
- **Ekspor video:** audio AAC 320–384 kbps, 48 kHz.
- **Menyimpan resep.** Simpan file `.toml` setiap video yang diupload, supaya bisa dibuat ulang kapan saja.

---

## 9. Pemeriksaan sebelum rilis

```bash
python cek_rilis.py
```
Merender semua preset (4 menit masing-masing) dan memeriksa: volume tepat di target, puncak aman (juga
setelah jadi MP3), awal lagu mulai dari hening, akhir lagu fade-out, tidak ada klik, keseimbangan suara,
dan tidak ada nada sumbang. File hasil ekspor Studio web juga bisa diperiksa: `python cek_rilis.py --wav file.wav`.

---

## 10. Kalau ada masalah

| Gejala | Solusi |
|---|---|
| `ModuleNotFoundError` | Jalankan lagi `pip install -r requirements.txt` |
| MP3 tidak dibuat | ffmpeg belum terpasang (lihat bagian 1) |
| Render lama / komputer berat | Tambahkan `--workers 2` supaya hanya memakai 2 core |
| Disk penuh | Render 60 menit butuh sekitar 2,5 GB sementara; hapus isi `out/` yang tidak dipakai |
| `.qc.txt` berisi `[CEK]` | Hanya catatan; dengarkan dulu, kalau enak abaikan saja |

Penjelasan teknis lengkap ada di `ambient-gen/README.md`.
