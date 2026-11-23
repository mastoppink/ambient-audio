"""Komposisi: menghasilkan daftar event (start, durasi, nada, lapisan).

Komposisi terpisah dari rendering, jadi daftar event bisa disimpan ke JSON
dan suaranya bisa diganti tanpa mengubah komposisi.
"""
from dataclasses import dataclass, asdict

import numpy as np

import config

# Template chord sebagai derajat skala (0-based), berlaku untuk mode apa pun.
# Kunci = nama romawi relatif terhadap tonika; nilai = (derajat, bobot pemilihan).
CHORDS = {
    "I":   ([0, 2, 4, 1], 3.0),   # tonika + 9
    "II":  ([1, 3, 5, 0], 2.5),   # derajat 2 di atas pedal tonika (di Lydian: warna khas #4)
    "iii": ([2, 4, 6, 1], 1.5),
    "V":   ([4, 5, 1], 1.5),       # sus2
    "vi":  ([5, 0, 2, 6], 1.5),
    "vii": ([6, 1, 3, 5], 0.7),
}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def chord_label(name):
    root = (config.TONIC_MIDI + config.SCALE[CHORDS[name][0][0]]) % 12
    return f"{name}({NOTE_NAMES[root]})"


@dataclass
class Event:
    start: float
    dur: float
    midi: int
    layer: str
    label: str = ""
    vel: float = 1.0


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
    weights = np.array([config.CHORD_WEIGHTS.get(n, CHORDS[n][1]) for n in names], float)
    t, prev_name, prev_notes, out = 0.0, None, [], []
    while t < total:
        dur = rng.uniform(*config.CHORD_SECONDS)
        if prev_name is None:
            name = "I"  # mulai dari tonika
        else:
            w = weights.copy()
            w[names.index(prev_name)] = 0  # jangan ulang chord yang sama
            if w.sum() == 0:
                w[:] = 1; w[names.index(prev_name)] = 0
            name = rng.choice(names, p=w / w.sum())
        notes = voice_lead(prev_notes, degree_pcs(CHORDS[name][0]), *config.PAD_RANGE)
        out.append((t, dur, chord_label(name), notes))
        prev_name, prev_notes = name, notes
        t += dur - config.CHORD_OVERLAP
    return out


def _allowed_pcs(chord_notes):
    """Nada yang aman di atas chord: nada chord + nada skala yang tidak berjarak 1 semiton
    dari nada chord atau drone mana pun (minor 2nd = interval paling sumbang)."""
    pad = {n % 12 for n in chord_notes}
    ctx = pad | {d % 12 for d in config.DRONE_NOTES}
    scale = {(config.TONIC_MIDI + s) % 12 for s in config.SCALE}
    safe = {pc for pc in scale if all((pc - c) % 12 not in (1, 11) for c in ctx)}
    return pad | safe


def _snap(pool, idx, allowed):
    """Geser ke indeks terdekat yang nadanya diizinkan (deterministik, tanpa angka acak)."""
    if pool[idx] % 12 in allowed:
        return idx
    cand = [i for i in range(len(pool)) if pool[i] % 12 in allowed]
    return min(cand, key=lambda i: (abs(i - idx), i)) if cand else idx


def _allowed_at(t, ring, chords):
    """Nada aman untuk nada yang mulai di t dan masih terdengar selama `ring` detik:
    harus cocok dengan chord sekarang DAN chord berikutnya kalau pergantian terjadi saat itu."""
    cur_i = max(i for i, c in enumerate(chords) if c[0] <= t)
    allowed = _allowed_pcs(chords[cur_i][3])
    if cur_i > 0:
        prev = chords[cur_i - 1]
        if t < prev[0] + prev[1] - config.CHORD_OVERLAP * 0.5:   # chord lama masih terdengar
            allowed = (allowed & _allowed_pcs(prev[3])) or allowed
    for c in chords[cur_i + 1:]:
        # chord berikutnya mulai terdengar jelas setelah crossfade setengah jalan
        if c[0] + config.CHORD_OVERLAP * 0.5 < t + ring:
            both = allowed & _allowed_pcs(c[3])
            allowed = both or {n % 12 for n in c[3]}
        else:
            break
    return allowed


def melody(total, rng, chords):
    """Nada jarang: random walk berbobot pada skala, condong ke nada chord yang sedang bunyi.

    melody.consonance > 0: setiap nada (termasuk nada frasa) dijaga agar tidak berjarak
    1 semiton dari chord/drone, termasuk chord berikutnya kalau nada masih berdengung saat
    chord berganti. Tidak memakai angka acak tambahan, jadi consonance = 0 memberi hasil
    yang persis sama seperti sebelumnya.
    """
    p = config.MELODY
    lo, hi = p["range"]
    pool = [m for m in range(lo, hi + 1)
            if (m - config.TONIC_MIDI) % 12 in config.SCALE]
    cons = p.get("consonance", 0.0) > 0
    ring = p["decay"] * 1.2
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
        if cons:
            idx = _snap(pool, idx, _allowed_at(t, ring, chords))
        dur = min(p["decay"] * 2.5, total - t)
        keep = rng.random()   # selalu diambil -> urutan acak tidak bergantung pada kurva
        # frasa: kadang 2-3 nada berurutan (melangkah dekat, makin pelan), bukan nada tunggal
        is_phrase = rng.random() < p.get("phrase_prob", 0.0)
        n_extra = int(rng.integers(1, 3))
        steps = rng.choice([-2, -1, 1, 2], size=2, p=[.2, .35, .3, .15])
        spacing = rng.uniform(0.7, 1.9, size=2)
        if config.SHAPE is None or keep < 0.3 + 0.9 * float(config.SHAPE(t)):
            out.append(Event(round(t, 3), round(dur, 3), pool[idx], "melody", cur[2]))
            if is_phrase:
                tt, j = t, idx
                for k in range(n_extra):
                    tt += spacing[k]
                    j = int(np.clip(j + steps[k], 0, len(pool) - 1))
                    if cons:
                        j2 = _snap(pool, j, _allowed_at(tt, ring, chords))
                        if pool[j2] == out[-1].midi:     # jangan ulang nada yang sama
                            j2 = _snap(pool, int(np.clip(j + np.sign(steps[k]), 0, len(pool) - 1)),
                                       _allowed_at(tt, ring, chords))
                        j = j2
                    if tt < total - 8:
                        out.append(Event(round(tt, 3), round(min(dur, total - tt), 3), pool[j],
                                         "melody", cur[2], vel=round(0.75 - 0.15 * k, 2)))
        gap = rng.uniform(*p["gap"])
        if rng.random() < p["rest_prob"]:
            gap += rng.uniform(10, 30)
        t += gap
    return out


def compose(total, seed, with_melody=False):
    """Tiap lapisan memakai sumber acak sendiri yang hanya bergantung pada seed,
    jadi awal komposisi sama berapa pun durasinya (preview = awal versi panjang)."""
    events = [Event(0.0, total, m, "drone", "drone") for m in config.DRONE_NOTES]
    chords = chord_progression(total, np.random.default_rng([seed, 1]))
    for start, dur, name, notes in chords:
        dur = min(dur, total - start)
        events += [Event(round(start, 3), round(dur, 3), m, "pad", name) for m in notes]
    if with_melody:
        events += melody(total, np.random.default_rng([seed, 2]), chords)
    return events


def to_dicts(events):
    return [asdict(e) for e in events]
