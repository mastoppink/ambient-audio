// Mesin audio Web Audio. Bekerja untuk AudioContext (pemutaran langsung, tanpa akhir) maupun
// OfflineAudioContext (ekspor WAV). Struktur sama dengan ambient-gen/pipeline.py:
// lapisan (drone, pad, melodi, tekstur) -> EQ -> efek lapisan -> kering + kirim ke reverb -> master.
//
// Performa: semua suara dihitung oleh mesin audio bawaan browser (native). Thread halaman hanya
// menjadwalkan. Reverb dibuat async lewat OfflineAudioContext dan disimpan di cache; perubahan slider
// diterapkan langsung lewat update() tanpa membangun ulang mesin.
import { rngFor, midiToHz, Composer, makeShape, Sections } from "./music.js";
import { makeIRAsync, pinkBufferCached } from "./dsp.js";
import { ensureWorklets, fdnGainAsync } from "./worklets.js";
import { pianoBuffer } from "./piano.js";

const CURVE_HZ = 8;                 // resolusi kurva otomasi (titik per detik)
const DRONE_CHUNK = 240;            // drone dibuat per potongan (detik), disambung crossfade
const DRONE_XF = 20;
const TEX_CHUNK = 30;
const TIMBRE_GAIN = { soft: 1.0, glass: 0.9, kalimba: 1.08, piano: 5.56 };
const GLIDE = 0.6;                  // detik: transisi saat parameter diubah langsung

function curve(dur, fn) {
  const n = Math.max(2, Math.ceil(dur * CURVE_HZ) + 1), c = new Float32Array(n);
  for (let i = 0; i < n; i++) c[i] = fn((i / (n - 1)) * dur);
  return c;
}

export class Engine {
  /** Buat mesin dan tunggu reverb siap (tidak memblokir halaman). */
  static async create(ctx, P, seed, opts = {}) {
    // AudioWorklet untuk reverb hall & kehangatan; kalau tidak didukung -> reverb lama, tanpa kehangatan
    let worklets = false;
    try { await ensureWorklets(ctx); worklets = true; } catch (err) { console.warn("Spacenight: tanpa AudioWorklet:", err.message); }
    const e = new Engine(ctx, P, seed, { ...opts, worklets });
    await e._loadReverb(P.fx, true);
    return e;
  }

  /**
   * @param ctx AudioContext atau OfflineAudioContext (48 kHz)
   * @param P parameter teknis (music.technical)
   * @param total durasi lagu (detik) atau null untuk tanpa akhir
   */
  constructor(ctx, P, seed, { total = null, offline = false, start = null, destination = null, worklets = false } = {}) {
    this.ctx = ctx; this.P = P; this.seed = seed; this.total = total; this.offline = offline;
    this.worklets = worklets;
    this.pending = [];             // nada piano yang sedang dirender (ekspor menunggu semuanya)
    this.cloudBucket = 0;
    this.destination = destination ?? ctx.destination;
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

  /**
   * Mulai pemutaran (dipanggil setelah create selesai).
   * warm > 0: lagu dimulai seolah sudah berjalan `warm` detik, jadi drone/pad/angin langsung penuh
   * tanpa intro. Dipakai saat ganti preset sambil memutar, supaya tidak ada lubang hening.
   */
  begin(warm = 0) {
    const now = this.ctx.currentTime + 0.1;
    if (!this.offline && this.startAt == null) this.t0 = now - warm;
    this.warm = warm;
    for (const n of this._startLater) n.start(Math.max(this.t0, this.offline ? 0 : now));
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
    let pre = this.master;
    if (this.worklets) {   // kehangatan pita (saturasi, wow/flutter, desis) + warna nada pita
      const W = P.warmth, wr = rngFor(this.seed, "warmth");
      this.warmNode = new AudioWorkletNode(ctx, "warmth", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2],
        channelCount: 2, channelCountMode: "explicit", processorOptions: { sr: ctx.sampleRate, amount: W.amount, tape: W.tape, noise: W.noise,
          wowF: wr.uniform(0.4, 0.7), flutF: wr.uniform(5.5, 7.0), wowPh: wr.uniform(0, 6.28), flutPh: wr.uniform(0, 6.28),
          driftF: [wr.uniform(0.05, 0.12), wr.uniform(0.05, 0.12)], driftPh: [wr.uniform(0, 6.28), wr.uniform(0, 6.28)],
          noiseSeed: Math.floor(wr() * 2 ** 31) } });
      this.warmTone = [["lowshelf", 90], ["highshelf", 9000], ["lowpass", 18500]].map(([type, f]) => {
        const b = ctx.createBiquadFilter(); b.type = type; b.frequency.value = f; b.Q.value = 0.7; return b; });
      this._setWarmTone(W);
      pre.connect(this.warmNode); pre = this.warmNode;
      for (const b of this.warmTone) { pre.connect(b); pre = b; }
    }
    pre.connect(hp).connect(this.masterGain);
    if (this.offline) this.masterGain.connect(this.out);
    else {   // limiter sederhana untuk pemutaran langsung; ekspor memakai limiter lookahead di dsp.js
      const lim = ctx.createDynamicsCompressor();
      lim.threshold.value = -2; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = 0.002; lim.release.value = 0.2;
      this.masterGain.connect(lim).connect(this.out);
    }
    this.out.connect(this.destination);
    this.meterTap = this.masterGain;      // titik ukur loudness (sebelum limiter)

