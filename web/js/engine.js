// Mesin audio Web Audio. Bekerja untuk AudioContext (pemutaran langsung, tanpa akhir) maupun
// OfflineAudioContext (ekspor WAV). Struktur sama dengan ambient-gen/pipeline.py:
// lapisan (drone, pad, melodi, tekstur) -> EQ -> efek lapisan -> kering + kirim ke reverb -> master.
//
// Performa: semua suara dihitung oleh mesin audio bawaan browser (native). Thread halaman hanya
// menjadwalkan. Reverb dibuat async lewat OfflineAudioContext dan disimpan di cache; perubahan slider
// diterapkan langsung lewat update() tanpa membangun ulang mesin.
import { rngFor, midiToHz, Composer, makeShape, Sections } from "./music.js";
import { makeIRAsync, pinkBufferCached } from "./dsp.js";

const CURVE_HZ = 8;                 // resolusi kurva otomasi (titik per detik)
const DRONE_CHUNK = 240;            // drone dibuat per potongan (detik), disambung crossfade
const DRONE_XF = 20;
const TEX_CHUNK = 30;
const TIMBRE_GAIN = { soft: 1.0, glass: 0.9, kalimba: 1.08, piano: 2.2 };
const GLIDE = 0.6;                  // detik: transisi saat parameter diubah langsung

function curve(dur, fn) {
  const n = Math.max(2, Math.ceil(dur * CURVE_HZ) + 1), c = new Float32Array(n);
  for (let i = 0; i < n; i++) c[i] = fn((i / (n - 1)) * dur);
  return c;
}

export class Engine {
  /** Buat mesin dan tunggu reverb siap (tidak memblokir halaman). */
  static async create(ctx, P, seed, opts = {}) {
    const e = new Engine(ctx, P, seed, opts);
    await e._loadIR(P.fx, true);
    return e;
  }

  /**
   * @param ctx AudioContext atau OfflineAudioContext (48 kHz)
   * @param P parameter teknis (music.technical)
   * @param total durasi lagu (detik) atau null untuk tanpa akhir
   */
  constructor(ctx, P, seed, { total = null, offline = false, start = null } = {}) {
    this.ctx = ctx; this.P = P; this.seed = seed; this.total = total; this.offline = offline;
    this.startAt = start;
    this.t0 = start ?? ctx.currentTime + 0.15;
    this.shape = makeShape(total, seed, P.form);
    this.sections = this._sections(P);
    this.comp = new Composer(P, seed, this.shape, this.sections);
    this.scheduledChord = 0; this.droneChunk = 0; this.texChunk = 0; this.nodes = new Set();
    this.voices = [];               // pad/drone yang dijadwalkan: untuk diubah langsung
    this._build();
    this._applyLevels(0);
  }

  /** Mulai pemutaran: waktu nol lagu = sekarang (dipanggil setelah create selesai). */
  begin() {
    if (!this.offline && this.startAt == null) this.t0 = this.ctx.currentTime + 0.1;
    for (const n of this._startLater) n.start(this.t0);
    this._startLater = [];
  }

  now() { return this.ctx.currentTime - this.t0; }
  _sections(P) { return P.variation > 0 ? new Sections(this.seed, P.variation, P.melody.level > 0, this.total ?? 6 * 3600) : null; }

  // ---------- graf ----------
  _eq(input, bands) {
    let node = input;
    const map = { hp: "highpass", lp: "lowpass", peak: "peaking", lowshelf: "lowshelf", highshelf: "highshelf" };
    for (const [kind, f, g, q] of bands || []) {
      const b = this.ctx.createBiquadFilter();
      b.type = map[kind]; b.frequency.value = f; b.gain.value = g;
      b.Q.value = kind.endsWith("shelf") ? 0.7 : q;
      node.connect(b); node = b;
    }
    return node;
  }

