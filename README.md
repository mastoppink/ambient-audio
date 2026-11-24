# Spacenight

Musik ambient bertema luar angkasa yang dibuat sepenuhnya oleh program: synth, komposisi, dan mastering
sendiri, tanpa sampel atau musik orang lain. Hasilnya MP3 60 menit yang siap dipakai untuk video YouTube.

- **Studio (web):** https://mastoppink.github.io/ambient-audio/ — dengarkan dan atur suara langsung di browser,
  lalu unduh resep `.toml`.
- **Panduan pemakaian:** [PANDUAN.md](PANDUAN.md)
- **Dokumentasi teknis:** [ambient-gen/README.md](ambient-gen/README.md)

## Mulai cepat

```bash
cd ambient-gen
pip install -r requirements.txt      # butuh Python 3.11+ dan ffmpeg
python buat.py --untuk tidur --jumlah 3 --contoh
python buat.py --lanjut
```

## Isi repo

| Folder | Isi |
|---|---|
| `ambient-gen/` | Generator Python: 9 preset, render 60 menit, MP3 siap YouTube, laporan kualitas |
| `web/` | Spacenight Studio (Web Audio), diterbitkan otomatis ke GitHub Pages |
| `PANDUAN.md` | Panduan pemakaian dalam bahasa Indonesia |
