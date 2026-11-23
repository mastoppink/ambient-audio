"""Alur lengkap streaming: komposisi -> sintesis paralel per segmen -> efek -> master.

Pass 1: segmen 30 detik disintesis paralel (semua core), lalu efek dijalankan berurutan
        dengan state dibawa antar segmen; hasil pra-master ditulis ke WAV float sementara
        sambil loudness diukur.
Pass 2: baca ulang per potongan, terapkan gain ke target LUFS + limiter, tulis WAV 24-bit.
Memori tetap kecil berapa pun durasinya.
"""
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import time

import numpy as np
import soundfile as sf

import config
import fx
from compose import compose, to_dicts
from form import make_shape
from loudness import LoudnessMeter
from render import render_segment, LAYER_NAMES

SR = config.SAMPLE_RATE
_JOB = {}


def _work(i):
    j = _JOB
    start = i * j["seg"]
    n = min(j["seg"], j["total_n"] - start)
    return i, render_segment(j["events"], start, n, j["seed"], i)


def produce(stem, total, seed, form=None, form_total=None, fade_out=30.0, stems=False,
            workers=None, log=print):
    """Render ke {stem}.wav (24-bit). Mengembalikan (events, lufs).

    form_total: durasi yang dipakai kurva bentuk. Untuk preview, isi dengan durasi versi
    panjang supaya preview tetap sama persis dengan awal versi panjangnya."""
    t0 = time.time()
    config.SHAPE = make_shape(form_total or total, seed, form) if form else None
    events = compose(total, seed, with_melody=True)
    total_n = int(total * SR)
    seg = int(config.SEGMENT_SECONDS * SR)
    n_seg = -(-total_n // seg)
    _JOB.update(events=events, seed=seed, total_n=total_n, seg=seg)

    p = config.FX
    chorus, delay = fx.stream_chorus(), fx.stream_delay(p)
    ir = fx.make_ir(p["reverb_decay"], p["reverb_predelay"], np.random.default_rng([seed, 5]),
                    p["reverb_hp"], early=p["early"], width=p["width"])
    reverb = fx.StreamReverb(ir)
    wet_chorus = fx.stream_wet_chorus() if p["motion"] > 0 else None
    shimmer = None
    if p["shimmer"] > 0:
        # jalur shimmer: kirim -> naik 1 oktaf -> buang bass -> reverb yang lebih panjang & tanpa ER
        ir2 = fx.make_ir(p["reverb_decay"] * 1.4, 0.05, np.random.default_rng([seed, 8]), 600.0,
                         early=0.0)
        shimmer = (fx.OctaveUp(), fx.StreamEQ([("hp", 700, 0, 0.7), ("lp", 9000, 0, 0.7)]),
                   fx.StreamReverb(ir2))
    eq = {k: fx.StreamEQ(v) for k, v in config.EQ.items()}
    meter = LoudnessMeter(SR)
    n_fade = int(min(fade_out, total / 4) * SR)

    tmp = f"{stem}.premaster.wav"
    stem_files = {k: sf.SoundFile(f"{stem}.{k}.wav", "w", SR, 2, "FLOAT") for k in LAYER_NAMES} \
        if stems else {}
    workers = workers or os.cpu_count() or 1
    ctx = mp.get_context("fork")   # anak proses mewarisi config yang sudah diterapkan preset
    with sf.SoundFile(tmp, "w", SR, 2, "FLOAT") as out, ctx.Pool(workers) as pool:
        for i, layers in pool.imap(_work, range(n_seg)):
            for k, f in stem_files.items():
                f.write(layers[k])
            layers = {k: eq[k](v.astype(np.float64)) for k, v in layers.items()}
            layers["pad"] = chorus(layers["pad"])
            layers["melody"] = delay(layers["melody"])
            dry = sum(layers.values())
            send = sum(layers[k] * p["send"][k] for k in layers)
            wet = reverb(send)
            if wet_chorus:
                wet = wet * (1 - p["motion"]) + wet_chorus(wet) * p["motion"]
            if shimmer:
                up, hp, rv = shimmer
                wet = wet + rv(hp(up(send))) * p["shimmer"] * 0.6
            mix = dry * config.MIX["dry"] + eq["reverb"](wet) * config.MIX["wet"]
            mix = eq["master"](mix)
            # fade-out di akhir lagu
            s0 = i * seg
            t_idx = s0 + np.arange(len(mix))
            m = t_idx >= total_n - n_fade
            if m.any():
                mix[m] *= (np.clip((total_n - t_idx[m]) / n_fade, 0, 1) ** 2)[:, None]
            meter.add(mix)
            out.write(mix.astype(np.float32))
            done = (i + 1) / n_seg
            el = time.time() - t0
            log(f"\r  pass 1: {done * 100:5.1f}%  {el:4.0f}s  (sisa ~{el / done - el:4.0f}s)", end="")
    for f in stem_files.values():
        f.close()
    log("")

    gain = 10 ** ((p["target_lufs"] - meter.integrated()) / 20)
    lim = fx.StreamLimiter(p["ceiling_db"])
    meter2 = LoudnessMeter(SR)
    with sf.SoundFile(tmp) as src, sf.SoundFile(f"{stem}.wav", "w", SR, 2, "PCM_24") as dst:
        drng = np.random.default_rng([seed, 7])
        lsb = 2.0 ** -23   # 1 LSB untuk 24-bit

        def emit(y):
            meter2.add(y)
            # dither TPDF +-1 LSB: kuantisasi ke 24-bit jadi noise halus, bukan distorsi
            # (penting pada fade-out panjang yang sangat pelan)
            d = (drng.random(y.shape) - drng.random(y.shape)) * lsb
            dst.write(np.clip(y + d, -1, 1 - lsb))

        for block in src.blocks(blocksize=seg, dtype="float64"):
            emit(lim.push(block * gain))
        emit(lim.flush())
    os.remove(tmp)
    lufs = meter2.integrated()
    log(f"  pass 2 selesai, {time.time() - t0:.0f}s total")
    return events, lufs


def export_flac16(stem, seed=0):
    """FLAC 16-bit (kualitas CD) dengan dither TPDF, ~60% ukuran FLAC 24-bit.
    Cukup untuk YouTube/streaming yang toh akan mengompres ulang."""
    rng = np.random.default_rng([seed, 9])
    lsb = 2.0 ** -15
    with sf.SoundFile(f"{stem}.wav") as src, \
            sf.SoundFile(f"{stem}.16bit.flac", "w", SR, 2, "PCM_16", format="FLAC") as dst:
        for b in src.blocks(blocksize=SR * 30, dtype="float64"):
            d = (rng.random(b.shape) - rng.random(b.shape)) * lsb
            dst.write(np.clip(b + d, -1, 1 - lsb))


def _mp3_true_peak(mp3):
    """Dekode MP3 dan ukur true peak (oversampling 4x), dBTP."""
    from scipy.signal import resample_poly
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", mp3, "-f", "f32le", "-ac", "2",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(out, dtype=np.float32).reshape(-1, 2)
    peak = 0.0
    for i in range(0, len(x), SR * 60):
        peak = max(peak, float(np.abs(resample_poly(x[i:i + SR * 60], 4, 1, axis=0)).max()))
    return 20 * np.log10(peak + 1e-12)


def export_mp3(stem, title="", ceiling_dbtp=-1.0, bitrate="320k", log=print):
    """MP3 siap upload: 320 kbps CBR, 48 kHz, tag judul.
    Encoding MP3 bisa menaikkan puncak; kalau setelah dekode true peak > ceiling,
    turunkan volume secukupnya dan encode ulang."""
    wav, mp3 = f"{stem}.wav", f"{stem}.mp3"
    gain = 0.0
    for _ in range(3):
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", wav]
        if gain:
            cmd += ["-af", f"volume={gain:.2f}dB"]
        cmd += ["-c:a", "libmp3lame", "-b:a", bitrate, "-ar", str(SR),
                "-metadata", f"title={title}", "-metadata", "comment=Spacenight ambient-gen", mp3]
        subprocess.run(cmd, check=True)
        tp = _mp3_true_peak(mp3)
        if tp <= ceiling_dbtp:
            break
        gain -= tp - ceiling_dbtp + 0.1
    log(f"  mp3 {bitrate}: true peak {tp:.2f} dBTP (koreksi volume {gain:+.2f} dB)")
    return tp, gain


def save_meta(stem, events, resolved_toml, lufs, mp3=True, flac=False, qc=True, profile="default",
              flac16=False, seed=0):
    with open(f"{stem}.toml", "w") as f:
        f.write(f"# loudness terukur: {lufs:.1f} LUFS\n" + resolved_toml)
    with open(f"{stem}.events.json", "w") as f:
        json.dump(to_dicts(events), f, indent=1)
    if mp3 and shutil.which("ffmpeg"):
        import tomllib
        title = tomllib.loads(resolved_toml).get("name", "")
        export_mp3(stem, title=title)
    if flac:   # lossless, ~55-60% ukuran WAV
        with sf.SoundFile(f"{stem}.wav") as src, \
                sf.SoundFile(f"{stem}.flac", "w", SR, 2, "PCM_24", format="FLAC") as dst:
            for b in src.blocks(blocksize=SR * 30, dtype="int32"):
                dst.write(b)
    if flac16:
        export_flac16(stem, seed)
    if qc:
        import qc as qc_mod
        r = qc_mod.analyze(f"{stem}.wav")
        text = qc_mod.report(r, profile=profile)
        with open(f"{stem}.qc.txt", "w") as f:
            f.write(text + "\n")
        with open(f"{stem}.qc.json", "w") as f:
            json.dump({k: v for k, v in r.items() if not k.startswith("_")}, f, indent=1)
        qc_mod.plot(r, f"{stem}.qc.png")
        return text
