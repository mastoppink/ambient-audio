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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
Perintah `venv` membuat "ruang terpisah" khusus program ini, supaya paket-paketnya tidak bentrok
dengan program Python lain di komputermu. Setiap kali membuka Terminal baru, aktifkan lagi dulu:
```bash
cd ambient-audio/ambient-gen
source .venv/bin/activate
```
(Di Windows: `.venv\Scripts\activate`.)

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

## 2b. Mode album: track untuk dijual

Membuat satu album track pendek yang serasi (untuk Spotify/Apple Music lewat distributor, Bandcamp, dan sebagainya):
```bash
python album.py
```
Program akan bertanya: album untuk apa (tidur, meditasi, fokus, santai), berapa track, berapa menit per track,
nama album, dan nama artis. Atau langsung:
```bash
python album.py --fungsi tidur --jumlah 10 --menit 4 --nama "Orbital Lullabies" --artis "Spacenight"
```
Lihat rencananya dulu tanpa membuat audio:
```bash
python album.py --fungsi fokus --rencana
```

Yang dilakukan otomatis supaya album terasa satu karya:
- Preset hanya dari fungsi yang dipilih, bergiliran, dengan nomor versi yang dipilih supaya track tidak mirip.
- Nada dasar dari satu "keluarga" (nada rumah + kwint + kwart), dan track yang berurutan beda nada.
- Volume semua track sama.
- Album tidur dan meditasi diurutkan makin gelap menuju akhir.
- Pembukaan singkat (sekitar 6 detik sampai penuh), fade-out 12 detik, dan chord berganti lebih sering daripada versi video.
- Nama track dari bank nama (`album_kata.json`) dan tidak pernah dipakai dua kali (dicatat di `out/album/katalog_album.json`).

Hasil ada di `out/album/<tanggal>_<nama-album>/`:
| File | Untuk |
|---|---|
| `01 - Nama Track.wav` | WAV 16-bit 44,1 kHz: format standar yang diminta distributor |
| `01 - Nama Track.mp3` | MP3 320 kbps bertag (judul, artis, album, nomor track) |
| `album.txt` | Daftar track, durasi, dan catatan untuk distributor |
| `resep/` | Resep tiap track (untuk membuat ulang persis) dan laporan kualitas |
| `stok/` | Hanya dengan `--stok`: tiap track dalam versi 30 detik, 60 detik, dan loop 60 detik |
| `master/` | Hanya dengan `--master`: WAV 24-bit 48 kHz asli |

Untuk situs stock music (Pond5, AudioJungle, dan sebagainya), tambahkan `--stok`:
```bash
python album.py --fungsi santai --jumlah 10 --stok
```
- Versi 30 dan 60 detik dimulai tepat saat chord berganti (tidak di tengah nada) dan diakhiri fade singkat.
- Versi loop bisa diputar berulang tanpa sambungan terdengar, cocok untuk game, aplikasi, dan latar video.
- Volume semua versi sama dengan track aslinya.

Waktu render: sekitar 40 detik per track 4 menit, jadi satu album 10 track butuh sekitar 7 menit.

Sampul album (minimal 3000×3000 piksel) dibuat terpisah.

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

| Fungsi | Preset | Suasana |
|---|---|---|
| Tidur | `deep_sleep` | Gelap dan lambat, piano jauh |
| Tidur | `starlight_lullaby` | Lembut dan manis, piano jauh |
| Tidur | `lunar_haze` | Kabut bulan: nada lembut tanpa denting, paling pelan |
| Meditasi | `meditation` | Statis, tanpa melodi |
| Meditasi | `deep_space` | Misterius, gema paling panjang |
| Fokus & belajar | `orbit` | Ringan, paling banyak berubah, kalimba |
| Fokus & belajar | `drift` | Sendu dan hangat, kalimba lebih lembut |
| Fokus & belajar | `satellite` | Stabil dan hangat, piano jauh mengalir teratur |
| Santai | `nebula` | Luas dan terang, bel kaca berkilau |
| Santai | `aurora` | Hangat, paling berkilau |
| Santai | `solitude` | Sendu dan reflektif, menemani malam |

`buat.py --untuk tidur` hanya memakai preset Tidur, dan seterusnya (`belajar` memakai preset Fokus, tapi judulnya "study").
Judul otomatis juga mengikuti fungsi preset.

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
| `ModuleNotFoundError` | Aktifkan dulu `source .venv/bin/activate`, lalu `pip install -r requirements.txt` |
| Pesan `dependency conflicts` saat install | Paket program lain ikut terpengaruh. Pasang di virtual environment (bagian 1) |
| MP3 tidak dibuat | ffmpeg belum terpasang (lihat bagian 1) |
| Render lama / komputer berat | Tambahkan `--workers 2` supaya hanya memakai 2 core |
| Disk penuh | Render 60 menit butuh sekitar 2,5 GB sementara; hapus isi `out/` yang tidak dipakai |
| `.qc.txt` berisi `[CEK]` | Hanya catatan; dengarkan dulu, kalau enak abaikan saja |

Penjelasan teknis lengkap ada di `ambient-gen/README.md`.
