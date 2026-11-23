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
                    p["reverb_hp"])
    reverb, hpf = fx.StreamReverb(ir), fx.StreamHighpass(30.0)
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
            layers = {k: v.astype(np.float64) for k, v in layers.items()}
            layers["pad"] = chorus(layers["pad"])
            layers["melody"] = delay(layers["melody"])
            dry = sum(layers.values())
            send = sum(layers[k] * p["send"][k] for k in layers)
            mix = dry * config.MIX["dry"] + reverb(send) * config.MIX["wet"]
            mix = hpf(mix)
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


def save_meta(stem, events, resolved_toml, lufs, mp3=True, flac=False, qc=True):
    with open(f"{stem}.toml", "w") as f:
        f.write(f"# loudness terukur: {lufs:.1f} LUFS\n" + resolved_toml)
    with open(f"{stem}.events.json", "w") as f:
        json.dump(to_dicts(events), f, indent=1)
    if mp3 and shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", f"{stem}.wav",
                        "-b:a", "192k", f"{stem}.mp3"], check=True)
    if flac:   # lossless, ~55-60% ukuran WAV
        with sf.SoundFile(f"{stem}.wav") as src, \
                sf.SoundFile(f"{stem}.flac", "w", SR, 2, "PCM_24", format="FLAC") as dst:
            for b in src.blocks(blocksize=SR * 30, dtype="int32"):
                dst.write(b)
    if qc:
        import qc as qc_mod
        r = qc_mod.analyze(f"{stem}.wav")
        text = qc_mod.report(r)
        with open(f"{stem}.qc.txt", "w") as f:
            f.write(text + "\n")
        with open(f"{stem}.qc.json", "w") as f:
            json.dump({k: v for k, v in r.items() if not k.startswith("_")}, f, indent=1)
        qc_mod.plot(r, f"{stem}.qc.png")
        return text
