// Memuat AudioWorklet: dsp-core.js + worklet-processors.js digabung jadi satu modul (Blob URL),
// supaya kode DSP hanya ditulis sekali dan tidak bergantung pada dukungan import di worklet.
import { fdnNormGain, FDNCore } from "./dsp-core.js";

let SOURCE = null;
const LOADED = new WeakMap();

async function source() {
  if (!SOURCE) {
    const base = new URL(".", import.meta.url);
    const [core, proc] = await Promise.all([
      fetch(new URL("dsp-core.js", base)).then((r) => r.text()),
      fetch(new URL("worklet-processors.js", base)).then((r) => r.text()),
    ]);
    SOURCE = URL.createObjectURL(new Blob([core.replace(/^export /gm, "") + "\n" + proc], { type: "text/javascript" }));
  }
  return SOURCE;
}

/** Pastikan worklet sudah dimuat di konteks ini (sekali per konteks). */
export function ensureWorklets(ctx) {
  if (!ctx.audioWorklet) return Promise.reject(new Error("AudioWorklet tidak didukung browser ini"));
  if (!LOADED.has(ctx)) LOADED.set(ctx, source().then((url) => ctx.audioWorklet.addModule(url)));
  return LOADED.get(ctx);
}

const GAIN_CACHE = new Map();
/** Faktor normalisasi FDN, dihitung bertahap (potongan ~15 ms) agar halaman tidak macet. Di-cache. */
export function fdnGainAsync(o) {
  const key = JSON.stringify(o);
  if (!GAIN_CACHE.has(key)) {
    GAIN_CACHE.set(key, (async () => {
      const core = new FDNCore(o), B = 1024, n = Math.floor(o.decay * 1.3 * o.sr);
      const iL = new Float32Array(B), iR = new Float32Array(B), oL = new Float32Array(B), oR = new Float32Array(B);
      let e = 0, t = performance.now();
      for (let s = 0; s < n; s += B) {
        iL.fill(0); iR.fill(0);
        if (s === 0) { iL[0] = 1; iR[0] = 1; }
        core.process(iL, iR, oL, oR, B);
        for (let k = 0; k < B; k++) e += oL[k] * oL[k] + oR[k] * oR[k];
        if (performance.now() - t > 12) { await new Promise((r) => setTimeout(r, 0)); t = performance.now(); }
      }
      return 1 / Math.sqrt(e / 2 + 1e-20);
    })());
    if (GAIN_CACHE.size > 16) GAIN_CACHE.delete(GAIN_CACHE.keys().next().value);
  }
  return GAIN_CACHE.get(key);
}

export { fdnNormGain };