  _modDelay(input, { centre, depth, rate, mix }) {
    // chorus stereo: delay kiri dan kanan dimodulasi LFO yang sama dengan fase berlawanan
    const ctx = this.ctx, out = ctx.createChannelMerger(2), dry = ctx.createGain(), sum = ctx.createGain();
    const split = ctx.createChannelSplitter(2), lfo = ctx.createOscillator();
    lfo.frequency.value = rate; this._startLater.push(lfo); this.nodes.add(lfo);
    dry.gain.value = 1 - mix;
    input.connect(dry).connect(sum);
    input.connect(split);
    for (let ch = 0; ch < 2; ch++) {
      const d = ctx.createDelay(0.1), amt = ctx.createGain(), wet = ctx.createGain();
      d.delayTime.value = centre; amt.gain.value = ch ? -depth : depth; wet.gain.value = mix;
      lfo.connect(amt).connect(d.delayTime);
      split.connect(d, ch); d.connect(wet).connect(out, 0, ch);
    }
    out.connect(sum);
    return sum;
  }

  _build() {
    const ctx = this.ctx, P = this.P, F = P.fx;
    this._startLater = [];
    this.master = ctx.createGain();
    const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 25;
    this.masterGain = ctx.createGain();
    this.out = ctx.createGain();
    this.master.connect(hp).connect(this.masterGain);
    if (this.offline) this.masterGain.connect(this.out);
    else {   // limiter sederhana untuk pemutaran langsung; ekspor memakai limiter lookahead di dsp.js
      const lim = ctx.createDynamicsCompressor();
      lim.threshold.value = -2; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = 0.002; lim.release.value = 0.2;
      this.masterGain.connect(lim).connect(this.out);
    }
    this.out.connect(ctx.destination);
    this.meterTap = this.masterGain;      // titik ukur loudness (sebelum limiter)

    this.dryBus = ctx.createGain(); this.dryBus.gain.value = F.dry; this.dryBus.connect(this.master);
    this.revIn = ctx.createGain();
    this.revOut = ctx.createGain();       // keluaran semua konvolver (bisa lebih dari satu saat bertukar IR)
    let wet = this.revOut;
    if (F.motion > 0) wet = this._modDelay(this.revOut, { centre: 0.014, depth: 0.003, rate: 0.07, mix: 0.5 * F.motion });
    this.wetGain = ctx.createGain(); this.wetGain.gain.value = F.wet;
    this._eq(wet, P.eq.reverb).connect(this.wetGain).connect(this.master);

    this.layerIn = {}; this.layerLvl = {};
    for (const k of ["drone", "pad", "melody", "texture"]) {
      const inp = ctx.createGain(), lvl = ctx.createGain();   // lvl: level lapisan, bisa diubah langsung
      inp.connect(lvl);
      let node = this._eq(lvl, P.eq[k]);
      if (k === "pad") node = this._modDelay(node, { centre: 0.009, depth: 0.0015, rate: 0.12, mix: 0.35 });
      if (k === "melody") {
        const out = ctx.createGain(), dry = ctx.createGain(), wetG = ctx.createGain(), d = ctx.createDelay(5);
        this.delayFb = ctx.createGain();
        d.delayTime.value = F.delaySeconds; this.delayFb.gain.value = F.delayFeedback;
        dry.gain.value = 1 - F.delayMix; wetG.gain.value = F.delayMix;
        node.connect(dry).connect(out); node.connect(d); d.connect(this.delayFb).connect(d); d.connect(wetG).connect(out);
        node = out;
      }
      node.connect(this.dryBus);
      const send = ctx.createGain(); send.gain.value = F.send[k]; node.connect(send).connect(this.revIn);
      this.layerIn[k] = inp; this.layerLvl[k] = lvl;
    }
    // tekstur: pink noise loop -> band-pass bergerak (per kanal) -> amplitudo. Selalu dibangun,
    // supaya level angin bisa dinaikkan dari 0 secara langsung.
    const src = ctx.createBufferSource(); src.buffer = pinkBufferCached(ctx); src.loop = true;
    const split = ctx.createChannelSplitter(2), merge = ctx.createChannelMerger(2);
    src.connect(split);
    this.texBand = []; this.texAmp = [];
    for (let ch = 0; ch < 2; ch++) {
      const bp = ctx.createBiquadFilter(); bp.type = "bandpass"; bp.Q.value = 1.2;
      const g = ctx.createGain(); g.gain.value = 0;
      split.connect(bp, ch); bp.connect(g).connect(merge, 0, ch);
      this.texBand.push(bp); this.texAmp.push(g);
    }
    merge.connect(this.layerIn.texture);
    this._startLater.push(src); this.nodes.add(src);
    const r = rngFor(this.seed, "texlfo");
    this.texPh = [0, 1].map(() => P.texture.periods.map(() => r.uniform(0, 6.28)).concat([r.uniform(0, 6.28)]));
    if (this.offline) this.begin();
  }