    this.dryBus = ctx.createGain(); this.dryBus.gain.value = F.dry; this.dryBus.connect(this.master);
    this.revIn = ctx.createGain();
    this.revOut = ctx.createGain();       // keluaran semua konvolver (bisa lebih dari satu saat bertukar IR)
    let wet = this.revOut;
    this.hall = F.reverbType === "hall" && this.worklets;
    // reverb lama: ekor statis -> beri chorus pelan. Hall bergerak dari dalam, tidak perlu.
    if (F.motion > 0 && !this.hall) wet = this._modDelay(this.revOut, { centre: 0.014, depth: 0.003, rate: 0.07, mix: 0.5 * F.motion });
    this.wetGain = ctx.createGain(); this.wetGain.gain.value = F.wet;
    this._eq(wet, P.eq.reverb).connect(this.wetGain).connect(this.master);

    this.layerIn = {}; this.layerLvl = {};
    for (const k of ["drone", "pad", "melody", "texture", "cloud"]) {
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
      const send = ctx.createGain(); send.gain.value = F.send[k] ?? 0.5; node.connect(send).connect(this.revIn);
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

  _setWarmTone(W) {
    const [ls, hs, lp] = this.warmTone, t = this.ctx.currentTime;
    ls.gain.setTargetAtTime(1.2 * W.amount, t, 0.1);
    hs.gain.setTargetAtTime(-2.5 * W.amount, t, 0.1);
    lp.frequency.setTargetAtTime(18500 - 5000 * W.amount, t, 0.1);
  }

  _erBuffer(early) {
    // pantulan awal 90 ms (seperti fx.make_ir / FDNReverb): 14 pantulan, lowpass 5 kHz, energi = early^2
    const sr = this.ctx.sampleRate, n = Math.floor(0.09 * sr), r = rngFor(this.seed, "er");
    const buf = new AudioBuffer({ numberOfChannels: 2, length: n, sampleRate: sr });
    const L = buf.getChannelData(0), R = buf.getChannelData(1);
    for (let i = 0; i < 14; i++) {
      const d = r.uniform(0.008, 0.08), g = 0.9 * (1 - d / 0.09) * r.uniform(0.5, 1), pan = r.uniform(0.1, 0.9), j = Math.floor(d * sr);
      L[j] += g * Math.cos((pan * Math.PI) / 2); R[j] += g * Math.sin((pan * Math.PI) / 2);
    }
    const a = 1 - Math.exp((-2 * Math.PI * 5000) / sr);
    let e = 0;
    for (const x of [L, R]) { let y = 0; for (let i = 0; i < n; i++) { y += a * (x[i] - y); x[i] = y; e += y * y; } }
    const g = early / Math.sqrt(e || 1);
    for (const x of [L, R]) for (let i = 0; i < n; i++) x[i] *= g;
    return buf;
  }

  /** Bangun reverb (hall FDN atau konvolusi lama) dan tukar dengan crossfade kalau sudah ada. */
  async _loadReverb(F, first = false) {
    const ctx = this.ctx, g = ctx.createGain(), chain = { g, fdn: null, nodes: [g] };
    if (this.hall) {
      const r = rngFor(this.seed, "fdn");
      const o = { sr: ctx.sampleRate, decay: F.decay, size: F.size, modDepthMs: 0.15 + 0.9 * F.motion, hfRatio: 0.4, width: F.width,
        lfoF: Array.from({ length: 8 }, () => r.uniform(0.07, 0.5)), lfoPh: Array.from({ length: 8 }, () => r.uniform(0, 6.28)) };
      const norm = await fdnGainAsync(o);
      if (this.stopped) return;
      const pre = ctx.createDelay(1); pre.delayTime.value = F.predelay;
      const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = F.reverbHp; hp.Q.value = 0.6;
      const fdn = new AudioWorkletNode(ctx, "fdn-reverb", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2],
        channelCount: 2, channelCountMode: "explicit", processorOptions: o });
      const ng = ctx.createGain(); ng.gain.value = norm;
      const er = ctx.createConvolver(); er.normalize = false; er.buffer = this._erBuffer(F.early);
      this.revIn.connect(pre).connect(hp);
      hp.connect(fdn).connect(ng).connect(g);
      hp.connect(er).connect(g);
      chain.fdn = fdn; chain.nodes.push(pre, hp, fdn, ng, er);
    } else {
      const key = { decay: F.decay, predelay: F.predelay, hp: F.reverbHp, early: F.early, width: F.width };
      const buf = await makeIRAsync(ctx.sampleRate, this.seed, key);
      if (this.stopped) return;
      const conv = ctx.createConvolver(); conv.normalize = false; conv.buffer = buf;
      this.revIn.connect(conv).connect(g);
      chain.nodes.push(conv);
    }
    g.connect(this.revOut);
    if (first || this.offline) { g.gain.value = 1; this.rev = chain; return; }
    // tukar reverb dengan crossfade, supaya tidak ada klik
    const t = ctx.currentTime, old = this.rev;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(1, t + 1.5);
    old.g.gain.setValueAtTime(old.g.gain.value, t); old.g.gain.linearRampToValueAtTime(0, t + 1.5);
    setTimeout(() => { old.fdn?.port.postMessage("stop"); for (const n of old.nodes) n.disconnect(); }, 2000);
    this.rev = chain;
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

