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

/** IR reverb sintetis: pantulan awal + ekor difus dengan decay berbeda per pita (lihat fx.make_ir). */
export function makeIR(ctx, rng, { decay, predelay, hp, early = 0.5, width = 1.0 }) {
  const sr = ctx.sampleRate;
  const n = Math.floor((decay * 1.25 + predelay) * sr);
  const pre = Math.floor(predelay * sr);
  const buf = ctx.createBuffer(2, n + pre, sr);
  const gauss = () => { let u = 0, v = 0; while (u === 0) u = rng(); v = rng(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  const bands = [["lp", 300, 0.9], ["bp", 2000, 1.0], ["bp", 6000, 0.55], ["hp", 6000, 0.28]];
  const chans = [];
  for (let ch = 0; ch < 2; ch++) {
    const noise = new Float32Array(n); for (let i = 0; i < n; i++) noise[i] = gauss();
    const tail = new Float32Array(n);
    for (const [kind, f, k] of bands) {
      const x = noise.slice();
      if (kind === "lp") { biquadInPlace(x, rbj("lp", f, sr)); biquadInPlace(x, rbj("lp", f, sr)); }
      else if (kind === "hp") { biquadInPlace(x, rbj("hp", f, sr)); biquadInPlace(x, rbj("hp", f, sr)); }
      else { const lo = f === 2000 ? 300 : 2000; const fc = Math.sqrt(lo * f); biquadInPlace(x, rbj("bp", fc, sr, 0, fc / (f - lo))); }
      const tau = decay * k;
      for (let i = 0; i < n; i++) tail[i] += x[i] * 10 ** ((-3 * i) / sr / tau);
    }
    const build = Math.floor(0.12 * sr);
    for (let i = 0; i < build; i++) tail[i] *= Math.sin(((i / build) * Math.PI) / 2) ** 2;
    let e = 0; for (let i = 0; i < n; i++) e += tail[i] * tail[i];
    const g = 1 / Math.sqrt(e || 1); for (let i = 0; i < n; i++) tail[i] *= g;
    chans.push(tail);
  }
  // pantulan awal
  const er = [new Float32Array(Math.floor(0.09 * sr)), new Float32Array(Math.floor(0.09 * sr))];
  for (let i = 0; i < 14; i++) {
    const d = 0.008 + rng() * 0.072, g = 0.9 * (1 - d / 0.09) * (0.5 + 0.5 * rng()), pan = 0.1 + 0.8 * rng();
    const j = Math.floor(d * sr);
    er[0][j] += g * Math.cos((pan * Math.PI) / 2); er[1][j] += g * Math.sin((pan * Math.PI) / 2);
  }
  let ee = 0;
  for (const c of er) { biquadInPlace(c, rbj("lp", 5000, sr, 0, 0.5)); for (const v of c) ee += v * v; }
  for (let ch = 0; ch < 2; ch++) for (let i = 0; i < er[ch].length; i++) chans[ch][i] += (er[ch][i] * early) / Math.sqrt(ee || 1);
  if (width < 1) for (let i = 0; i < n; i++) { const m = (chans[0][i] + chans[1][i]) / 2; chans[0][i] = m + (chans[0][i] - m) * width; chans[1][i] = m + (chans[1][i] - m) * width; }
  for (let ch = 0; ch < 2; ch++) {
    const x = chans[ch]; biquadInPlace(x, rbj("hp", hp, sr));
    let e = 0; for (const v of x) e += v * v;
    const g = 1 / Math.sqrt(e || 1);
    const out = buf.getChannelData(ch);
    for (let i = 0; i < n; i++) out[pre + i] = x[i] * g;
  }
  return buf;
}

/** Pink noise stereo (filter 3 kutub, kemiringan -3 dB/oktaf), RMS ~1. */
export function pinkBuffer(ctx, rng, seconds) {
  const sr = ctx.sampleRate, n = Math.floor(seconds * sr), buf = ctx.createBuffer(2, n, sr);
  const b = [0.049922035, -0.095993537, 0.050612699, -0.004408786], a = [1, -2.494956002, 2.017265875, -0.5221894];
  for (let ch = 0; ch < 2; ch++) {
    const out = buf.getChannelData(ch);
    const xs = [0, 0, 0, 0], ys = [0, 0, 0, 0];
    for (let i = -sr; i < n; i++) {
      const w = (rng() + rng() + rng() + rng() - 2) * 1.732;
      xs.unshift(w); xs.pop();
      const y = b[0] * xs[0] + b[1] * xs[1] + b[2] * xs[2] + b[3] * xs[3] - a[1] * ys[0] - a[2] * ys[1] - a[3] * ys[2];
      ys.unshift(y); ys.pop();
      if (i >= 0) out[i] = y / 0.086;
    }
    // sambungan loop halus: crossfade 1 detik akhir ke awal
    const f = sr;
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
