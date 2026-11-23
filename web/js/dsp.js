import { rngFor } from "./music.js";

// Utilitas DSP di JavaScript murni: biquad, IR reverb sintetis, pink noise, loudness BS.1770,
// limiter, dan penulis WAV. Port dari ambient-gen/fx.py, loudness.py, synth.py.

export function rbj(kind, f, sr, gainDb = 0, q = 0.7071) {
  const A = 10 ** (gainDb / 40), w0 = (2 * Math.PI * Math.min(f, sr * 0.45)) / sr;
  const cw = Math.cos(w0), sw = Math.sin(w0), al = sw / (2 * q);
  let b, a;
  if (kind === "lp") { b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]; a = [1 + al, -2 * cw, 1 - al]; }
  else if (kind === "hp") { b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + al, -2 * cw, 1 - al]; }
  else if (kind === "bp") { b = [al, 0, -al]; a = [1 + al, -2 * cw, 1 - al]; }
  else throw new Error(kind);
  return { b: b.map((x) => x / a[0]), a: [1, a[1] / a[0], a[2] / a[0]] };
}

export function biquadInPlace(x, c) {
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  const [b0, b1, b2] = c.b, [, a1, a2] = c.a;
  for (let i = 0; i < x.length; i++) {
    const y = b0 * x[i] + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1; x1 = x[i]; y2 = y1; y1 = y; x[i] = y;
  }
  return x;
}

/**
 * IR reverb sintetis, dirender oleh mesin audio bawaan browser (OfflineAudioContext) supaya tidak
 * memblokir halaman. Hasil disimpan di cache: IR dengan parameter sama tidak dibuat dua kali.
 * Hasilnya setara makeIR() di bawah (pantulan awal + ekor dengan decay berbeda per pita).
 */
const IR_CACHE = new Map();
export function makeIRAsync(sr, seed, { decay, predelay, hp, early = 0.5, width = 1.0 }) {
  const key = [sr, seed, decay, predelay, hp, early, width].join("|");
  if (!IR_CACHE.has(key)) IR_CACHE.set(key, renderIR(sr, seed, { decay, predelay, hp, early, width }));
  if (IR_CACHE.size > 12) IR_CACHE.delete(IR_CACHE.keys().next().value);
  return IR_CACHE.get(key);
}

