"""Blok dasar sintesis: oscillator, envelope, filter, LFO.

Setiap suara bisa di-render sebagian saja (mulai `offset` sampel, sepanjang `n`), dengan
hasil yang sama seperti me-render penuh lalu dipotong. Itu yang memungkinkan render
per segmen secara paralel (milestone 4). Semua fungsi waktu (LFO, envelope, kurva bentuk)
memakai waktu absolut; filter IIR "dipanaskan" dengan pre-roll pendek.
"""
import numpy as np
from scipy.signal import sosfilt, sosfilt_zi

from config import SAMPLE_RATE as SR

BLOCK = 1024              # filter berubah per blok ini (grid absolut dari awal suara)
PREROLL = 12 * BLOCK      # ~0.26 s: cukup untuk menstabilkan filter >= 100 Hz


def midi_to_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


# ---------- oscillator (wavetable band-limited) ----------
TABLE = 4096


def _wavetable(freq, harmonics, kind):
    """Satu siklus gelombang band-limited (hanya harmonik di bawah Nyquist)."""
    ph = np.arange(TABLE) / TABLE * 2 * np.pi
    w = np.zeros(TABLE + 1)
    if kind == "saw":
        ks, amp, scale = range(1, harmonics + 1), (lambda i, k: 1 / k), 2 / np.pi
    else:
        ks, amp, scale = range(1, harmonics * 2, 2), (lambda i, k: (-1) ** i / k**2), 8 / np.pi**2
    for i, k in enumerate(ks):
        if k * freq >= SR / 2:
            break
        w[:TABLE] += amp(i, k) * np.sin(k * ph)
    w[TABLE] = w[0]
    return w * scale


def _read_table(table, freq, idx, phase0):
    """idx = indeks sampel absolut (array int)."""
    pos = (phase0 / (2 * np.pi) + (freq / SR) * idx) % 1.0 * TABLE
    i = pos.astype(np.int64)
    frac = pos - i
    return table[i] * (1 - frac) + table[i + 1] * frac


def sine_at(freq, idx, phase0=0.0):
    return np.sin((2 * np.pi * freq / SR) * idx + phase0)


def sine(freq, n, phase0=0.0):
    return sine_at(freq, np.arange(n), phase0)


def saw_additive(freq, n, phase0, harmonics):
    return _read_table(_wavetable(freq, harmonics, "saw"), freq, np.arange(n), phase0)


def triangle_additive(freq, n, phase0, harmonics):
    return _read_table(_wavetable(freq, harmonics, "tri"), freq, np.arange(n), phase0)


# ---------- envelope & LFO ----------
def envelope_at(idx, total_n, attack, release):
    """Attack/release kurva sinus-kuadrat, dievaluasi pada indeks sampel absolut."""
    a = max(1, min(int(attack * SR), total_n))
    r = max(1, min(int(release * SR), total_n - a))
    env = np.ones(len(idx))
    m = idx < a
    env[m] = np.sin(idx[m] / a * np.pi / 2) ** 2
    m = idx >= total_n - r
    env[m] = np.cos((idx[m] - (total_n - r)) / r * np.pi / 2) ** 2
    env[idx >= total_n] = 0.0
    return env


def envelope(n, attack, release):
    return envelope_at(np.arange(n), n, attack, release)


def lfo_at(t, period, phase0=0.0):
    """LFO sinus 0..1, t dalam detik."""
    return 0.5 + 0.5 * np.sin(2 * np.pi * t / period + phase0)


def lfo(n, period, phase0=0.0):
    return lfo_at(np.arange(n) / SR, period, phase0)


# ---------- filter biquad (RBJ), koefisien dihitung vektor untuk semua blok ----------
def _biquad_sos(kind, fc, q):
    w0 = 2 * np.pi * np.clip(fc, 20, SR / 2 - 1000) / SR
    cw, alpha = np.cos(w0), np.sin(w0) / (2 * q)
    if kind == "low":
        b = np.stack([(1 - cw) / 2, 1 - cw, (1 - cw) / 2], -1)
    else:  # band-pass, puncak 0 dB
        b = np.stack([alpha, np.zeros_like(cw), -alpha], -1)
    a = np.stack([1 + alpha, -2 * cw, 1 - alpha], -1)
    return np.concatenate([b / a[:, :1], a / a[:, :1]], -1)   # (blok, 6)


def moving_filter(x, fc_per_block, kind="low", q=0.7071):
    """Filter yang cutoff-nya berubah tiap BLOCK sampel; state dibawa antar blok.
    x harus dimulai tepat di batas blok."""
    sos = _biquad_sos(kind, np.asarray(fc_per_block, float), q)
    out = np.empty_like(x)
    zi = sosfilt_zi(sos[:1]) * x[0] if kind == "low" else np.zeros((1, 2))
    for j, s in enumerate(range(0, len(x), BLOCK)):
        out[s:s + BLOCK], zi = sosfilt(sos[j:j + 1], x[s:s + BLOCK], zi=zi)
    return out