  _padVoice(dest, p, midi, songT, dur, rng, { attack, release, subLevel = 0, shapeBright = 0, fadeIn = "sin2", fadeOut = "sin2", kind = "pad" }) {
    const ctx = this.ctx, t = this.t0 + songT, f0 = midiToHz(midi), k = p.nOsc;
    if (!this.offline && t + dur <= ctx.currentTime + 0.05) return;   // sudah selesai (mulai "panas")
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
    // "sin2": muncul/hilang pelan (awal & akhir lagu); "sin": equal-power untuk sambungan antar potongan drone
    const shapeOf = (s) => (s === "sin" ? (u) => Math.sin((u * Math.PI) / 2) : (u) => Math.sin((u * Math.PI) / 2) ** 2);
    const fi = shapeOf(fadeIn), fo = shapeOf(fadeOut);
    this._curve(env.gain, t, dur, (x) => (x < a ? fi(x / a) : x > dur - r ? fo(Math.max(0, (dur - x) / r)) : 1));
    mg.connect(env).connect(dest);
    // waktu bisa negatif saat lagu dimulai "panas" di awal pemutaran: mulai seketika (0), jangan negatif
    for (const o of oscs) { o.start(Math.max(0, t)); o.stop(Math.max(0.01, t + dur + 0.05)); this._track(o); }
    if (!this.offline) this.voices.push(v);
  }