  async _loadIR(F, first = false) {
    const key = { decay: F.decay, predelay: F.predelay, hp: F.reverbHp, early: F.early, width: F.width };
    const buf = await makeIRAsync(this.ctx.sampleRate, this.seed, key);
    if (this.stopped) return;
    const conv = this.ctx.createConvolver(); conv.normalize = false; conv.buffer = buf;
    const g = this.ctx.createGain();
    this.revIn.connect(conv).connect(g).connect(this.revOut);
    if (first || this.offline) { g.gain.value = 1; this.conv = { conv, g }; return; }
    // tukar IR dengan crossfade, supaya tidak ada klik
    const t = this.ctx.currentTime, old = this.conv;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(1, t + 1.5);
    old.g.gain.setValueAtTime(old.g.gain.value, t); old.g.gain.linearRampToValueAtTime(0, t + 1.5);
    setTimeout(() => { old.conv.disconnect(); old.g.disconnect(); }, 2000);
    this.conv = { conv, g };
  }

  // ---------- suara ----------
  _filterFn(v, ch) {
    const p = v.p;
    return (x) => {
      const m = 0.5 + 0.5 * Math.sin((2 * Math.PI * x) / p.lfoPeriod + v.lfoPh + ch * 0.4);
      const bright = v.shapeBright ? 2 ** (v.shapeBright * (this.shape(v.songT + x) - 0.5)) : 1;
      return Math.min(this.ctx.sampleRate * 0.45, p.cutMin * (p.cutMax / p.cutMin) ** m * bright);
    };
  }

  _padVoice(dest, p, midi, songT, dur, rng, { attack, release, subLevel = 0, shapeBright = 0, fadeShape = "sin2", kind = "pad" }) {
    const ctx = this.ctx, t = this.t0 + songT, f0 = midiToHz(midi), k = p.nOsc;
    const NH = 64, real = new Float32Array(NH), imag = new Float32Array(NH);
    for (let h = 1; h < NH; h++) {
      const saw = (2 / Math.PI) / h;
      const tri = h % 2 ? (8 / Math.PI ** 2) * ((((h - 1) / 2) % 2) ? -1 : 1) / (h * h) : 0;
      imag[h] = p.sawMix * saw + (1 - p.sawMix) * tri;
    }
    const wave = ctx.createPeriodicWave(real, imag, { disableNormalization: true });
    const bus = ctx.createGain(); bus.channelCount = 2; bus.channelCountMode = "explicit";
    const oscs = [];
    for (let i = 0; i < k; i++) {
      const spread = k > 1 ? (i / (k - 1)) * 2 - 1 : 0;
      const cents = spread * p.detune + rng.uniform(-1.5, 1.5);
      const per = [rng.uniform(5, 23), rng.uniform(5, 23), rng.uniform(5, 23)], ph = per.map(() => rng.uniform(0, 6.28));
      const o = ctx.createOscillator(); o.setPeriodicWave(wave); o.frequency.value = f0;
      const drift = p.drift || 0;
      this._curve(o.detune, t, dur, (x) => cents + (drift / 3) * per.reduce((a, P_, j) => a + Math.sin((2 * Math.PI * x) / P_ + ph[j]), 0));
      const g = ctx.createGain(); g.gain.value = 2 / k;
      const pan = ctx.createStereoPanner(); pan.pan.value = (p.spread ?? 0.35) * spread;
      o.connect(g).connect(pan).connect(bus);
      oscs.push(o);
    }
    if (subLevel > 0) {
      const s = ctx.createOscillator(); s.frequency.value = f0 / 2;
      // 0.6: dikalibrasi agar pita sub setara versi Python (diukur dengan qc.py)
      const g = ctx.createGain(); g.gain.value = subLevel * Math.SQRT1_2 * 0.6;
      s.connect(g).connect(bus); oscs.push(s);
    }
    const v = { kind, p, songT, dur, lfoPh: rng.uniform(0, 6.28), shapeBright, flts: [] };
    const sp = ctx.createChannelSplitter(2), mg = ctx.createChannelMerger(2);
    bus.connect(sp);
    for (let ch = 0; ch < 2; ch++) {
      const flt = ctx.createBiquadFilter(); flt.type = "lowpass"; flt.Q.value = p.q ?? 0.7071;
      this._curve(flt.frequency, t, dur, this._filterFn(v, ch));
      sp.connect(flt, ch); flt.connect(mg, 0, ch); v.flts.push(flt);
    }
    const env = ctx.createGain(); env.gain.value = 0;
    const a = Math.min(attack, dur / 2), r = Math.min(release, dur - a);
    const fade = fadeShape === "sin" ? (u) => Math.sin((u * Math.PI) / 2) : (u) => Math.sin((u * Math.PI) / 2) ** 2;
    this._curve(env.gain, t, dur, (x) => (x < a ? fade(x / a) : x > dur - r ? fade(Math.max(0, (dur - x) / r)) : 1));
    mg.connect(env).connect(dest);
    for (const o of oscs) { o.start(t); o.stop(t + dur + 0.05); this._track(o); }
    if (!this.offline) this.voices.push(v);
  }

