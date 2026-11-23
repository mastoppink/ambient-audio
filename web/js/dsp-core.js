// Inti DSP per sampel yang dipakai bersama oleh thread halaman dan AudioWorklet (thread audio).
// Port dari ambient-gen/fx.py (FDNReverb, Warmth). File ini sengaja tanpa import: worklets.js
// menggabungkannya dengan worklet-processors.js menjadi satu modul.

export const FDN_BASE_MS = [29.7, 37.1, 41.1, 43.7, 53.3, 61.9, 71.3, 97.1];
const HAD8_ROWS = (() => {                       // baris matriks Hadamard 8x8 (Sylvester)
  const H = [[1]];
  let M = H;
  for (let s = 0; s < 3; s++) M = M.map((r) => r.concat(r)).concat(M.map((r) => r.concat(r.map((v) => -v))));
  return M;
})();

/** Reverb FDN 8 jalur dengan modulasi (lihat fx.FDNReverb). Masukan sudah melewati predelay + high-pass. */
export class FDNCore {
  /**
   * @param o { sr, decay, size, modDepthMs, hfRatio, width, lfoF[8], lfoPh[8] }
   */
  constructor(o) {
    const sr = o.sr, N = 8;
    this.N = N; this.sr = sr;
    this.L = FDN_BASE_MS.map((ms) => (Math.floor((ms * (o.size || 1) * sr) / 1000) | 1));
    this.depth = ((o.modDepthMs ?? 0.5) * sr) / 1000;
    const need = Math.max(...this.L) + this.depth + 8;
    this.S = 1 << Math.ceil(Math.log2(need));
    this.mask = this.S - 1;
    this.buf = new Float64Array(N * this.S);
    this.w = 0; this.n = 0;
    const hf = o.hfRatio ?? 0.4;
    this.g = this.L.map((L) => 10 ** ((-3 * L) / (o.decay * sr)));
    this.a = this.L.map((L, i) => {
      const r = Math.min(1, Math.max(1e-4, 10 ** ((-3 * L) / (o.decay * hf * sr)) / this.g[i]));
      return (1 - r) / (1 + r);
    });
    this.zi = new Float64Array(N);
    this.lfoW = o.lfoF.map((f) => (2 * Math.PI * f) / sr);
    this.lfoPh = o.lfoPh.slice();
    const s8 = Math.sqrt(N), s4 = Math.sqrt(N / 2);
    this.outL = HAD8_ROWS[1].map((v) => v / s8); this.outR = HAD8_ROWS[2].map((v) => v / s8);
    this.inL = HAD8_ROWS[3].map((v) => v / s4); this.inR = HAD8_ROWS[5].map((v) => v / s4);
    this.width = o.width ?? 1;
    // difusi awal: 4 allpass per kanal
    this.ap = [0, 1].map((ch) => [[4.77, 0.7], [3.59, 0.7], [12.73, 0.6], [9.31, 0.6]].map(([ms, g]) => {
      const D = Math.floor(((ms * sr) / 1000) * (ch ? 1.07 : 1));
      return { g, D, xb: new Float64Array(D), yb: new Float64Array(D), w: 0 };
    }));
    this.d = new Float64Array(N); this.y = new Float64Array(N);
  }

  _allpass(st, x) {
    const j = st.w;
    const y = -st.g * x + st.xb[j] + st.g * st.yb[j];
    st.xb[j] = x; st.yb[j] = y;
    st.w = j + 1 === st.D ? 0 : j + 1;
    return y;
  }

  /** Proses n sampel. inL/inR/outL/outR: Float32Array (boleh sama untuk masukan & keluaran). */
  process(inL, inR, outL, outR, n) {
    const N = this.N, S = this.S, mask = this.mask, buf = this.buf, d = this.d, y = this.y;
    for (let k = 0; k < n; k++) {
      let xl = inL[k], xr = inR[k];
      for (const st of this.ap[0]) xl = this._allpass(st, xl);
      for (const st of this.ap[1]) xr = this._allpass(st, xr);
      const nn = this.n + k;
      let ssum = 0;
      for (let i = 0; i < N; i++) {
        const pos = this.w - this.L[i] - this.depth * (0.5 + 0.5 * Math.sin(this.lfoW[i] * nn + this.lfoPh[i]));
        const i0 = Math.floor(pos), fr = pos - i0;
        const base = i * S;
        const v = buf[base + (i0 & mask)] * (1 - fr) + buf[base + ((i0 + 1) & mask)] * fr;
        d[i] = v;
        this.zi[i] = (1 - this.a[i]) * v + this.a[i] * this.zi[i];
        y[i] = this.zi[i] * this.g[i];
        ssum += y[i];
      }
      let ol = 0, or = 0;
      const wi = this.w & mask;
      for (let i = 0; i < N; i++) {
        buf[i * S + wi] = y[i] - (2 / N) * ssum + this.inL[i] * xl + this.inR[i] * xr;
        ol += this.outL[i] * d[i]; or += this.outR[i] * d[i];
      }
      if (this.width < 1) { const m = (ol + or) / 2; ol = m + (ol - m) * this.width; or = m + (or - m) * this.width; }
      outL[k] = ol; outR[k] = or;
      this.w = (this.w + 1) & mask;
    }
    this.n += n;
  }
}

/** Energi respons impuls FDN (per kanal, rata-rata) -> pengali normalisasi (setara IR berenergi 1). */
export function fdnNormGain(o) {
  const core = new FDNCore(o), B = 1024, n = Math.floor(o.decay * 1.3 * o.sr);
  const iL = new Float32Array(B), iR = new Float32Array(B), oL = new Float32Array(B), oR = new Float32Array(B);
  let e = 0;
  for (let s = 0; s < n; s += B) {
    iL.fill(0); iR.fill(0);
    if (s === 0) { iL[0] = 1; iR[0] = 1; }
    core.process(iL, iR, oL, oR, B);
    for (let k = 0; k < B; k++) e += oL[k] * oL[k] + oR[k] * oR[k];
  }
  return 1 / Math.sqrt(e / 2 + 1e-20);
}