  _melodyVoice(midi, songT, vel, rng) {
    const ctx = this.ctx, M = this.P.melody, t = this.t0 + songT, decay = M.decay;
    const f = midiToHz(midi) * 2 ** (rng.uniform(-3, 3) / 1200);
    const pan = ctx.createStereoPanner(); pan.pan.value = rng.uniform(0.2, 0.8) * 2 - 1;
    const out = ctx.createGain(); out.gain.value = vel * (TIMBRE_GAIN[M.timbre] ?? 1);   // level di lapisan
    out.connect(pan).connect(this.layerIn.melody);
    const len = Math.min(decay * 2.5, 40), oscs = [];
    if (M.timbre === "piano") { this._pianoVoice(midi, t, len, vel, out); return; }
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
    for (const o of oscs) { o.start(Math.max(0, t)); o.stop(Math.max(0.01, t + len)); this._track(o); }
  }

  /** Piano model fisik: buffer dirender di latar (piano.js), lalu diputar pada waktunya. */
  _pianoVoice(midi, t, len, vel, out) {
    out.gain.value = 0;
    const p = pianoBuffer(this.ctx.sampleRate, midi, vel, this.P.melody.decay, len).then((buf) => {
      if (this.stopped) return;
      const ctx = this.ctx, now = this.offline ? 0 : ctx.currentTime + 0.02;
      if (t + len <= now + 0.1) return;
      const src = ctx.createBufferSource(); src.buffer = buf;
      const lvl = vel * TIMBRE_GAIN.piano, g = out.gain, start = Math.max(t, now);
      g.setValueAtTime(0, start); g.linearRampToValueAtTime(lvl, start + 0.003);
      g.setValueAtTime(lvl, Math.max(start + 0.01, t + len - 0.5)); g.linearRampToValueAtTime(0, t + len);
      src.connect(out);
      src.start(Math.max(0, start), Math.max(0, start - t)); src.stop(Math.max(0.01, t + len));
      this._track(src);
    });
    if (this.offline) this.pending.push(p);
  }

