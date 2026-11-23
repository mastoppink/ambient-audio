// Piano model fisik (port dari ambient-gen/synth.py: _piano_note). Tiap nada dirender sekali oleh mesin
// audio bawaan browser (OfflineAudioContext, di luar thread halaman), lalu disimpan di cache.
import { rngFor, midiToHz } from "./music.js";

const CACHE = new Map();
const MAX_HZ = 9000;
let BODY = null;

/** Respons papan suara + rangka (120 ms): bunyi langsung senar dominan + resonansi kayu teredam + noise
 *  berwarna yang meluruh ~40 ms. Rumus sama dengan synth._soundboard_ir (Python). */
const BODY_MODES = [[95, 12, 0.8], [180, 14, 0.7], [290, 16, 0.6], [480, 18, 0.45], [820, 20, 0.3], [1350, 22, 0.2], [2400, 25, 0.12]];
const BODY_MODE_GAIN = 0.02, BODY_NOISE_GAIN = 0.03;

function bodyIR(sr) {
  if (BODY && BODY.sampleRate === sr) return BODY;
  const n = Math.floor(0.12 * sr), r = rngFor(424242, "body"), ir = new Float64Array(n);
  for (const [f, q, g] of BODY_MODES)
    for (let i = 0; i < n; i++) { const t = i / sr; ir[i] += BODY_MODE_GAIN * g * Math.sin(2 * Math.PI * f * t) * Math.exp((-Math.PI * f / q) * t); }
  // noise gaussian, band-pass 150-4000 Hz (high-pass + low-pass orde 2), meluruh 40 ms
  const noise = new Float64Array(n);
  for (let i = 0; i < n; i++) noise[i] = Math.sqrt(-2 * Math.log(1 - r())) * Math.cos(2 * Math.PI * r());
  for (const [kind, fc] of [["hp", 150], ["lp", 4000]]) {
    const w0 = (2 * Math.PI * fc) / sr, cw = Math.cos(w0), al = Math.sin(w0) / (2 * Math.SQRT1_2);
    const b = kind === "lp" ? [(1 - cw) / 2, 1 - cw, (1 - cw) / 2] : [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2], a0 = 1 + al;
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    for (let i = 0; i < n; i++) {
      const y = (b[0] * noise[i] + b[1] * x1 + b[2] * x2 + 2 * cw * y1 - (1 - al) * y2) / a0;
      x2 = x1; x1 = noise[i]; y2 = y1; y1 = y; noise[i] = y;
    }
  }
  for (let i = 0; i < n; i++) ir[i] += BODY_NOISE_GAIN * noise[i] * Math.exp(-i / sr / 0.04);
  ir[0] += 1.0;
  let e = 0; for (const v of ir) e += v * v;
  const g = 1 / Math.sqrt(e);
  BODY = new AudioBuffer({ numberOfChannels: 1, length: n, sampleRate: sr });
  const d = BODY.getChannelData(0); for (let i = 0; i < n; i++) d[i] = ir[i] * g;
  return BODY;
}

/**
 * Buffer mono satu nada piano.
 * @param vel 0..1 (dibulatkan 0,1 untuk cache), decay: waktu peluruhan acuan di C4 (detik)
 */
export function pianoBuffer(sr, midi, vel, decay, seconds) {
  const v10 = Math.round(Math.min(1, Math.max(0.2, vel)) * 10) / 10;
  const key = [sr, midi, v10, decay, seconds].join("|");
  if (!CACHE.has(key)) CACHE.set(key, renderNote(sr, midi, v10, decay, seconds));
  if (CACHE.size > 96) CACHE.delete(CACHE.keys().next().value);
  return CACHE.get(key);
}

async function renderNote(sr, midi, vel, decay, seconds) {
  const r = rngFor(midi, "piano");
  const n = Math.floor(seconds * sr), f = midiToHz(midi);
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const oc = new OAC(1, n, sr);
  const sum = oc.createGain(); sum.gain.value = 1 / 1.6;
  const conv = oc.createConvolver(); conv.normalize = false; conv.buffer = bodyIR(sr);
  sum.connect(conv).connect(oc.destination);
  const B = Math.min(0.02, Math.max(4e-5, 0.00035 * 2 ** (((midi - 60) / 12) * 1.3)));
  const beta = 1 / (6.8 + r() * 1.7);                 // posisi palu ~1/7..1/8,5
  const v = vel * (0.85 + 0.15 * r());
  const tilt = 2.3 - 1.2 * v;                         // pelan -> lebih gelap
  const tau = decay * 2 ** (-(midi - 60) / 22);       // nada rendah berdengung lebih lama
  const nStr = midi >= 46 ? 3 : 2;
  const detunes = [0, 0.2 + 0.6 * r(), -(0.2 + 0.6 * r())].slice(0, nStr);
  const gains = [1, 0.45, 0.3].slice(0, nStr), gsum = gains.reduce((a, b) => a + b, 0);
  const K = Math.min(48, Math.floor(MAX_HZ / f));
  for (let k = 1; k <= K; k++) {
    const fk = f * k * Math.sqrt(1 + B * k * k);
    if (fk > MAX_HZ) break;
    const amp = Math.abs(Math.sin(Math.PI * k * beta)) / k ** tilt;
    if (amp < 1e-4) continue;
    const tk = tau / (1 + 0.11 * (k - 1) ** 1.3);
    const end = Math.min(seconds, tk * Math.log(1e4 * Math.max(amp * 50, 1)));
    // parsial atas: senar digabung (denyutnya tidak terdengar), hemat node
    const strings = k <= 12 ? detunes.map((c, i) => [c, gains[i] / gsum]) : [[0, 1]];
    for (const [c, gs] of strings) {
      const o = oc.createOscillator(); o.frequency.value = fk * 2 ** (c / 1200);
      for (const [w, tc] of [[0.65, tk * 0.11], [0.35, tk]]) {   // peluruhan dua tahap
        const g = oc.createGain();
        g.gain.setValueAtTime(amp * gs * w, 0); g.gain.setTargetAtTime(0, 0, tc);
        o.connect(g).connect(sum);
      }
      o.start(0); o.stop(end);
    }
  }
  // bunyi palu: semburan noise ~3 ms
  const hl = Math.floor(0.015 * sr), hb = oc.createBuffer(1, hl, sr), hd = hb.getChannelData(0);
  for (let i = 0; i < hl; i++) hd[i] = (r() * 2 - 1) * Math.exp(-i / (0.003 * sr));
  const hs = oc.createBufferSource(); hs.buffer = hb;
  const bp = oc.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = Math.sqrt(300 * (1500 + 3500 * v)); bp.Q.value = 0.7;
  const hg = oc.createGain(); hg.gain.value = 0.05 * v * 1.7;
  hs.connect(bp).connect(hg).connect(sum); hs.start(0);
  return oc.startRendering();
}
