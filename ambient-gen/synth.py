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


MAX_HARM_HZ = 12_000.0   # harmonik di atas ini tidak dibuat (filter yang menentukan kecerahan)


def _wavetable(freq, harmonics, kind):
    """Satu siklus gelombang band-limited. harmonics=None -> sebanyak mungkin s/d MAX_HARM_HZ."""
    if harmonics is None:
        harmonics = max(1, int(MAX_HARM_HZ / freq))
        if kind != "saw":
            harmonics = harmonics // 2 + 1
    ph = np.arange(TABLE) / TABLE * 2 * np.pi
    w = np.zeros(TABLE + 1)
    if kind == "saw":
        ks, amp, scale = range(1, harmonics + 1), (lambda i, k: 1 / k), 2 / np.pi
    else:
        ks, amp, scale = range(1, harmonics * 2, 2), (lambda i, k: (-1) ** i / k**2), 8 / np.pi**2
    for i, k in enumerate(ks):
        if k * freq >= min(SR / 2, MAX_HARM_HZ * 1.01) or k > TABLE // 2 - 1:
            break
        w[:TABLE] += amp(i, k) * np.sin(k * ph)
    w[TABLE] = w[0]
    return w * scale


def _read_table(table, freq, idx, phase0, extra_cycles=None):
    """idx = indeks sampel absolut (array int). extra_cycles: deviasi fase (dalam siklus)."""
    cyc = phase0 / (2 * np.pi) + (freq / SR) * idx
    if extra_cycles is not None:
        cyc = cyc + extra_cycles
    pos = cyc % 1.0 * TABLE
    i = pos.astype(np.int64)
    frac = pos - i
    return table[i] * (1 - frac) + table[i + 1] * frac


def sine_at(freq, idx, phase0=0.0):
    return np.sin((2 * np.pi * freq / SR) * idx + phase0)


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


def lfo_at(t, period, phase0=0.0):
    """LFO sinus 0..1, t dalam detik."""
    return 0.5 + 0.5 * np.sin(2 * np.pi * t / period + phase0)


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