  _melodyVoice(midi, songT, vel, rng) {
    const ctx = this.ctx, M = this.P.melody, t = this.t0 + songT, decay = M.decay;
    const f = midiToHz(midi) * 2 ** (rng.uniform(-3, 3) / 1200);
    const pan = ctx.createStereoPanner(); pan.pan.value = rng.uniform(0.2, 0.8) * 2 - 1;
    const out = ctx.createGain(); out.gain.value = vel * (TIMBRE_GAIN[M.timbre] ?? 1);   // level di lapisan
    out.connect(pan).connect(this.layerIn.melody);
    const len = Math.min(decay * 2.5, 40), oscs = [];
    const partial = (freq, amp, tau, attack) => {
      const o = ctx.createOscillator(); o.frequency.value = freq;
      const g = ctx.createGain(); g.gain.value = 0;
      g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(amp, t + attack);
      g.gain.setTargetAtTime(0, t + attack, tau);
      o.connect(g).connect(out); oscs.push(o); return o;
    };
    if (M.timbre === "glass") {
      const car = partial(f, 1, decay, 0.03);
      const modO = ctx.createOscillator(); modO.frequency.value = f * 2;
      const idx = ctx.createGain();   // indeks FM -> deviasi frekuensi (Hz) = indeks * f_mod
      idx.gain.setValueAtTime((1.1 + 0.1) * f * 2, t); idx.gain.setTargetAtTime(0.1 * f * 2, t, decay * 0.15);
      modO.connect(idx).connect(car.frequency); oscs.push(modO);
      partial(f * 4 * 2 ** (4 / 1200), 0.18, decay * 0.2, 0.03);
    } else if (M.timbre === "kalimba") {
      partial(f, 1, decay * 0.55, 0.014);
      partial(f * 6, 0.3, 0.09, 0.014);
      partial(f * 2, 0.15, decay * 0.25, 0.014);
    } else if (M.timbre === "piano") {
      for (let k = 1; k <= 8; k++) {
        const fk = f * k * Math.sqrt(1 + 0.0004 * k * k);
        if (fk > 9000) break;
        const amp = k ** -1.6 * Math.exp(-(k - 1) * 0.25), dk = decay / (1 + 0.45 * (k - 1));
        for (const c of [0, 0.8]) {   // dua senar; decay dua tahap didekati dengan dua parsial
          partial(fk * 2 ** (c / 1200), 0.5 * amp * 0.55, dk * 0.12, 0.01);
          partial(fk * 2 ** (c / 1200), 0.5 * amp * 0.45, dk, 0.01);
        }
      }
    } else {
      partial(f, 1, decay, M.attack);
      partial(midiToHz(midi) * 2, 0.3, decay * 0.4, M.attack);
      partial(midiToHz(midi) * 3, 0.08, decay * 0.2, M.attack);
    }
    for (const o of oscs) { o.start(t); o.stop(t + len); this._track(o); }
  }

  /** setValueCurveAtTime yang aman: bagian yang sudah lewat dipotong. */
  _curve(param, start, dur, fn) {
    const now = this.offline ? 0 : this.ctx.currentTime + 0.02;
    const skip = Math.max(0, now - start);
    if (skip >= dur - 0.05) return;
    param.setValueCurveAtTime(curve(dur - skip, (x) => fn(x + skip)), start + skip, dur - skip);
  }