/** Kehangatan pita: saturasi relatif level + wow/flutter + desis (lihat fx.Warmth). Warna nada di luar (biquad). */
export class WarmthCore {
  constructor(o) {
    this.sr = o.sr;
    this.set(o);
    this.env = -1;
    this.coef = Math.exp(-1 / (8 * o.sr));
    this.S = 4096; this.mask = 4095;
    this.bufL = new Float64Array(this.S); this.bufR = new Float64Array(this.S);
    this.w = 0; this.n = 0;
    this.wf = o.wowF; this.ff = o.flutF; this.wph = o.wowPh; this.fph = o.flutPh;
    this.dfr = o.driftF; this.dph = o.driftPh;
    let s = o.noiseSeed >>> 0 || 1;
    this.rand = () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
    // filter desis: hp 400, lp 11000, high-shelf +3 dB di 4 kHz (biquad RBJ)
    this.hiss = [biq("hp", 400, o.sr, 0, 0.7), biq("lp", 11000, o.sr, 0, 0.7), biq("hs", 4000, o.sr, 3, 0.7)];
  }

  set(o) {
    const a = o.amount;
    this.k = 0.06 + 0.22 * a; this.bias = 0.25 * a; this.sat = a > 0;
    const sr = this.sr, t = o.tape;
    this.wow = ((3.0 * t * 1e-3 * Math.LN2) / 1.2 / (2 * Math.PI * (o.wowF ?? this.wf))) * sr;
    this.flut = ((0.5 * t * 1e-3 * Math.LN2) / 1.2 / (2 * Math.PI * (o.flutF ?? this.ff))) * sr;
    this.D0 = 3 * 1.6 * 1e-3 * Math.LN2 / 1.2 / (2 * Math.PI * 0.4) * sr + 30;   // tetap (maks), agar latensi tidak berubah
    this.noiseG = o.noise > 0 ? 10 ** ((-62 + 12 * o.noise) / 20) : 0;
  }

  process(inL, inR, outL, outR, n) {
    const tp = 2 * Math.PI, sr = this.sr, mask = this.mask;
    if (this.env < 0) { let e = 0; for (let k = 0; k < n; k++) e += (inL[k] * inL[k] + inR[k] * inR[k]) / 2; this.env = Math.max(e / n, 1e-8); }
    const kk = this.k, b = this.bias, tb = Math.tanh(kk * b), norm = 1 / (kk * (1 - tb * tb));
    for (let k = 0; k < n; k++) {
      let l = inL[k], r = inR[k];
      this.env = (1 - this.coef) * ((l * l + r * r) / 2) + this.coef * this.env;
      const ref = Math.sqrt(Math.max(this.env, 1e-10));
      if (this.sat) {
        l = (Math.tanh(kk * (l / ref + b)) - tb) * norm * ref;
        r = (Math.tanh(kk * (r / ref + b)) - tb) * norm * ref;
      }
      if (this.wow > 0) {
        const t = (this.n + k) / sr;
        const m = this.wow * (Math.sin(tp * this.wf * t + this.wph) * 0.8 + 0.12 * Math.sin(tp * this.dfr[0] * t + this.dph[0])
          + 0.08 * Math.sin(tp * this.dfr[1] * t + this.dph[1])) + this.flut * Math.sin(tp * this.ff * t + this.fph);
        const wi = this.w & mask;
        this.bufL[wi] = l; this.bufR[wi] = r;
        const pos = this.w - this.D0 - m, i0 = Math.floor(pos), fr = pos - i0;
        l = this.bufL[i0 & mask] * (1 - fr) + this.bufL[(i0 + 1) & mask] * fr;
        r = this.bufR[i0 & mask] * (1 - fr) + this.bufR[(i0 + 1) & mask] * fr;
        this.w = (this.w + 1) & mask;
      }
      if (this.noiseG > 0) {
        for (let c = 0; c < 2; c++) {
          let h = (this.rand() + this.rand() + this.rand() + this.rand() - 2) * 1.732;
          for (const f of this.hiss) h = f.step(h, c);
          if (c === 0) l += h * ref * this.noiseG; else r += h * ref * this.noiseG;
        }
      }
      outL[k] = l; outR[k] = r;
    }
    this.n += n;
  }
}

function biq(kind, f, sr, gainDb, q) {
  const A = 10 ** (gainDb / 40), w0 = (2 * Math.PI * f) / sr, cw = Math.cos(w0), al = Math.sin(w0) / (2 * q);
  let b, a;
  if (kind === "lp") { b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]; a = [1 + al, -2 * cw, 1 - al]; }
  else if (kind === "hp") { b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + al, -2 * cw, 1 - al]; }
  else {
    const s = 2 * Math.sqrt(A) * al;
    b = [A * ((A + 1) + (A - 1) * cw + s), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - s)];
    a = [(A + 1) - (A - 1) * cw + s, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - s];
  }
  const b0 = b[0] / a[0], b1 = b[1] / a[0], b2 = b[2] / a[0], a1 = a[1] / a[0], a2 = a[2] / a[0];
  const st = [[0, 0, 0, 0], [0, 0, 0, 0]];
  return { step(x, c) { const s = st[c]; const y = b0 * x + b1 * s[0] + b2 * s[1] - a1 * s[2] - a2 * s[3]; s[1] = s[0]; s[0] = x; s[3] = s[2]; s[2] = y; return y; } };
}
