"""Komposisi: menghasilkan daftar event (start, durasi, nada, lapisan).

Komposisi terpisah dari rendering, jadi daftar event bisa disimpan ke JSON
dan suaranya bisa diganti tanpa mengubah komposisi.
"""
from dataclasses import dataclass, asdict

import numpy as np

import config

# Chord sebagai derajat skala (0-based) dari D Lydian, dengan bobot pemilihan.
# I = D, II = E (mayor, ciri khas Lydian), iii = F#m, V = A, vi = Bm, vii = C#m
CHORDS = {
    "Dmaj9":   ([0, 2, 4, 1], 3.0),   # D F# A E
    "Emaj/D":  ([1, 3, 5, 0], 2.5),   # E G# B + D  (warna Lydian)
    "F#m7":    ([2, 4, 6, 1], 1.5),
    "Asus2":   ([4, 5, 1], 1.5),       # A B E
    "Bm9":     ([5, 0, 2, 6], 1.5),
    "C#m7":    ([6, 1, 3, 5], 0.7),
}


@dataclass
class Event:
    start: float
    dur: float
    midi: int
    layer: str
    label: str = ""


def degree_pcs(degrees):
    return [(config.SCALE[d % 7] + config.TONIC_MIDI) % 12 for d in degrees]


def voice_lead(prev, pcs, lo, hi):
    """Pilih nada untuk tiap pitch class, sedekat mungkin dengan voicing sebelumnya."""
    cands = [[m for m in range(lo, hi + 1) if m % 12 == pc] for pc in pcs]
    if not prev:
        center = (lo + hi) / 2
        notes = [min(c, key=lambda m: abs(m - center)) for c in cands]
    else:
        notes, used = [], set()
        for c in cands:
            best = min(c, key=lambda m: min(abs(m - p) for p in prev) + (6 if m in used else 0))
            notes.append(best)
            used.add(best)
    notes = sorted(set(notes))
    # hindari nada terlalu rapat di register rendah (cluster < 1 oktaf di bawah C4 jadi keruh)
    for i in range(1, len(notes)):
        if notes[i] < 60 and notes[i] - notes[i - 1] < 3 and notes[i] + 12 <= hi:
            notes[i] += 12
    return sorted(set(notes))


def chord_progression(total, rng):
    names = list(CHORDS)
    weights = np.array([CHORDS[n][1] for n in names])
    t, prev_name, prev_notes, out = 0.0, None, [], []
    while t < total:
        dur = rng.uniform(*config.CHORD_SECONDS)
        if prev_name is None:
            name = "Dmaj9"  # mulai dari tonika
        else:
            w = weights.copy()
            w[names.index(prev_name)] = 0  # jangan ulang chord yang sama
            name = rng.choice(names, p=w / w.sum())
        notes = voice_lead(prev_notes, degree_pcs(CHORDS[name][0]), *config.PAD_RANGE)
        out.append((t, dur, name, notes))
        prev_name, prev_notes = name, notes
        t += dur - config.CHORD_OVERLAP
    return out


def melody(total, rng, chords):
    """Nada jarang: random walk berbobot pada skala, condong ke nada chord yang sedang bunyi."""
    p = config.MELODY
    lo, hi = p["range"]
    pool = [m for m in range(lo, hi + 1)
            if (m - config.TONIC_MIDI) % 12 in config.SCALE]
    idx = len(pool) // 2
    t = rng.uniform(*p["gap"]) * 0.6
    out = []
    while t < total - 8:
        step = rng.choice([-2, -1, 1, 2, 3, -3, 0], p=[.2, .25, .25, .15, .05, .05, .05])
        idx = int(np.clip(idx + step, 0, len(pool) - 1))
        cur = [c for c in chords if c[0] <= t][-1]
        chord_pcs = {n % 12 for n in cur[3]}
        if pool[idx] % 12 not in chord_pcs and rng.random() < 0.6:
            near = [i for i in range(len(pool)) if pool[i] % 12 in chord_pcs]
            idx = min(near, key=lambda i: abs(i - idx))
        dur = min(p["decay"] * 2.5, total - t)
        out.append(Event(round(t, 3), round(dur, 3), pool[idx], "melody", cur[2]))
        gap = rng.uniform(*p["gap"])
        if rng.random() < p["rest_prob"]:
            gap += rng.uniform(10, 30)
        t += gap
    return out


def compose(total, rng, with_melody=False):
    events = [Event(0.0, total, m, "drone", "drone") for m in config.DRONE_NOTES]
    chords = chord_progression(total, rng)
    for start, dur, name, notes in chords:
        dur = min(dur, total - start)
        events += [Event(round(start, 3), round(dur, 3), m, "pad", name) for m in notes]
    if with_melody:
        events += melody(total, rng, chords)
    return events


def to_dicts(events):
    return [asdict(e) for e in events]
