// Mesin audio Web Audio. Bekerja untuk AudioContext (pemutaran langsung, tanpa akhir) maupun
// OfflineAudioContext (ekspor WAV). Struktur sama dengan ambient-gen/pipeline.py:
// lapisan (drone, pad, melodi, tekstur) -> EQ -> efek lapisan -> kering + kirim ke reverb -> master.
import { rngFor, midiToHz, Composer, makeShape } from "./music.js";
import { makeIR, pinkBuffer } from "./dsp.js";

const CURVE_HZ = 8;                 // resolusi kurva otomasi (titik per detik)
const DRONE_CHUNK = 240;            // drone dibuat per potongan (detik), disambung crossfade
const DRONE_XF = 20;
const TEX_CHUNK = 30;
const TIMBRE_GAIN = { soft: 1.0, glass: 0.9, kalimba: 1.08, piano: 2.2 };

function curve(dur, fn) {
  const n = Math.max(2, Math.ceil(dur * CURVE_HZ) + 1), c = new Float32Array(n);
  for (let i = 0; i < n; i++) c[i] = fn((i / (n - 1)) * dur);
  return c;
}

export class Engine {
  /**
   * @param ctx AudioContext atau OfflineAudioContext (48 kHz)
   * @param P parameter teknis (music.technical)
   * @param total durasi lagu (detik) atau null untuk tanpa akhir
   */
  constructor(ctx, P, seed, { total = null, offline = false, start = null } = {}) {
    this.ctx = ctx; this.P = P; this.seed = seed; this.total = total; this.offline = offline;
    this.t0 = start ?? ctx.currentTime + 0.15;
    this.shape = makeShape(total, seed, P.form);
    this.comp = new Composer(P, seed, this.shape);
    this.scheduledChord = 0; this.droneChunk = 0; this.texChunk = 0; this.nodes = new Set();
    this.listeners = [];
    this._build();
    this.applyLevels();
  }

  now() { return this.ctx.currentTime - this.t0; }

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
    // (seperti Chorus pedalboard), jadi kanal kiri/kanan sedikit berbeda -> lebih lebar
    const ctx = this.ctx, out = ctx.createChannelMerger(2), dry = ctx.createGain(), sum = ctx.createGain();
    const split = ctx.createChannelSplitter(2), lfo = ctx.createOscillator();
    lfo.frequency.value = rate; lfo.start(this.t0); this.nodes.add(lfo);
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
    // titik ukur loudness (sebelum limiter) untuk penyesuaian volume otomatis
    this.meterTap = this.masterGain;

    const dryBus = ctx.createGain(); dryBus.gain.value = F.dry; dryBus.connect(this.master);
    const revIn = ctx.createGain();
    const conv = ctx.createConvolver(); conv.normalize = false;
    conv.buffer = makeIR(ctx, rngFor(this.seed, "ir"), { decay: F.decay, predelay: F.predelay, hp: F.reverbHp, early: F.early, width: F.width });
    revIn.connect(conv);
    let wet = conv;
    if (F.motion > 0) {   // modulasi pelan pada ekor reverb
      const m = this._modDelay(conv, { centre: 0.014, depth: 0.003, rate: 0.07, mix: 0.5 * F.motion });
      wet = m;
    }
    const wetGain = ctx.createGain(); wetGain.gain.value = F.wet;
    this._eq(wet, P.eq.reverb).connect(wetGain).connect(this.master);

