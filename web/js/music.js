// Logika musik: RNG ber-seed, preset -> parameter, progresi chord, melodi.
// Port dari ambient-gen/settings.py dan compose.py. Karakter sama, tetapi urutan nada tidak identik
// dengan versi Python (generator acak berbeda).

// ---------- RNG ber-seed ----------
export function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function rngFor(seed, ...stream) {
  let h = 2166136261 ^ (seed | 0);
  for (const s of stream) {
    for (const ch of String(s)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    h = Math.imul(h ^ 0x9e3779b9, 16777619);
  }
  const r = mulberry32(h);
  r.uniform = (a, b) => a + (b - a) * r();
  r.int = (n) => Math.floor(r() * n);
  r.choice = (items, weights) => {
    const tot = weights.reduce((a, b) => a + b, 0);
    let x = r() * tot;
    for (let i = 0; i < items.length; i++) { x -= weights[i]; if (x < 0) return items[i]; }
    return items[items.length - 1];
  };
  return r;
}

// ---------- teori ----------
export const MODES = {
  ionian: [0, 2, 4, 5, 7, 9, 11], dorian: [0, 2, 3, 5, 7, 9, 10], phrygian: [0, 1, 3, 5, 7, 8, 10],
  lydian: [0, 2, 4, 6, 7, 9, 11], mixolydian: [0, 2, 4, 5, 7, 9, 10], aeolian: [0, 2, 3, 5, 7, 8, 10],
};
export const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const NOTES = { C: 0, "C#": 1, DB: 1, D: 2, "D#": 3, EB: 3, E: 4, F: 5, "F#": 6, GB: 6, G: 7,
  "G#": 8, AB: 8, A: 9, "A#": 10, BB: 10, B: 11 };
export const CHORDS = {
  I: [[0, 2, 4, 1], 3.0], II: [[1, 3, 5, 0], 2.5], iii: [[2, 4, 6, 1], 1.5],
  V: [[4, 5, 1], 1.5], vi: [[5, 0, 2, 6], 1.5], vii: [[6, 1, 3, 5], 0.7],
  // chord tambahan: hanya kalau variation > 0 dan tidak ada nada berjarak 1 semiton di dalamnya
  IV: [[3, 5, 0, 4], 1.0], Isus: [[0, 3, 4, 1], 0.8], I6: [[0, 2, 4, 5], 0.8],
};
export const EXTRA_CHORDS = ["IV", "Isus", "I6"];
export const FORM_TYPES = ["arc", "rise", "valley", "calm", "journey"];
export const midiToHz = (m) => 440 * 2 ** ((m - 69) / 12);
const mod = (a, n) => ((a % n) + n) % n;
const clip = (x, a, b) => Math.min(b, Math.max(a, x));
const lerpLog = (lo, hi, x) => lo * (hi / lo) ** x;

// ---------- preset ----------
// salinan dalam untuk data JSON biasa (structuredClone belum ada di iOS < 15.4)
export const clone = (v) => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

export function deepMerge(base, over) {
  const out = clone(base);
  for (const [k, v] of Object.entries(over || {})) {
    if (v && typeof v === "object" && !Array.isArray(v) && out[k] && typeof out[k] === "object"
        && !Array.isArray(out[k])) out[k] = deepMerge(out[k], v);
    else out[k] = clone(v);
  }
  return out;
}

const RANGE_KEYS = new Set(["pad.chord_seconds", "form.period_min"]);

/** Pilih nilai untuk setiap [min,max] dan daftar teks, berdasarkan seed (seperti settings.resolve). */
export function resolve(s, seed) {
  const r = rngFor(seed, "resolve");
  const walk = (node, path) => {
    const out = {};
    for (const [k, v] of Object.entries(node)) {
      const p = path ? `${path}.${k}` : k;
      if (v && typeof v === "object" && !Array.isArray(v) && k !== "chord_weights") out[k] = walk(v, p);
      else if (Array.isArray(v) && v.length === 2 && !RANGE_KEYS.has(p) && v.every((x) => typeof x === "number"))
        out[k] = Math.round(r.uniform(Math.min(...v), Math.max(...v)) * 1e4) / 1e4;
      else if (Array.isArray(v) && v.length && v.every((x) => typeof x === "string")) out[k] = v[r.int(v.length)];
      else out[k] = v;
    }
    return out;
  };
  const out = walk(s, "");
  out.seed = seed;
  return out;
}

/** Preset final -> parameter teknis (seperti settings.apply). */
export function technical(r, data) {
  const mode = String(r.key.mode).toLowerCase();
  const tonicName = String(r.key.tonic).toUpperCase();
  const pc = NOTES[tonicName] ?? 2;
  let t = pc <= 5 ? 48 + pc : 36 + pc;
  if (t < 46) t += 12;
  const scale = MODES[mode] || MODES.lydian;
  const pad = r.pad, mix = r.mix, m = r.melody, sp = r.space, fm = r.form;
  const cutMax = lerpLog(1100, 7000, pad.brightness);
  const dmax = lerpLog(300, 1500, r.drone.brightness);
  const meanGap = 8 + 60 * (1 - m.density);
  const mlo = t + 12 + Math.round(12 * m.register);
  const cs = pad.chord_seconds;
  return {
    tonic: t, scale, mode, tonicName,
    droneNotes: [t - 12, t - 5],
    padRange: [t + 2, t + 24],
    chordSeconds: cs, chordOverlap: Math.min(12, cs[0] * 0.3),
    chordWeights: pad.chord_weights || {},
    pad: { level: mix.pad, nOsc: data.pad_base.n_osc, cutMax, cutMin: cutMax * 0.23,
      sawMix: 0.25 + 0.5 * pad.brightness, detune: 3 + 12 * pad.width, spread: 0.1 + 0.5 * pad.width,
      lfoPeriod: lerpLog(120, 20, pad.movement), drift: 1 + 5 * pad.life, q: 0.9 + 0.4 * pad.brightness,
      shapeBright: fm.amount * fm.bright },
    drone: { level: mix.drone, nOsc: data.drone_base.n_osc, detune: data.drone_base.detune_cents,
      sawMix: data.drone_base.saw_mix, cutMax: dmax, cutMin: dmax * 0.28, lfoPeriod: data.drone_base.lfo_period,
      sub: 0.6 * r.drone.sub, attack: data.drone_base.attack },
    melody: { level: mix.melody, timbre: m.timbre, decay: m.decay, range: [mlo, mlo + 24],
      gap: [meanGap * 0.5, meanGap * 1.5], restProb: 0.25, phraseProb: m.phrases,
      consonance: m.consonance > 0, attack: data.melody_attack },
    texture: { level: mix.texture, bandLo: lerpLog(120, 600, r.texture.brightness),
      bandHi: lerpLog(1500, 7000, r.texture.brightness), periods: data.texture_base.lfo_periods,
      shapeAmount: fm.amount },
    fx: { decay: sp.reverb_decay, dry: 1 - 0.5 * sp.reverb_mix, wet: 2 * sp.reverb_mix,
      delayFeedback: sp.delay_feedback, delaySeconds: data.delay_seconds, delayMix: data.delay_mix,
      early: sp.early, width: sp.width, motion: sp.motion, shimmer: sp.shimmer,
      reverbType: sp.reverb_type || "hall", size: sp.size ?? 1,
      send: data.send, reverbHp: data.reverb_hp, predelay: data.reverb_predelay },
    form: fm, lufs: r.master.target_lufs, eq: data.eq, variation: r.variation?.amount ?? 0,
    warmth: { amount: r.warmth?.amount ?? 0, tape: r.warmth?.tape ?? 0, noise: r.warmth?.noise ?? 0 },
    cloud: (() => {
      const c = r.cloud || {}, reg = c.register ?? 0.5;
      return { level: mix.cloud ?? 0, density: c.density ?? 10, length: c.length ?? 0.25,
        octaves: reg < 0.34 ? [0, 1, 1] : reg < 0.67 ? [1, 1, 2] : [1, 2, 2] };
    })(),
  };
}

// ---------- kurva bentuk (intensitas 0..1) ----------
const smooth = (x) => { x = clip(x, 0, 1); return x * x * (3 - 2 * x); };

export function makeShape(total, seed, f) {
  const r = rngFor(seed, "form");
  const pm = f.period_min || [12, 25];
  const p1 = r.uniform(pm[0], pm[1]) * 60, p2 = r.uniform(pm[0], pm[1]) * 60;
  const ph1 = r.uniform(0, 2 * Math.PI), ph2 = r.uniform(0, 2 * Math.PI);
  const intro = (f.intro_min ?? 3) * 60, outro = (f.outro_min ?? 5) * 60, low = 0.2, amount = f.amount ?? 0.6;
  const kind = FORM_TYPES.includes(f.type) ? f.type : "arc";
  const span = total || 3600;                      // tanpa akhir: pola bentuk diulang tiap jam
  const jr = rngFor(seed, "journey"), plateau = jr.uniform(8, 14) * 60;
  const levels = Array.from({ length: Math.ceil(span / plateau) + 3 }, () => jr.uniform(0.25, 0.85));
  const base = (t) => {
    const wave = 0.5 + 0.32 * Math.sin((2 * Math.PI * t) / p1 + ph1) + 0.18 * Math.sin((2 * Math.PI * t) / p2 + ph2);
    const small = 0.5 + 0.5 * Math.sin((2 * Math.PI * t) / p1 + ph1);
    const u = (t % span) / span;
    if (kind === "arc") return wave;
    if (kind === "rise") return 0.2 + 0.65 * smooth(u / 0.68) - 0.25 * smooth((u - 0.75) / 0.25) + 0.12 * (small - 0.5);
    if (kind === "valley") return 0.72 - 0.5 * Math.sin(Math.PI * u) ** 2 + 0.12 * (small - 0.5);
    if (kind === "calm") return 0.32 + 0.08 * (small - 0.5);
    const k = (t % span) / plateau, i = Math.floor(k), fr = smooth(((k - i) * plateau) / 120);
    const L = (j) => levels[clip(j, 0, levels.length - 1)];
    return L(i) * (1 - fr) + L(i + 1) * fr;
  };
  const shape = (t) => {
    const c = 0.5 + amount * (base(t) - 0.5);
    const wi = intro > 0 ? clip(t / intro, 0, 1) : 1;
    const wo = total && outro > 0 ? clip((total - t) / outro, 0, 1) : 1;   // total=null: tanpa akhir
    const w = Math.min(Math.sin((wi * Math.PI) / 2) ** 2, Math.sin((wo * Math.PI) / 2) ** 2);
    return clip(low + (c - low) * w, 0, 1);
  };
  shape.kind = kind;
  return shape;
}

/** Babak: lagu dibagi bagian 8-18 menit dengan karakter berbeda (lihat ambient-gen/form.py). */
export class Sections {
  constructor(seed, amount, allowRest = true, horizon = 6 * 3600) {
    const r = rngFor(seed, "sections"), a = amount;
    this.list = [];
    for (let t = 0, first = true; t < horizon; first = false) {
      const len = r.uniform(8, 18) * 60;
      const rest = !first && allowRest && r() < 0.18 * a;
      const mel = rest ? 0 : r.uniform(1 - 0.5 * a, 1 + 0.6 * a);
      const reg = first ? (r(), 0) : Math.round(r.uniform(-3, 3) * a);
      this.list.push({ start: t, end: t + len, melody: mel, register: reg,
        texture: r.uniform(1 - 0.6 * a, 1 + 0.9 * a), favor: ["I", "II", "iii", "V", "vi", "vii"][r.int(6)], boost: 1 + 2 * a });
      t += len;
    }
  }
  at(t) { return this.list.find((s) => s.start <= t && t < s.end) || this.list[this.list.length - 1]; }
  index(t) { return this.list.indexOf(this.at(t)); }
  textureMult(t) {
    let out = this.list[0].texture;
    for (const s of this.list.slice(1)) { if (s.start - 20 > t) break; const k = smooth((t - s.start + 20) / 40); out = out * (1 - k) + s.texture * k; }
    return out;
  }
}

// ---------- komposisi (dibuat bertahap, cocok untuk pemutaran tanpa akhir) ----------
function degreePcs(P, degrees) { return degrees.map((d) => (P.scale[d % 7] + P.tonic) % 12); }

function voiceLead(prev, pcs, lo, hi) {
  const cands = pcs.map((pc) => { const c = []; for (let m = lo; m <= hi; m++) if (mod(m, 12) === pc) c.push(m); return c; });
  let notes;
  if (!prev.length) {
    const center = (lo + hi) / 2;
    notes = cands.map((c) => c.reduce((a, b) => (Math.abs(b - center) < Math.abs(a - center) ? b : a)));
  } else {
    notes = []; const used = new Set();
    for (const c of cands) {
      const score = (m) => Math.min(...prev.map((p) => Math.abs(m - p))) + (used.has(m) ? 6 : 0);
      const best = c.reduce((a, b) => (score(b) < score(a) ? b : a));
      notes.push(best); used.add(best);
    }
  }
  notes = [...new Set(notes)].sort((a, b) => a - b);
  for (let i = 1; i < notes.length; i++)
    if (notes[i] < 60 && notes[i] - notes[i - 1] < 3 && notes[i] + 12 <= hi) notes[i] += 12;
  return [...new Set(notes)].sort((a, b) => a - b);
}

export function chordLabel(P, name) {
  return `${name} (${NOTE_NAMES[(P.tonic + P.scale[CHORDS[name][0][0]]) % 12]})`;
}

export class Composer {
  constructor(P, seed, shape, sections = null) {
    this.P = P; this.shape = shape; this.sections = sections;
    this.seed = seed;
    this._weights();
    this.rc = rngFor(seed, "chords"); this.rm = rngFor(seed, "melody");
    this.chords = []; this.nextChordT = 0; this.prevName = null; this.prevNotes = [];
    const [lo, hi] = P.melody.range;
    this.pool = [];
    for (let m = lo; m <= hi; m++) if (P.scale.includes(mod(m - P.tonic, 12))) this.pool.push(m);
    this.mIdx = Math.floor(this.pool.length / 2);
    this.nextMelT = this.rm.uniform(...P.melody.gap) * 0.6;
  }

  /** Pastikan chord sudah dibuat sampai waktu t (+ satu chord ke depan). */
  chordsUntil(t) {
    const P = this.P, names = Object.keys(CHORDS);
    while (this.nextChordT <= t + 200) {
      const dur = this.rc.uniform(...P.chordSeconds);
      let name;
      if (this.prevName === null) name = "I";
      else {
        const sec = this.sections?.at(this.nextChordT);
        const w = names.map((n) => (n === this.prevName ? 0 : this.weights[n] * (sec && sec.favor === n ? sec.boost : 1)));
        if (w.every((x) => x === 0)) names.forEach((n, i) => { w[i] = n === this.prevName ? 0 : 1; });
        name = this.rc.choice(names, w);
      }
      const notes = voiceLead(this.prevNotes, degreePcs(P, CHORDS[name][0]), ...P.padRange);
      this.chords.push({ start: this.nextChordT, dur, name, label: chordLabel(P, name), notes });
      this.prevName = name; this.prevNotes = notes;
      this.nextChordT += dur - P.chordOverlap;
    }
  }

  /** bobot chord: chord tambahan hanya kalau cocok; "rasa harmoni" sedikit berbeda per versi */
  _weights() {
    const P = this.P, jr = rngFor(this.seed, "harmony");
    this.weights = {};
    for (const n of Object.keys(CHORDS)) {
      let w = P.chordWeights[n] ?? CHORDS[n][1];
      if (EXTRA_CHORDS.includes(n)) w = P.variation > 0 && this._chordOk(n) ? w * P.variation : 0;
      const j = jr.uniform(-0.6, 0.6);
      if (P.variation > 0) w *= Math.exp(j * P.variation);
      this.weights[n] = w;
    }
  }

  /** Parameter baru saat lagu berjalan: berlaku untuk chord & nada berikutnya. */
  setParams(P) {
    const oldRange = this.P.melody.range.join(), cur = this.pool[this.mIdx];
    this.P = P;
    this._weights();
    if (P.melody.range.join() !== oldRange) {
      const [lo, hi] = P.melody.range;
      this.pool = [];
      for (let m = lo; m <= hi; m++) if (P.scale.includes(mod(m - P.tonic, 12))) this.pool.push(m);
      let best = 0; this.pool.forEach((m, i) => { if (Math.abs(m - cur) < Math.abs(this.pool[best] - cur)) best = i; });
      this.mIdx = best;
    }
  }

  _chordOk(name) {
    const pcs = degreePcs(this.P, CHORDS[name][0]);
    return pcs.every((a) => pcs.every((b) => a === b || ![1, 11].includes(mod(a - b, 12))));
  }

  chordAt(t) { let c = this.chords[0]; for (const x of this.chords) if (x.start <= t) c = x; return c; }

  _allowedPcs(notes) {
    const P = this.P;
    const pad = new Set(notes.map((n) => mod(n, 12)));
    const ctx = new Set([...pad, ...P.droneNotes.map((d) => mod(d, 12))]);
    const out = new Set(pad);
    for (const s of P.scale) {
      const pc = (P.tonic + s) % 12;
      if ([...ctx].every((c) => ![1, 11].includes(mod(pc - c, 12)))) out.add(pc);
    }
    return out;
  }

  _allowedAt(t, ring) {
    const P = this.P;
    let i = 0;   // indeks chord terakhir yang sudah mulai (findLastIndex belum ada di iOS < 15.4)
    for (let j = 0; j < this.chords.length; j++) if (this.chords[j].start <= t) i = j;
    let allowed = this._allowedPcs(this.chords[i].notes);
    const inter = (a, b) => new Set([...a].filter((x) => b.has(x)));
    if (i > 0) {
      const prev = this.chords[i - 1];
      if (t < prev.start + prev.dur - P.chordOverlap * 0.5) { const b = inter(allowed, this._allowedPcs(prev.notes)); if (b.size) allowed = b; }
    }
    for (const c of this.chords.slice(i + 1)) {
      if (c.start + P.chordOverlap * 0.5 < t + ring) {
        const b = inter(allowed, this._allowedPcs(c.notes));
        allowed = b.size ? b : new Set(c.notes.map((n) => mod(n, 12)));
      } else break;
    }
    return allowed;
  }

  _snap(idx, allowed) {
    if (allowed.has(mod(this.pool[idx], 12))) return idx;
    let best = idx, bd = 1e9;
    this.pool.forEach((m, i) => { if (allowed.has(mod(m, 12)) && Math.abs(i - idx) < bd) { bd = Math.abs(i - idx); best = i; } });
    return best;
  }

  /** Nada melodi yang mulai sebelum t. */
  melodyUntil(t) {
    const P = this.P, M = P.melody, r = this.rm, out = [];
    if (M.level <= 0) return out;
    this.chordsUntil(t + 60);
    const ring = M.decay * 1.2;
    while (this.nextMelT < t) {
      const tm = this.nextMelT;
      const step = r.choice([-2, -1, 1, 2, 3, -3, 0], [0.2, 0.25, 0.25, 0.15, 0.05, 0.05, 0.05]);
      this.mIdx = clip(this.mIdx + step, 0, this.pool.length - 1);
      const cur = this.chordAt(tm);
      const cpcs = new Set(cur.notes.map((n) => mod(n, 12)));
      if (!cpcs.has(mod(this.pool[this.mIdx], 12)) && r() < 0.6) {
        let best = this.mIdx, bd = 1e9;
        this.pool.forEach((m, i) => { if (cpcs.has(mod(m, 12)) && Math.abs(i - this.mIdx) < bd) { bd = Math.abs(i - this.mIdx); best = i; } });
        this.mIdx = best;
      }
      if (M.consonance) this.mIdx = this._snap(this.mIdx, this._allowedAt(tm, ring));
      const keep = r(), isPhrase = r() < M.phraseProb, nExtra = 1 + r.int(2);
      const steps = [r.choice([-2, -1, 1, 2], [0.2, 0.35, 0.3, 0.15]), r.choice([-2, -1, 1, 2], [0.2, 0.35, 0.3, 0.15])];
      const spacing = [r.uniform(0.7, 1.9), r.uniform(0.7, 1.9)];
      const sec = this.sections?.at(tm), dens = sec ? sec.melody : 1, reg = sec ? sec.register : 0;
      let base = this.mIdx;
      if (dens > 0 && keep < (0.3 + 0.9 * this.shape(tm)) * dens) {
        if (reg) {   // babak ini: melodi digeser beberapa langkah (jalan acaknya tidak berubah)
          base = clip(this.mIdx + reg, 0, this.pool.length - 1);
          if (M.consonance) base = this._snap(base, this._allowedAt(tm, ring));
        }
        out.push({ t: tm, midi: this.pool[base], vel: 1 });
        if (isPhrase) {
          let tt = tm, j = base;
          for (let k = 0; k < nExtra; k++) {
            tt += spacing[k];
            j = clip(j + steps[k], 0, this.pool.length - 1);
            if (M.consonance) {
              let j2 = this._snap(j, this._allowedAt(tt, ring));
              if (this.pool[j2] === out[out.length - 1].midi)
                j2 = this._snap(clip(j + Math.sign(steps[k]), 0, this.pool.length - 1), this._allowedAt(tt, ring));
              j = j2;
            }
            out.push({ t: tt, midi: this.pool[j], vel: Math.round((0.75 - 0.15 * k) * 100) / 100 });
          }
        }
      }
      let gap = r.uniform(...M.gap);
      if (r() < M.restProb) gap += r.uniform(10, 30);
      this.nextMelT += gap;
    }
    return out;
  }
}