  /** Ganti kurva yang sedang berjalan mulai sekarang, dengan transisi halus dari nilai saat ini. */
  _recurve(param, start, dur, fn) {
    const t = this.ctx.currentTime + 0.03, rem = start + dur - t - 0.02;
    if (rem < 0.2 || t < start) return false;
    const held = param.value;
    if (param.cancelAndHoldAtTime) param.cancelAndHoldAtTime(t);
    else { param.cancelScheduledValues(t); param.setValueAtTime(held, t); }
    const off = t + 0.01 - start;
    param.setValueCurveAtTime(curve(rem, (x) => {
      const k = Math.min(1, x / GLIDE), target = fn(off + x);
      return held * (1 - k) + target * k;
    }), t + 0.01, rem);
    return true;
  }

  _track(node) { this.nodes.add(node); node.onended = () => this.nodes.delete(node); }

  // ---------- penjadwalan ----------
  /** Jadwalkan semua yang mulai sebelum waktu lagu T (detik). */
  scheduleUntil(T) {
    const P = this.P, end = this.total ?? Infinity, until = Math.min(T, end);
    while (this.droneChunk * (DRONE_CHUNK - DRONE_XF) < until) {
      const i = this.droneChunk++, st = i * (DRONE_CHUNK - DRONE_XF);
      const dur = Math.min(DRONE_CHUNK, end - st);
      if (dur <= 0) break;
      const last = st + dur >= end;
      P.droneNotes.forEach((m, j) => this._padVoice(this.layerIn.drone, P.drone, m, st, dur, rngFor(this.seed, "drone", i, j), {
        attack: i === 0 ? P.drone.attack : DRONE_XF, release: last ? 20 : DRONE_XF, fadeShape: i === 0 && !last ? "sin2" : "sin",
        subLevel: j === 0 ? P.drone.sub : 0, kind: "drone",
      }));
    }
    this.comp.chordsUntil(until + 10);
    while (this.scheduledChord < this.comp.chords.length && this.comp.chords[this.scheduledChord].start < until) {
      const c = this.comp.chords[this.scheduledChord++];
      const dur = Math.min(c.dur, end - c.start);
      if (dur <= 1) continue;
      c.notes.forEach((m) => this._padVoice(this.layerIn.pad, P.pad, m, c.start, dur, rngFor(this.seed, "pad", c.start.toFixed(3), m), {
        attack: P.chordOverlap, release: P.chordOverlap, shapeBright: P.pad.shapeBright,
      }));
    }
    for (const n of this.comp.melodyUntil(until)) if (n.t < end - 8) this._melodyVoice(n.midi, n.t, n.vel, rngFor(this.seed, "mel", n.t.toFixed(3), n.midi));
    while (this.texChunk * TEX_CHUNK < until) {
      const st = this.texChunk++ * TEX_CHUNK, dur = Math.min(TEX_CHUNK, end - st) - 1e-3;
      if (dur <= 0) break;
      this.texCur = { st, dur };
      for (let ch = 0; ch < 2; ch++) {
        this._curve(this.texBand[ch].frequency, this.t0 + st, dur, this._texBandFn(st, ch));
        this._curve(this.texAmp[ch].gain, this.t0 + st, dur, this._texAmpFn(st, ch));
      }
    }
    // buang catatan suara yang sudah selesai
    if (this.voices.length > 64) { const n = this.now(); this.voices = this.voices.filter((v) => v.songT + v.dur > n); }
  }

  _texBandFn(st, ch) {
    const T_ = this.P.texture, ph = this.texPh[ch];
    return (x) => {
      const tt = st + x;
      const m = T_.periods.reduce((a, per, i) => a + 0.5 + 0.5 * Math.sin((2 * Math.PI * tt) / per + ph[i]), 0) / T_.periods.length;
      return T_.bandLo * (T_.bandHi / T_.bandLo) ** m;
    };
  }

