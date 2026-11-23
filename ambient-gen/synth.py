"""Blok dasar sintesis: oscillator, envelope, filter, LFO."""
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

from config import SAMPLE_RATE as SR


def midi_to_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


TABLE = 4096


def _wavetable(freq, harmonics, kind):
    """Satu siklus gelombang band-limited (hanya harmonik di bawah Nyquist)."""
    ph = np.arange(TABLE) / TABLE * 2 * np.pi
    w = np.zeros(TABLE + 1)
    if kind == "saw":
        ks, amp = range(1, harmonics + 1), lambda i, k: 1 / k
        scale = 2 / np.pi
    else:
        ks, amp = range(1, harmonics * 2, 2), lambda i, k: (-1) ** i / k**2
        scale = 8 / np.pi**2
    for i, k in enumerate(ks):
        if k * freq >= SR / 2:
            break
        w[:TABLE] += amp(i, k) * np.sin(k * ph)
    w[TABLE] = w[0]
    return w * scale


def _read_table(table, freq, n, phase0):
    pos = (phase0 / (2 * np.pi) + freq * np.arange(n) / SR) % 1.0 * TABLE
    i = pos.astype(np.int64)
    frac = pos - i
    return table[i] * (1 - frac) + table[i + 1] * frac


def saw_additive(freq, n, phase0, harmonics):
    return _read_table(_wavetable(freq, harmonics, "saw"), freq, n, phase0)


def triangle_additive(freq, n, phase0, harmonics):
    return _read_table(_wavetable(freq, harmonics, "tri"), freq, n, phase0)


def sine(freq, n, phase0=0.0):
    return np.sin(2 * np.pi * freq * np.arange(n) / SR + phase0)


def envelope(n, attack, release, sustain_len=None):
    """Attack/release dengan kurva sinus-kuadrat (lebih halus dari linear)."""
    env = np.ones(n)
    a = min(int(attack * SR), n)
    r = min(int(release * SR), n - a)
    env[:a] = np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    if r > 0:
        env[n - r:] = np.cos(np.linspace(0, np.pi / 2, r)) ** 2
    return env


def lfo(n, period, phase0=0.0):
    """LFO sinus 0..1."""
    return 0.5 + 0.5 * np.sin(2 * np.pi * np.arange(n) / SR / period + phase0)


def moving_lowpass(x, cutoff, block=1024, order=2):
    """Low-pass yang cutoff-nya berubah per blok kecil; state filter dibawa antar blok."""
    out = np.empty_like(x)
    zi = None
    for s in range(0, len(x), block):
        fc = float(np.clip(cutoff[s], 20, SR / 2 - 100))
        sos = butter(order, fc, btype="low", fs=SR, output="sos")
        if zi is None:
            zi = sosfilt_zi(sos) * x[0]
        out[s:s + block], zi = sosfilt(sos, x[s:s + block], zi=zi)
    return out


def pad_voice(midi, duration, rng, p):
    """Satu nada pad stereo -> array (n, 2).

    Oscillator detune dibuat sekali lalu disebar di medan stereo (equal-power),
    sub di tengah. Dengan begitu L/R tetap berkorelasi dan aman saat didengar mono.
    """
    n = int(duration * SR)
    f0 = midi_to_hz(midi)
    L = np.zeros(n)
    R = np.zeros(n)
    k = p["n_osc"]
    for i in range(k):
        # detune tersebar rata + sedikit acak; pan dari kiri ke kanan
        spread = (i / (k - 1) * 2 - 1) if k > 1 else 0.0
        cents = spread * p["detune_cents"] + rng.uniform(-1.5, 1.5)
        f = f0 * 2 ** (cents / 1200)
        ph = rng.uniform(0, 2 * np.pi)
        x = p["saw_mix"] * saw_additive(f, n, ph, p["harmonics"])
        x += (1 - p["saw_mix"]) * triangle_additive(f, n, ph, p["harmonics"] // 2)
        pan = 0.5 + p.get("stereo_spread", 0.35) * spread  # tidak sampai ujung
        L += x * np.cos(pan * np.pi / 2)
        R += x * np.sin(pan * np.pi / 2)
    sub = p["sub_level"] * sine(f0 / 2, n, rng.uniform(0, 2 * np.pi)) * np.sqrt(0.5) * k / 2
    norm = 2 / k
    L = (L + sub) * norm
    R = (R + sub) * norm
    # LFO tiap kanal sedikit bergeser -> gerak stereo pelan
    lfo_phase = rng.uniform(0, 2 * np.pi)
    chans = []
    for ch, x in enumerate((L, R)):
        m = lfo(n, p["lfo_period"], lfo_phase + ch * 0.4)
        cutoff = p["cutoff_min"] * (p["cutoff_max"] / p["cutoff_min"]) ** m  # skala log
        chans.append(moving_lowpass(x, cutoff))
    out = np.stack(chans, axis=1)
    out *= envelope(n, p["attack"], p["release"])[:, None]
    return out


def bell_voice(midi, duration, rng, attack, decay, pan):
    """Nada melodi lembut: sinus + sedikit harmonik, decay eksponensial."""
    n = int(duration * SR)
    f0 = midi_to_hz(midi)
    t = np.arange(n) / SR
    x = (sine(f0 * 2 ** (rng.uniform(-3, 3) / 1200), n, rng.uniform(0, 6.28))
         + 0.3 * sine(f0 * 2, n, rng.uniform(0, 6.28)) * np.exp(-t / (decay * 0.4))
         + 0.08 * sine(f0 * 3.0, n, rng.uniform(0, 6.28)) * np.exp(-t / (decay * 0.2)))
    a = int(attack * SR)
    env = np.exp(-t / decay)
    env[:a] *= np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    tail = int(0.5 * SR)
    env[-tail:] *= np.linspace(1, 0, tail)
    x *= env
    return np.stack([x * np.cos(pan * np.pi / 2), x * np.sin(pan * np.pi / 2)], axis=1)


def pink_noise(n, rng):
    """Pink noise lewat pembentukan spektrum 1/f di domain frekuensi."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spec))
    f[0] = 1
    x = np.fft.irfft(spec / np.sqrt(f), n)
    return x / np.max(np.abs(x))


def moving_bandpass(x, center, q=1.2, block=1024):
    out = np.empty_like(x)
    zi = None
    for s in range(0, len(x), block):
        fc = float(np.clip(center[s], 40, SR / 2 - 1000))
        lo, hi = fc / (1 + 1 / (2 * q)), fc * (1 + 1 / (2 * q))
        sos = butter(2, [lo, hi], btype="band", fs=SR, output="sos")
        if zi is None:
            zi = np.zeros((sos.shape[0], 2))
        out[s:s + block], zi = sosfilt(sos, x[s:s + block], zi=zi)
    return out


def texture(duration, rng, p):
    """Angin/ruang: pink noise band-pass, dipandu tiga LFO berperiode prima."""
    n = int(duration * SR)
    chans = []
    for ch in range(2):
        noise = pink_noise(n, rng)
        m = np.mean([lfo(n, per, rng.uniform(0, 6.28)) for per in p["lfo_periods"]], axis=0)
        center = p["band_lo"] * (p["band_hi"] / p["band_lo"]) ** m
        amp = 0.4 + 0.6 * lfo(n, p["lfo_periods"][ch % 3] * 1.7, rng.uniform(0, 6.28))
        chans.append(moving_bandpass(noise, center) * amp)
    x = np.stack(chans, axis=1)
    return x / (np.max(np.abs(x)) + 1e-12)