async function renderIR(sr, seed, { decay, predelay, hp, early, width }) {
  const rng = rngFor(seed, "ir");
  const n = Math.floor((decay * 1.25 + predelay) * sr), pre = Math.floor(predelay * sr);
  // 4 kanal: 0-1 ekor, 2-3 pantulan awal (dinormalkan terpisah di bawah)
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const oc = new OAC(4, n, sr);
  const noise = oc.createBuffer(2, n, sr);
  for (let ch = 0; ch < 2; ch++) { const x = noise.getChannelData(ch); for (let i = 0; i < n; i++) x[i] = (rng() + rng() + rng() + rng() - 2) * 1.732; }
  const merge = oc.createChannelMerger(4); merge.connect(oc.destination);
  const tailSum = oc.createGain(), tailSplit = oc.createChannelSplitter(2);
  // muncul bertahap 120 ms
  tailSum.gain.setValueCurveAtTime(Float32Array.from({ length: 64 }, (_, i) => Math.sin(((i / 63) * Math.PI) / 2) ** 2), 0, 0.12);
  const bands = [["lowpass", 300, 0.9, 2], ["bandpass", Math.sqrt(300 * 2000), 1.0, 1], ["bandpass", Math.sqrt(2000 * 6000), 0.55, 1], ["highpass", 6000, 0.28, 2]];
  for (const [type, f, k, order] of bands) {
    const src = oc.createBufferSource(); src.buffer = noise;
    let node = src;
    for (let o = 0; o < order; o++) {
      const b = oc.createBiquadFilter(); b.type = type; b.frequency.value = f;
      if (type === "bandpass") b.Q.value = f < 1000 ? f / (2000 - 300) : f / (6000 - 2000);
      node.connect(b); node = b;
    }
    const env = oc.createGain(), tau = decay * k;   // -60 dB pada t = tau
    env.gain.setValueAtTime(1, 0); env.gain.exponentialRampToValueAtTime(1e-3, tau);
    env.gain.setTargetAtTime(0, tau, tau / 6.9);
    node.connect(env).connect(tailSum);
    src.start(0);
  }
  tailSum.connect(tailSplit); tailSplit.connect(merge, 0, 0); tailSplit.connect(merge, 1, 1);
  // pantulan awal
  const erLen = Math.floor(0.09 * sr), er = oc.createBuffer(2, erLen, sr);
  for (let i = 0; i < 14; i++) {
    const d = 0.008 + rng() * 0.072, g = 0.9 * (1 - d / 0.09) * (0.5 + 0.5 * rng()), pan = 0.1 + 0.8 * rng();
    const j = Math.floor(d * sr);
    er.getChannelData(0)[j] += g * Math.cos((pan * Math.PI) / 2); er.getChannelData(1)[j] += g * Math.sin((pan * Math.PI) / 2);
  }
  const erSrc = oc.createBufferSource(); erSrc.buffer = er;
  const erLp = oc.createBiquadFilter(); erLp.type = "lowpass"; erLp.frequency.value = 5000; erLp.Q.value = 0.5;
  const erSplit = oc.createChannelSplitter(2);
  erSrc.connect(erLp).connect(erSplit); erSplit.connect(merge, 0, 2); erSplit.connect(merge, 1, 3); erSrc.start(0);
  const r = await oc.startRendering();

  const out = new AudioBuffer({ numberOfChannels: 2, length: n + pre, sampleRate: sr });
  const tail = [r.getChannelData(0), r.getChannelData(1)], erc = [r.getChannelData(2), r.getChannelData(3)];
  const energy = (xs) => xs.reduce((a, x) => { let e = 0; for (let i = 0; i < x.length; i++) e += x[i] * x[i]; return a + e; }, 0);
  const eTail = [energy([tail[0]]), energy([tail[1]])], eEr = Math.sqrt(energy(erc)) || 1;
  const chans = [0, 1].map((ch) => {
    const x = new Float32Array(n), gt = 1 / Math.sqrt(eTail[ch] || 1), ge = early / eEr;
    for (let i = 0; i < n; i++) x[i] = tail[ch][i] * gt + erc[ch][i] * ge;
    return x;
  });
  if (width < 1) for (let i = 0; i < n; i++) { const m = (chans[0][i] + chans[1][i]) / 2; chans[0][i] = m + (chans[0][i] - m) * width; chans[1][i] = m + (chans[1][i] - m) * width; }
  for (let ch = 0; ch < 2; ch++) {
    const x = chans[ch]; biquadInPlace(x, rbj("hp", hp, sr));
    let e = 0; for (let i = 0; i < n; i++) e += x[i] * x[i];
    const g = 1 / Math.sqrt(e || 1), o = out.getChannelData(ch);
    for (let i = 0; i < n; i++) o[pre + i] = x[i] * g;
  }
  return out;
}

const PINK_CACHE = new Map();
/** Pink noise yang sama untuk semua mesin (dibuat sekali per sample rate). */
export function pinkBufferCached(ctx) {
  const sr = ctx.sampleRate;
  if (!PINK_CACHE.has(sr)) {
    PINK_CACHE.set(sr, pinkFast(sr, rngFor(12345, "pink"), 23));
  }
  return PINK_CACHE.get(sr);
}

function pinkFast(sr, rng, seconds) {
  const n = Math.floor(seconds * sr), buf = new AudioBuffer({ numberOfChannels: 2, length: n, sampleRate: sr });
  const b0 = 0.049922035, b1 = -0.095993537, b2 = 0.050612699, b3 = -0.004408786, a1 = -2.494956002, a2 = 2.017265875, a3 = -0.5221894;
  for (let ch = 0; ch < 2; ch++) {
    const out = buf.getChannelData(ch);
    let x1 = 0, x2 = 0, x3 = 0, y1 = 0, y2 = 0, y3 = 0;
    for (let i = -sr; i < n; i++) {
      const w = (rng() + rng() + rng() + rng() - 2) * 1.732;
      const y = b0 * w + b1 * x1 + b2 * x2 + b3 * x3 - a1 * y1 - a2 * y2 - a3 * y3;
      x3 = x2; x2 = x1; x1 = w; y3 = y2; y2 = y1; y1 = y;
      if (i >= 0) out[i] = y / 0.086;
    }
    const f = sr;   // sambungan loop halus
    for (let i = 0; i < f; i++) { const k = i / f; out[n - f + i] = out[n - f + i] * (1 - k) + out[i] * k; }
  }
  return buf;
}

// ---------- loudness BS.1770 (khusus 48 kHz) ----------
const KB1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], KA1 = [1, -1.69065929318241, 0.73248077421585];
const KB2 = [1, -2, 1], KA2 = [1, -1.99004745483398, 0.99007225036621];