def drift_cycles(t, freq, cents, periods, phases):
    """Pitch drift analitik: deviasi nada d(t) = cents * rata-rata sinus lambat.
    Fase = integral frekuensi -> rumus tertutup, jadi render per segmen tetap identik."""
    k = freq * np.log(2) / 1200 * cents / len(periods)
    out = np.zeros_like(t)
    for P, ph in zip(periods, phases):
        out += -k * P / (2 * np.pi) * (np.cos(2 * np.pi * t / P + ph) - np.cos(ph))
    return out


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
        oscs.append(dict(spread=spread, f=f0 * 2 ** (cents / 1200), ph=rng.uniform(0, 2 * np.pi),
                         dper=rng.uniform(5, 23, 3), dph=rng.uniform(0, 2 * np.pi, 3),
                         mper=rng.uniform(25, 70), mph=rng.uniform(0, 2 * np.pi)))
    sub_ph = rng.uniform(0, 2 * np.pi)
    lfo_phase = rng.uniform(0, 2 * np.pi)

    start, idx = _span(offset, n, total_n)
    t = idx / SR
    L = np.zeros(len(idx))
    R = np.zeros(len(idx))
    drift = p.get("drift_cents", 0.0)
    wob = p.get("timbre_wobble", 0.0)
    harm = p.get("harmonics")
    for o in oscs:
        f = o["f"]
        ex = drift_cycles(t, f, drift, o["dper"], o["dph"]) if drift else None
        saw = _read_table(_wavetable(f, harm, "saw"), f, idx, o["ph"], ex)
        tri = _read_table(_wavetable(f, harm // 2 if harm else None, "tri"), f, idx, o["ph"], ex)
        mix = p["saw_mix"]
        if wob:   # kadar saw/triangle "bernapas" pelan per oscillator
            mix = np.clip(mix + wob * np.sin(2 * np.pi * t / o["mper"] + o["mph"]), 0, 1)
        x = mix * saw + (1 - mix) * tri
        pan = 0.5 + p.get("stereo_spread", 0.35) * o["spread"]
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
        chans.append(moving_filter(x, cutoff, q=p.get("resonance", 0.7071)))
    out = np.stack(chans, axis=1) * envelope_at(idx, total_n, p["attack"], p["release"])[:, None]
    out = out[offset - start:]
    return _fit(out, n)


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


def texture_segment(t_start, n, seed, seg, p, shape=None, mult=None):
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
        if mult is not None:     # babak: angin lebih kuat/lemah
            amp = amp * mult(t)
        chans.append((y * amp)[pre:])
    return np.stack(chans, axis=1) * 0.35   # ~ setara level normalisasi lama


# ---------- suara melodi: beberapa timbre ----------
# disamakan kira-kira ke loudness yang sama (diukur: RMS rangkaian 3 nada)
TIMBRE_GAIN = {"soft": 1.0, "glass": 0.9, "kalimba": 1.08, "piano": 2.2}

def melody_voice(timbre, midi, duration, rng, decay, pan, vel=1.0, offset=0, n=None, attack=1.2):
    """Nada melodi stereo. Semua angka acak diambil di depan -> render per segmen identik.

    timbre:
      soft  - sinus lembut dengan attack pelan (suara lama)
      glass - bel kaca: FM dengan rasio tidak harmonis, kilau yang cepat meredup
      kalimba - petikan lembut: fundamental + parsial tinggi yang sangat singkat
      piano - piano jauh & lembut: parsial sedikit tidak harmonis, dua senar, decay dua tahap
    """
    total_n = int(duration * SR)
    n = total_n - offset if n is None else n
    f0 = midi_to_hz(midi)
    ph = rng.uniform(0, 2 * np.pi, 12)
    det = 2 ** (rng.uniform(-3, 3) / 1200)
    idx = np.arange(offset, min(offset + n, total_n))
    t = idx / SR
    f = f0 * det

    if timbre == "glass":
        # rasio FM 2:1 -> semua sideband jatuh di harmonik (ganjil) dari nada, jadi menyatu dengan
        # chord. (Dulu 3.5 & parsial 2.76: berkilau tapi parsialnya di luar tangga nada = sumbang.)
        ratio = 2.0
        index = 1.1 * np.exp(-t / (decay * 0.15)) + 0.1
        mod = np.sin(2 * np.pi * f * ratio * t + ph[0])
        x = np.sin(2 * np.pi * f * t + ph[1] + index * mod)
        x += 0.18 * np.sin(2 * np.pi * f * 4.0 * 2 ** (4 / 1200) * t + ph[2]) * np.exp(-t / (decay * 0.2))
        env = np.exp(-t / decay)
        a_s = 0.03      # serangan sedikit lembut -> menyatu dengan pad, tidak "menusuk"
    elif timbre == "kalimba":
        x = np.sin(2 * np.pi * f * t + ph[0])
        # parsial "logam" kalimba di 6x (2 oktaf + kuint) alih-alih 5.95x: tetap ada kilau petikan,
        # tapi jatuh di nada yang harmonis
        x += 0.3 * np.sin(2 * np.pi * f * 6.0 * t + ph[1]) * np.exp(-t / 0.09)
        x += 0.15 * np.sin(2 * np.pi * f * 2 * t + ph[2]) * np.exp(-t / (decay * 0.25))
        env = np.exp(-t / (decay * 0.55))
        a_s = 0.014
    elif timbre == "piano":
        B = 0.0004
        x = np.zeros_like(t)
        for k in range(1, 9):
            fk = f * k * np.sqrt(1 + B * k * k)
            if fk > 9000:
                break
            amp = k ** -1.6 * np.exp(-(k - 1) * 0.25)          # palu lembut: parsial atas kecil
            dk = decay / (1 + 0.45 * (k - 1))
            for s, c in ((0, 0.0), (1, 0.8)):                   # dua senar, beda 0.8 cent
                x += 0.5 * amp * np.sin(2 * np.pi * fk * 2 ** (c / 1200) * t + ph[k + s]) \
                    * (0.55 * np.exp(-t / (dk * 0.12)) + 0.45 * np.exp(-t / dk))
        env = np.ones_like(t)
        a_s = 0.01
    else:  # soft
        x = (np.sin(2 * np.pi * f * t + ph[0])
             + 0.3 * np.sin(2 * np.pi * f0 * 2 * t + ph[1]) * np.exp(-t / (decay * 0.4))
             + 0.08 * np.sin(2 * np.pi * f0 * 3 * t + ph[2]) * np.exp(-t / (decay * 0.2)))
        env = np.exp(-t / decay)
        a_s = attack
    a = max(1, int(a_s * SR))
    m = idx < a
    env = env.copy()
    env[m] *= np.sin(idx[m] / a * np.pi / 2) ** 2
    tail = int(0.5 * SR)
    m = idx >= total_n - tail
    env[m] *= (total_n - idx[m]) / tail
    x = x * env * vel * TIMBRE_GAIN.get(timbre, 1.0)
    return _fit(np.stack([x * np.cos(pan * np.pi / 2), x * np.sin(pan * np.pi / 2)], axis=1), n)


# ---------- lapisan "awan": butir-butir suara pendek dari nada chord (granular) ----------
def cloud_segment(t_start, n, seed, chords, p, shape=None, sections=None):
    """Butir suara 80-450 ms di sekitar nada chord yang sedang berbunyi -> lapisan berkilau yang terus berubah.

    Butir dibuat per "ember" 1 detik dengan sumber acak [seed, 20, ember], jadi setiap butir hanya
    bergantung pada seed dan waktunya: render per segmen identik dengan render utuh.
    chords: daftar (start, dur, label, notes) dari compose.chord_progression.
    p: density (butir/detik), length (detik, rata-rata), octaves (daftar geser oktaf), level.
    """
    out = np.zeros((n, 2))
    if p["level"] <= 0 or not chords:
        return out
    s0 = int(round(t_start * SR))
    max_len = p["length"] * 2.0
    starts = np.array([c[0] for c in chords])
    b0 = int(np.floor(t_start - max_len)) - 1
    b1 = int(np.ceil((s0 + n) / SR)) + 1
    octs = np.array(p["octaves"], float)
    for b in range(max(0, b0), b1):
        rng = np.random.default_rng([seed, 20, b])
        dens = p["density"] * (0.35 + 0.9 * float(shape(b + 0.5)) if shape is not None else 1.0)
        if sections is not None:
            sec = sections.at(b)
            dens *= 0.6 + 0.4 * min(1.5, max(0.0, sec["melody"]))   # babak sepi -> awan lebih tipis
        k = rng.poisson(dens)
        for _ in range(k):
            t = b + rng.random()
            length = float(np.clip(rng.gamma(4.0, p["length"] / 4.0), 0.08, max_len))
            ci = int(np.searchsorted(starts, t, side="right") - 1)
            notes = chords[max(ci, 0)][3]
            midi = notes[int(rng.integers(len(notes)))] + 12 * octs[int(rng.integers(len(octs)))]
            f = midi_to_hz(midi) * 2 ** (rng.uniform(-8, 8) / 1200)
            amp = rng.uniform(0.35, 1.0)
            pan = rng.uniform(0.1, 0.9)
            ph = rng.uniform(0, 2 * np.pi, 3)
            # bagian butir yang jatuh di segmen ini
            g0 = int(round(t * SR))
            gl = int(length * SR)
            lo, hi = max(g0, s0), min(g0 + gl, s0 + n)
            if lo >= hi or f > 9000:
                continue
            idx = np.arange(lo - g0, hi - g0)
            u = idx / gl
            env = np.sin(np.pi * u) ** 2                       # jendela Hann: tanpa klik
            w = (np.sin(2 * np.pi * f * idx / SR + ph[0]) + 0.25 * np.sin(4 * np.pi * f * idx / SR + ph[1])
                 + 0.08 * np.sin(6 * np.pi * f * idx / SR + ph[2]))
            x = w * env * amp
            out[lo - s0:hi - s0, 0] += x * np.cos(pan * np.pi / 2)
            out[lo - s0:hi - s0, 1] += x * np.sin(pan * np.pi / 2)
    return out * p["level"]