  /** Lapisan awan: butir pendek dari nada chord (lihat synth.cloud_segment). Ember 1 detik per sumber acak. */
  _scheduleCloud(until) {
    const C = this.P.cloud, ctx = this.ctx;
    if (!this.cloudWave) {
      const re = new Float32Array(4), im = new Float32Array([0, 1, 0.25, 0.08]);
      this.cloudWave = ctx.createPeriodicWave(re, im, { disableNormalization: true });
    }
    const late = this.offline ? -Infinity : ctx.currentTime + 0.05, maxLen = C.length * 2;
    while (this.cloudBucket < until) {
      const b = this.cloudBucket++;
      if (C.level <= 0) continue;
      const r = rngFor(this.seed, "cloud", b);
      // awan muncul perlahan 20 detik pertama, bersama pad (sama dengan synth.CLOUD_INTRO)
      const intro = (t) => Math.sin((Math.min(1, Math.max(0, t / 20)) * Math.PI) / 2) ** 2;
      let dens = C.density * (0.35 + 0.9 * this.shape(b + 0.5)) * intro(b + 0.5);
      if (this.sections) dens *= 0.6 + 0.4 * Math.min(1.5, Math.max(0, this.sections.at(b).melody));
      let k = 0, p = Math.exp(-dens), prod = r();       // Poisson (Knuth)
      while (prod > p) { k++; prod *= r(); }
      for (let i = 0; i < k; i++) {
        const t = b + r();
        let len = 0; for (let j = 0; j < 4; j++) len -= Math.log(1 - r()) * (C.length / 4);   // gamma(4, L/4)
        len = Math.min(maxLen, Math.max(0.08, len));
        const notes = this.comp.chordAt(t).notes, oct = C.octaves[Math.floor(r() * C.octaves.length)];
        const midi = notes[Math.floor(r() * notes.length)] + 12 * oct;
        const f = midiToHz(midi) * 2 ** (r.uniform(-8, 8) / 1200), amp = r.uniform(0.35, 1) * intro(t), pan = r.uniform(0.1, 0.9);
        const at = this.t0 + t;
        if (f > 9000 || at < late) continue;
        const o = ctx.createOscillator(); o.setPeriodicWave(this.cloudWave); o.frequency.value = f;
        const g = ctx.createGain(); g.gain.value = 0;
        this._curve(g.gain, at, len, (x) => amp * Math.sin((Math.PI * x) / len) ** 2);
        const pn = ctx.createStereoPanner(); pn.pan.value = pan * 2 - 1;
        o.connect(g).connect(pn).connect(this.layerIn.cloud);
        o.start(at); o.stop(at + len + 0.02); this._track(o);
      }
    }
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
        attack: i === 0 ? P.drone.attack : DRONE_XF, release: last ? 20 : DRONE_XF,
        fadeIn: i === 0 ? "sin2" : "sin", fadeOut: last ? "sin2" : "sin",
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
    const late = this.offline ? -Infinity : this.ctx.currentTime + 0.05;
    for (const n of this.comp.melodyUntil(until)) {
      // nada yang waktunya sudah lewat (mulai "panas") dilewati, jangan dibunyikan bersamaan
      if (n.t < end - 8 && this.t0 + n.t >= late) this._melodyVoice(n.midi, n.t, n.vel, rngFor(this.seed, "mel", n.t.toFixed(3), n.midi));
    }
    this._scheduleCloud(until);
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
    set(this.layerLvl.cloud.gain, P.cloud.level);
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
    const irKey = (F) => [F.decay, F.early, F.width, F.size, F.motion].join("|");
    if (irKey(old.fx) !== irKey(P.fx)) {
      clearTimeout(this._irTimer);
      this._irTimer = setTimeout(() => this._loadReverb(P.fx), 250);
    }
    if (this.warmNode && changed(old.warmth, P.warmth)) {
      this.warmNode.port.postMessage({ type: "set", params: { ...P.warmth } });
      this._setWarmTone(P.warmth);
    }
  }

  /** Naik dari 0 dengan kurva equal-power (pasangan dari stop dengan crossfade). */
  fadeIn(dur) {
    const t = this.ctx.currentTime + 0.02;
    this.out.gain.setValueCurveAtTime(Float32Array.from({ length: 64 }, (_, i) => Math.sin(((i / 63) * Math.PI) / 2)), t, dur);
  }

  stop(fade = 1.5) {
    this.stopped = true;
    const g = this.out.gain, t = this.ctx.currentTime + 0.02, v = g.value;
    if (g.cancelAndHoldAtTime) g.cancelAndHoldAtTime(t); else g.cancelScheduledValues(t);
    // equal-power: jumlah energi lama + baru tetap rata selama crossfade
    g.setValueCurveAtTime(Float32Array.from({ length: 64 }, (_, i) => v * Math.cos(((i / 63) * Math.PI) / 2)), t + 0.01, fade);
    setTimeout(() => {
      for (const n of this.nodes) { try { n.stop(); } catch (e) { /* sudah berhenti */ } }
      this.out.disconnect();
      this.warmNode?.port.postMessage("stop"); this.rev?.fdn?.port.postMessage("stop");   // akhiri prosesor worklet
    }, fade * 1000 + 100);
  }

  info(songT) {
    const c = this.comp.chordAt(Math.max(0, songT));
    const t = Math.max(0, songT), sec = this.sections?.at(t);
    return { chord: c ? c.label : "", intensity: this.shape(t), form: this.shape.kind,
      section: sec ? { no: this.sections.index(t) + 1, ...sec } : null };
  }
}