  _texAmpFn(st, ch) {
    const T_ = this.P.texture, ph = this.texPh[ch];
    return (x) => {
      const tt = st + x;
      let amp = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin((2 * Math.PI * tt) / (T_.periods[ch % 3] * 1.7) + ph[ph.length - 1]));
      const k = T_.shapeAmount; amp *= (1 - k) + k * (0.25 + 1.5 * this.shape(tt));
      if (this.sections) amp *= this.sections.textureMult(tt);
      const fadeIn = Math.min(1, tt / 20), fadeOut = this.total ? Math.min(1, Math.max(0, (this.total - tt) / 30)) : 1;
      return amp * fadeIn * fadeOut;
    };
  }

  _applyLevels(glide = GLIDE / 3) {
    const P = this.P, t = this.ctx.currentTime;
    const set = (param, v) => { if (glide) param.setTargetAtTime(v, t, glide); else param.value = v; };
    set(this.layerLvl.pad.gain, P.pad.level);
    set(this.layerLvl.drone.gain, P.drone.level);
    set(this.layerLvl.melody.gain, P.melody.level);
    set(this.layerLvl.texture.gain, P.texture.level * 0.35);
    set(this.dryBus.gain, P.fx.dry);
    set(this.wetGain.gain, P.fx.wet);
    set(this.delayFb.gain, P.fx.delayFeedback);
  }

  /**
   * Terapkan parameter baru tanpa memulai ulang lagu. Level & gema langsung; warna suara pad/drone
   * pada nada yang sedang berbunyi; melodi & chord pada nada berikutnya; panjang gema dengan
   * crossfade reverb. Nada dasar/suasana/nomor versi tetap butuh mulai ulang (lihat app.js).
   */
  update(P) {
    const old = this.P;
    this.P = P;
    this._applyLevels();
    const changed = (a, b) => JSON.stringify(a) !== JSON.stringify(b);
    if (changed(old.form, P.form)) { this.shape = makeShape(this.total, this.seed, P.form); this.comp.shape = this.shape; }
    if (old.variation !== P.variation || old.melody.level > 0 !== P.melody.level > 0) {
      this.sections = this._sections(P);
      this.comp.sections = this.sections;
    }
    this.comp.setParams(P);
    // nada yang sedang berbunyi: ganti kurva filternya
    const n = this.now();
    for (const v of this.voices) {
      if (v.songT + v.dur <= n) continue;
      const np = v.kind === "drone" ? P.drone : P.pad;
      if (!changed({ a: np.cutMin, b: np.cutMax, c: np.lfoPeriod, d: np.q, e: P.pad.shapeBright }, { a: v.p.cutMin, b: v.p.cutMax, c: v.p.lfoPeriod, d: v.p.q, e: v.shapeBright })
          && !changed(old.form, P.form)) continue;
      v.p = np; if (v.kind === "pad") v.shapeBright = P.pad.shapeBright;
      v.flts.forEach((f, ch) => { f.Q.setTargetAtTime(np.q ?? 0.7071, this.ctx.currentTime, 0.2); this._recurve(f.frequency, this.t0 + v.songT, v.dur, this._filterFn(v, ch)); });
    }
    // tekstur: potongan yang sedang berjalan
    if (this.texCur && (changed(old.texture, P.texture) || changed(old.form, P.form) || old.variation !== P.variation)) {
      const { st, dur } = this.texCur;
      for (let ch = 0; ch < 2; ch++) {
        this._recurve(this.texBand[ch].frequency, this.t0 + st, dur, this._texBandFn(st, ch));
        this._recurve(this.texAmp[ch].gain, this.t0 + st, dur, this._texAmpFn(st, ch));
      }
    }
    const irKey = (F) => [F.decay, F.early, F.width].join("|");
    if (irKey(old.fx) !== irKey(P.fx)) {
      clearTimeout(this._irTimer);
      this._irTimer = setTimeout(() => this._loadIR(P.fx), 250);
    }
  }

  stop(fade = 1.5) {
    this.stopped = true;
    const g = this.out.gain, t = this.ctx.currentTime;
    g.cancelScheduledValues(t); g.setValueAtTime(g.value, t); g.linearRampToValueAtTime(0, t + fade);
    setTimeout(() => { for (const n of this.nodes) { try { n.stop(); } catch (e) { /* sudah berhenti */ } } this.out.disconnect(); }, fade * 1000 + 100);
  }

  info(songT) {
    const c = this.comp.chordAt(Math.max(0, songT));
    const t = Math.max(0, songT), sec = this.sections?.at(t);
    return { chord: c ? c.label : "", intensity: this.shape(t), form: this.shape.kind,
      section: sec ? { no: this.sections.index(t) + 1, ...sec } : null };
  }
}