def _span(offset, n, total_n):
    """Mulai render dari batas blok sebelum (offset - PREROLL); kembalikan indeks absolut."""
    start = max(0, (offset - PREROLL) // BLOCK * BLOCK)
    end = min(offset + n, total_n)
    return start, np.arange(start, end)


def _block_times(start, length):
    return (start + np.arange(0, length, BLOCK)) / SR


# ---------- suara ----------
def pad_voice(midi, duration, rng, p, offset=0, n=None, t0=0.0, shape=None):
    """Nada pad stereo -> (n, 2), sampel [offset, offset+n) dari suara sepanjang `duration`.

    Oscillator detune dibuat sekali lalu disebar di medan stereo (equal-power),
    sub di tengah. t0 = waktu mulai event di lagu (untuk kurva bentuk `shape`).
    """
    total_n = int(duration * SR)
    n = total_n - offset if n is None else n
    f0 = midi_to_hz(midi)
    k = p["n_osc"]
    # semua angka acak diambil di depan dengan urutan tetap -> hasil sama untuk offset apa pun
    oscs = []
    for i in range(k):
        spread = (i / (k - 1) * 2 - 1) if k > 1 else 0.0
        cents = spread * p["detune_cents"] + rng.uniform(-1.5, 1.5)
        oscs.append((spread, f0 * 2 ** (cents / 1200), rng.uniform(0, 2 * np.pi)))
    sub_ph = rng.uniform(0, 2 * np.pi)
    lfo_phase = rng.uniform(0, 2 * np.pi)

    start, idx = _span(offset, n, total_n)
    L = np.zeros(len(idx))
    R = np.zeros(len(idx))
    for spread, f, ph in oscs:
        x = p["saw_mix"] * _read_table(_wavetable(f, p["harmonics"], "saw"), f, idx, ph)
        x += (1 - p["saw_mix"]) * _read_table(_wavetable(f, p["harmonics"] // 2, "tri"), f, idx, ph)
        pan = 0.5 + p.get("stereo_spread", 0.35) * spread
        L += x * np.cos(pan * np.pi / 2)
        R += x * np.sin(pan * np.pi / 2)
    sub = p["sub_level"] * sine_at(f0 / 2, idx, sub_ph) * np.sqrt(0.5) * k / 2
    L = (L + sub) * (2 / k)
    R = (R + sub) * (2 / k)

    tb = _block_times(start, len(idx))
    bright = 1.0
    if shape is not None:
        bright = 2 ** (p.get("shape_bright", 0.0) * (shape(t0 + tb) - 0.5))
    chans = []
    for ch, x in enumerate((L, R)):
        m = lfo_at(tb, p["lfo_period"], lfo_phase + ch * 0.4)
        cutoff = p["cutoff_min"] * (p["cutoff_max"] / p["cutoff_min"]) ** m * bright
        chans.append(moving_filter(x, cutoff))
    out = np.stack(chans, axis=1) * envelope_at(idx, total_n, p["attack"], p["release"])[:, None]
    out = out[offset - start:]
    return _fit(out, n)


def bell_voice(midi, duration, rng, attack, decay, pan, offset=0, n=None):
    """Nada melodi lembut: sinus + sedikit harmonik, decay eksponensial."""
    total_n = int(duration * SR)
    n = total_n - offset if n is None else n
    f0 = midi_to_hz(midi)
    ph = rng.uniform(0, 6.28, 3)
    det = 2 ** (rng.uniform(-3, 3) / 1200)
    idx = np.arange(offset, min(offset + n, total_n))
    t = idx / SR
    x = (sine_at(f0 * det, idx, ph[0])
         + 0.3 * sine_at(f0 * 2, idx, ph[1]) * np.exp(-t / (decay * 0.4))
         + 0.08 * sine_at(f0 * 3.0, idx, ph[2]) * np.exp(-t / (decay * 0.2)))
    a = int(attack * SR)
    tail = int(0.5 * SR)
    env = np.exp(-t / decay)
    m = idx < a
    env[m] *= np.sin(idx[m] / a * np.pi / 2) ** 2
    m = idx >= total_n - tail
    env[m] *= (total_n - idx[m]) / tail
    x *= env
    return _fit(np.stack([x * np.cos(pan * np.pi / 2), x * np.sin(pan * np.pi / 2)], axis=1), n)


def _fit(x, n):
    if len(x) >= n:
        return x[:n]
    return np.vstack([x, np.zeros((n - len(x), 2))])


# ---------- tekstur ----------
_PINK_RMS = 0.086   # RMS keluaran pink_filter untuk white noise standar (dikalibrasi)


def pink_filter(white):
    """Pink noise dari white noise (filter IIR 3 kutub, kemiringan -3 dB/oktaf). Bisa per segmen."""
    from scipy.signal import lfilter
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    return lfilter(b, a, white, axis=0)


def texture_segment(t_start, n, seed, seg, p, shape=None):
    """Tekstur angin untuk satu segmen: pink noise band-pass, dipandu tiga LFO prima.
    Noise tiap segmen memakai sumber acak sendiri; filter dipanaskan dengan pre-roll."""
    rng_lfo = np.random.default_rng([seed, 4])           # fase LFO: sama untuk semua segmen
    phases = rng_lfo.uniform(0, 6.28, (2, len(p["lfo_periods"]) + 1))
    rng = np.random.default_rng([seed, 4, seg])
    pre = PREROLL * 4
    white = rng.standard_normal((n + pre, 2))
    noise = pink_filter(white) / _PINK_RMS
    s0 = int(round(t_start * SR)) - pre
    chans = []
    for ch in range(2):
        tb = (s0 + np.arange(0, n + pre, BLOCK)) / SR
        m = np.mean([lfo_at(tb, per, phases[ch, i]) for i, per in enumerate(p["lfo_periods"])], axis=0)
        center = p["band_lo"] * (p["band_hi"] / p["band_lo"]) ** m
        y = moving_filter(noise[:, ch], center, kind="band", q=1.2)
        t = (s0 + np.arange(n + pre)) / SR
        amp = 0.4 + 0.6 * lfo_at(t, p["lfo_periods"][ch % 3] * 1.7, phases[ch, -1])
        if shape is not None:   # intensitas tinggi -> angin lebih terdengar
            k = p.get("shape_amount", 0.0)
            amp = amp * ((1 - k) + k * (0.25 + 1.5 * shape(t)))
        chans.append((y * amp)[pre:])
    return np.stack(chans, axis=1) * 0.35   # ~ setara level normalisasi lama