export function integratedLoudness(channels, sr) {
  if (sr !== 48000) throw new Error("loudness: butuh 48 kHz");
  const step = sr / 10, nSub = Math.floor(channels[0].length / step), sub = new Float64Array(nSub);
  for (const x of channels) {
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0, u1 = 0, u2 = 0, z1 = 0, z2 = 0;
    for (let s = 0; s < nSub; s++) {
      let acc = 0;
      for (let i = s * step; i < (s + 1) * step; i++) {
        const y = KB1[0] * x[i] + KB1[1] * x1 + KB1[2] * x2 - KA1[1] * y1 - KA1[2] * y2;
        x2 = x1; x1 = x[i]; y2 = y1; y1 = y;
        const z = KB2[0] * y + KB2[1] * u1 + KB2[2] * u2 - KA2[1] * z1 - KA2[2] * z2;
        u2 = u1; u1 = y; z2 = z1; z1 = z;
        acc += z * z;
      }
      sub[s] += acc / step;
    }
  }
  const blocks = [];
  for (let i = 0; i + 4 <= nSub; i++) blocks.push((sub[i] + sub[i + 1] + sub[i + 2] + sub[i + 3]) / 4);
  const L = (e) => -0.691 + 10 * Math.log10(e + 1e-20);
  let g = blocks.filter((e) => L(e) > -70);
  if (!g.length) return -Infinity;
  const rel = L(g.reduce((a, b) => a + b, 0) / g.length) - 10;
  g = g.filter((e) => L(e) > rel);
  return L(g.reduce((a, b) => a + b, 0) / g.length);
}

/** Limiter lookahead (port fx.limiter): tidak menambah gain, puncak <= ceiling. */
export function limitInPlace(channels, sr, ceilingDb = -1, lookahead = 0.005, release = 0.25) {
  const c = 10 ** (ceilingDb / 20), n = channels[0].length, la = Math.max(1, Math.floor(lookahead * sr));
  const peak = new Float32Array(n);
  for (let i = 0; i < n; i++) peak[i] = Math.max(Math.abs(channels[0][i]), Math.abs(channels[1][i]));
  // maksimum berjendela [i-la, i+la] dengan deque
  const pm = new Float32Array(n), dq = new Int32Array(n);
  let h = 0, t = 0;
  for (let i = 0; i < n + la; i++) {
    if (i < n) { while (t > h && peak[dq[t - 1]] <= peak[i]) t--; dq[t++] = i; }
    const j = i - la;
    if (j >= 0) { while (dq[h] < j - la) h++; pm[j] = peak[dq[h]]; }
  }
  const g = new Float32Array(n), inst = new Float32Array(n);
  const coef = Math.exp(-1 / (release * sr));
  let env = 0;
  for (let i = 0; i < n; i++) {
    inst[i] = Math.min(1, c / Math.max(pm[i], 1e-9));
    const r = 1 - inst[i];
    env = r > env ? r : env * coef;
    g[i] = 1 - env;
  }
  // haluskan transisi (rata-rata bergerak sepanjang la)
  let acc = 0; const sm = new Float32Array(n);
  for (let i = 0; i < n; i++) { acc += g[i]; if (i >= la) acc -= g[i - la]; sm[i] = acc / Math.min(i + 1, la); }
  for (const x of channels) for (let i = 0; i < n; i++) x[i] = Math.max(-c, Math.min(c, x[i] * Math.min(sm[i], inst[i])));
}

/** WAV 16-bit PCM dengan dither TPDF. */
export function wavBlob(channels, sr) {
  const n = channels[0].length, data = new DataView(new ArrayBuffer(44 + n * 4));
  const w = (o, s) => { for (let i = 0; i < s.length; i++) data.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); data.setUint32(4, 36 + n * 4, true); w(8, "WAVE"); w(12, "fmt ");
  data.setUint32(16, 16, true); data.setUint16(20, 1, true); data.setUint16(22, 2, true);
  data.setUint32(24, sr, true); data.setUint32(28, sr * 4, true); data.setUint16(32, 4, true);
  data.setUint16(34, 16, true); w(36, "data"); data.setUint32(40, n * 4, true);
  let o = 44;
  for (let i = 0; i < n; i++) for (let ch = 0; ch < 2; ch++) {
    const d = (Math.random() - Math.random()) / 32768;
    data.setInt16(o, Math.max(-32768, Math.min(32767, Math.round((channels[ch][i] + d) * 32767))), true);
    o += 2;
  }
  return new Blob([data], { type: "audio/wav" });
}
