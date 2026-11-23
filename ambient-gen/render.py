"""Membunyikan daftar event menjadi audio stereo, per lapisan.

render_segment() hanya me-render satu potongan waktu, sehingga lagu panjang bisa
dikerjakan paralel dan memorinya tetap kecil.
"""
import numpy as np

import config
from synth import pad_voice, bell_voice, texture_segment

SR = config.SAMPLE_RATE
LAYER_NAMES = ("drone", "pad", "melody", "texture")


def _layer(name):
    # dibaca saat render (bukan saat import) supaya preset bisa mengubah config
    return {"drone": (config.DRONE, config.DRONE_LEVEL),
            "pad": (config.PAD, config.PAD_LEVEL)}[name]


def event_rng(seed, e):
    """Sumber acak per event: hanya bergantung pada seed + identitas event."""
    return np.random.default_rng([seed, 3, int(e.start * 1000), e.midi, len(e.layer)])


def _event_audio(e, seed, offset, n):
    rng = event_rng(seed, e)
    if e.layer == "melody":
        p = config.MELODY
        if p["level"] <= 0:
            return None
        pan = rng.uniform(0.2, 0.8)
        return bell_voice(e.midi, e.dur, rng, p["attack"], p["decay"], pan, offset, n) * p["level"]
    params, level = _layer(e.layer)
    if level <= 0:
        return None
    if e.layer == "drone":
        # sub hanya pada nada drone terendah
        params = dict(params, sub_level=getattr(config, "DRONE_SUB", 0.0)
                      if e.midi == min(config.DRONE_NOTES) else 0.0)
    if e.layer == "pad":
        # crossfade: release chord lama berjalan selama chord baru masuk
        params = dict(params, attack=config.CHORD_OVERLAP, release=config.CHORD_OVERLAP)
    return pad_voice(e.midi, e.dur, rng, params, offset, n, t0=e.start, shape=config.SHAPE) * level


def render_segment(events, seg_start, seg_n, seed, seg_index=0):
    """Sampel [seg_start, seg_start+seg_n) untuk semua lapisan -> dict float32 (n, 2)."""
    out = {k: np.zeros((seg_n, 2)) for k in LAYER_NAMES}
    for e in events:
        es = int(round(e.start * SR))
        en = es + int(e.dur * SR)
        lo, hi = max(es, seg_start), min(en, seg_start + seg_n)
        if lo >= hi:
            continue
        x = _event_audio(e, seed, lo - es, hi - lo)
        if x is not None:
            out[e.layer][lo - seg_start:hi - seg_start] += x
    tp = config.TEXTURE
    if tp["level"] > 0:
        out["texture"] = texture_segment(seg_start / SR, seg_n, seed, seg_index,
                                         tp, config.SHAPE) * tp["level"]
    if seg_start < 20 * SR:   # fade-in tekstur 20 detik pertama
        t = (seg_start + np.arange(seg_n)) / SR
        out["texture"] *= np.clip(t / 20, 0, 1)[:, None]
    return {k: v.astype(np.float32) for k, v in out.items()}


def render_layers(events, total, seed):
    """Seluruh lagu sekaligus (untuk durasi pendek / milestone lama)."""
    n = int(total * SR)
    out = render_segment(events, 0, n, seed)
    return {k: v.astype(np.float64) for k, v in out.items() if k != "texture"}


def render_events(events, total, seed):
    """Mix kering drone + pad + melodi (dipakai milestone 2)."""
    return sum(render_layers(events, total, seed).values())