    this.layerIn = {};
    for (const k of ["drone", "pad", "melody", "texture"]) {
      const inp = ctx.createGain();
      let node = this._eq(inp, P.eq[k]);
      if (k === "pad") node = this._modDelay(node, { centre: 0.009, depth: 0.0015, rate: 0.12, mix: 0.35 });
      if (k === "melody") {
        const out = ctx.createGain(), dry = ctx.createGain(), wetG = ctx.createGain(), d = ctx.createDelay(5), fb = ctx.createGain();
        d.delayTime.value = F.delaySeconds; fb.gain.value = F.delayFeedback;
        dry.gain.value = 1 - F.delayMix; wetG.gain.value = F.delayMix;
        node.connect(dry).connect(out); node.connect(d); d.connect(fb).connect(d); d.connect(wetG).connect(out);
        node = out;
      }
      node.connect(dryBus);
      const send = ctx.createGain(); send.gain.value = F.send[k]; node.connect(send).connect(revIn);
      this.layerIn[k] = inp;
    }
    // tekstur: pink noise loop -> band-pass bergerak (per kanal) -> amplitudo
    if (P.texture.level > 0) {
      const src = ctx.createBufferSource(); src.buffer = pinkBuffer(ctx, rngFor(this.seed, "pink"), 23); src.loop = true;
      const split = ctx.createChannelSplitter(2), merge = ctx.createChannelMerger(2);
      src.connect(split);
      this.texBand = []; this.texAmp = [];
      for (let ch = 0; ch < 2; ch++) {
        const bp = ctx.createBiquadFilter(); bp.type = "bandpass"; bp.Q.value = 1.2;
        const g = ctx.createGain(); g.gain.value = 0;
        split.connect(bp, ch); bp.connect(g).connect(merge, 0, ch);
        this.texBand.push(bp); this.texAmp.push(g);
      }
      const lvl = ctx.createGain(); lvl.gain.value = P.texture.level * 0.35;
      merge.connect(lvl).connect(this.layerIn.texture);
      src.start(this.t0);
      this.nodes.add(src);
      const r = rngFor(this.seed, "texlfo");
      this.texPh = [0, 1].map(() => P.texture.periods.map(() => r.uniform(0, 6.28)).concat([r.uniform(0, 6.28)]));
    }
  }

  // ---------- suara ----------
  _padVoice(dest, p, midi, songT, dur, rng, { attack, release, subLevel = 0, shapeBright = 0, fadeShape = "sin2" }) {
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
      o.detune.setValueCurveAtTime(curve(dur, (x) => cents + (drift / 3) * per.reduce((a, P_, j) => a + Math.sin((2 * Math.PI * x) / P_ + ph[j]), 0)), t, dur);
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
    const lfoPh = rng.uniform(0, 6.28);
    const sp = ctx.createChannelSplitter(2), mg = ctx.createChannelMerger(2);
    bus.connect(sp);
    for (let ch = 0; ch < 2; ch++) {
      const flt = ctx.createBiquadFilter(); flt.type = "lowpass"; flt.Q.value = p.q ?? 0.7071;
      flt.frequency.setValueCurveAtTime(curve(dur, (x) => {
        const m = 0.5 + 0.5 * Math.sin((2 * Math.PI * x) / p.lfoPeriod + lfoPh + ch * 0.4);
        const bright = shapeBright ? 2 ** (shapeBright * (this.shape(songT + x) - 0.5)) : 1;
        return Math.min(ctx.sampleRate * 0.45, p.cutMin * (p.cutMax / p.cutMin) ** m * bright);
      }), t, dur);
      sp.connect(flt, ch); flt.connect(mg, 0, ch);
    }
    const env = ctx.createGain(); env.gain.value = 0;
    const a = Math.min(attack, dur / 2), r = Math.min(release, dur - a);
    const fade = fadeShape === "sin" ? (u) => Math.sin((u * Math.PI) / 2) : (u) => Math.sin((u * Math.PI) / 2) ** 2;
    env.gain.setValueCurveAtTime(curve(dur, (x) => (x < a ? fade(x / a) : x > dur - r ? fade(Math.max(0, (dur - x) / r)) : 1)), t, dur);
    mg.connect(env).connect(dest);
    for (const o of oscs) { o.start(t); o.stop(t + dur + 0.05); this._track(o); }
  }

  _melodyVoice(midi, songT, vel, rng) {
    const ctx = this.ctx, M = this.P.melody, t = this.t0 + songT, decay = M.decay;
    const f = midiToHz(midi) * 2 ** (rng.uniform(-3, 3) / 1200);
    const pan = ctx.createStereoPanner(); pan.pan.value = rng.uniform(0.2, 0.8) * 2 - 1;
    const out = ctx.createGain(); out.gain.value = M.level * vel * (TIMBRE_GAIN[M.timbre] ?? 1);
    out.connect(pan).connect(this.layerIn.melody);
    const len = Math.min(decay * 2.5, 40), oscs = [];
    const partial = (freq, amp, tau, attack, phase = 0) => {
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

  _track(node) { this.nodes.add(node); node.onended = () => this.nodes.delete(node); }

  // ---------- penjadwalan ----------
  /** Jadwalkan semua yang mulai sebelum waktu lagu T (detik). */
  scheduleUntil(T) {
    const P = this.P, end = this.total ?? Infinity, until = Math.min(T, end);
    // drone: potongan bersambung dengan crossfade equal-power
    while (this.droneChunk * (DRONE_CHUNK - DRONE_XF) < until && P.drone.level > 0) {
      const i = this.droneChunk++, st = i * (DRONE_CHUNK - DRONE_XF);
      const dur = Math.min(DRONE_CHUNK, end - st);
      if (dur <= 0) break;
      const last = st + dur >= end;
      P.droneNotes.forEach((m, j) => this._padVoice(this.layerIn.drone, P.drone, m, st, dur, rngFor(this.seed, "drone", i, j), {
        attack: i === 0 ? P.drone.attack : DRONE_XF, release: last ? 20 : DRONE_XF, fadeShape: i === 0 && !last ? "sin2" : "sin",
        subLevel: j === 0 ? P.drone.sub : 0,
      }));
    }
    // chord pad
    this.comp.chordsUntil(until + 10);
    while (this.scheduledChord < this.comp.chords.length && this.comp.chords[this.scheduledChord].start < until) {
      const c = this.comp.chords[this.scheduledChord++];
      const dur = Math.min(c.dur, end - c.start);
      if (dur <= 1 || P.pad.level <= 0) continue;
      c.notes.forEach((m) => this._padVoice(this.layerIn.pad, { ...P.pad }, m, c.start, dur, rngFor(this.seed, "pad", c.start.toFixed(3), m), {
        attack: P.chordOverlap, release: P.chordOverlap, shapeBright: P.pad.shapeBright,
      }));
    }
    // melodi
    for (const n of this.comp.melodyUntil(until)) if (n.t < end - 8) this._melodyVoice(n.midi, n.t, n.vel, rngFor(this.seed, "mel", n.t.toFixed(3), n.midi));
    // tekstur: kurva per potongan
    if (this.texBand) {
      const T_ = P.texture;
      while (this.texChunk * TEX_CHUNK < until) {
        const st = this.texChunk++ * TEX_CHUNK, dur = Math.min(TEX_CHUNK, end - st) - 1e-3;
        if (dur <= 0) break;
        for (let ch = 0; ch < 2; ch++) {
          const ph = this.texPh[ch];
          this.texBand[ch].frequency.setValueCurveAtTime(curve(dur, (x) => {
            const tt = st + x;
            const m = T_.periods.reduce((a, per, i) => a + 0.5 + 0.5 * Math.sin((2 * Math.PI * tt) / per + ph[i]), 0) / T_.periods.length;
            return T_.bandLo * (T_.bandHi / T_.bandLo) ** m;
          }), this.t0 + st, dur);
          this.texAmp[ch].gain.setValueCurveAtTime(curve(dur, (x) => {
            const tt = st + x;
            let amp = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin((2 * Math.PI * tt) / (T_.periods[ch % 3] * 1.7) + ph[ph.length - 1]));
            const k = T_.shapeAmount; amp *= (1 - k) + k * (0.25 + 1.5 * this.shape(tt));
            const fadeIn = Math.min(1, tt / 20), fadeOut = this.total ? Math.min(1, Math.max(0, (this.total - tt) / 30)) : 1;
            return amp * fadeIn * fadeOut;
          }), this.t0 + st, dur);
        }
      }
    }
  }

  applyLevels() {
    // level lapisan pad & drone diterapkan di input lapisan (pad_voice sendiri tanpa level)
    this.layerIn.pad.gain.value = this.P.pad.level;
    this.layerIn.drone.gain.value = this.P.drone.level;
  }

  stop(fade = 1.5) {
    const g = this.out.gain, t = this.ctx.currentTime;
    g.cancelScheduledValues(t); g.setValueAtTime(g.value, t); g.linearRampToValueAtTime(0, t + fade);
    setTimeout(() => { for (const n of this.nodes) { try { n.stop(); } catch (e) { /* sudah berhenti */ } } this.out.disconnect(); }, fade * 1000 + 100);
  }

  info(songT) {
    const c = this.comp.chordAt(Math.max(0, songT));
    return { chord: c ? c.label : "", intensity: this.shape(Math.max(0, songT)) };
  }
}
