// Antarmuka Spacenight Studio.
import { resolve, technical, deepMerge, MODES, NOTE_NAMES, FORM_TYPES } from "./music.js";
import { Engine } from "./engine.js";
import { integratedLoudness, limitInPlace, wavBlob } from "./dsp.js";
import { toToml } from "./toml.js";

const SR = 48000;
const $ = (s) => document.querySelector(s);
let DATA, ctx = null, engine = null, timer = null, restartTimer = null;
const state = { presetKey: null, raw: null, seed: 1, touched: new Set() };

const MODE_NAMES = { lydian: "Luas & melayang", ionian: "Cerah & manis", mixolydian: "Ringan & santai",
  dorian: "Sendu & hangat", aeolian: "Gelap & tenang", phrygian: "Misterius" };
const FORM_NAMES = { arc: "Naik-turun lembut", rise: "Tumbuh perlahan", valley: "Menenang di tengah",
  calm: "Datar & tenang", journey: "Berpindah suasana" };

// kontrol: [path, label, min, max, step, keterangan]
const CONTROLS = {
  "Suara latar": [
    ["pad.brightness", "Kecerahan", 0, 1, 0.01, "gelap → terang"],
    ["pad.width", "Lebar", 0, 1, 0.01, "sempit → lebar"],
    ["pad.movement", "Gerak", 0, 1, 0.01, "statis → bergerak"],
    ["pad.life", "Analog", 0, 1, 0.01, "kaku → hidup"],
    ["drone.brightness", "Drone: kecerahan", 0, 1, 0.01, ""],
  ],
  Melodi: [
    ["melody.density", "Kepadatan", 0, 1, 0.01, "jarang → sering"],
    ["melody.phrases", "Frasa", 0, 1, 0.01, "nada tunggal → frasa 2–3 nada"],
    ["melody.register", "Tinggi nada", 0, 1, 0.01, "rendah → tinggi"],
    ["melody.decay", "Panjang nada", 3, 16, 0.5, "detik"],
  ],
  Ruang: [
    ["space.reverb_mix", "Gema", 0, 1, 0.01, "kering → luas"],
    ["space.reverb_decay", "Panjang gema", 4, 18, 0.5, "detik"],
    ["texture.brightness", "Angin: kecerahan", 0, 1, 0.01, ""],
  ],
  Variasi: [
    ["variation.amount", "Perubahan antar babak", 0, 1, 0.01, "sama terus → banyak berubah"],
    ["form.amount", "Naik-turun intensitas", 0, 1, 0.01, "datar → terasa"],
  ],
  Mix: [
    ["mix.drone", "Drone", 0, 1.2, 0.01, ""],
    ["mix.pad", "Pad", 0, 1.2, 0.01, ""],
    ["mix.melody", "Melodi", 0, 0.5, 0.005, "0 = tanpa melodi"],
    ["mix.texture", "Angin", 0, 0.12, 0.001, ""],
  ],
};

const get = (o, path) => path.split(".").reduce((a, k) => a?.[k], o);
const set = (o, path, v) => { const ks = path.split("."); let n = o; for (const k of ks.slice(0, -1)) n = n[k] ??= {}; n[ks.at(-1)] = v; };
const fmt = (v, step) => (step >= 1 ? v.toFixed(0) : step >= 0.1 ? v.toFixed(1) : step >= 0.01 ? v.toFixed(2) : v.toFixed(3));

async function init() {
  DATA = await (await fetch("presets.json")).json();
  const sel = $("#preset");
  for (const [k, p] of Object.entries(DATA.presets)) sel.add(new Option(p.name, k));
  for (const n of NOTE_NAMES) $("#tonic").add(new Option(n, n));
  for (const m of Object.keys(MODES)) $("#mode").add(new Option(MODE_NAMES[m] || m, m));
  $("#formtype").add(new Option("Pilihan preset", "")); 
  for (const f of FORM_TYPES) $("#formtype").add(new Option(FORM_NAMES[f], f));
  buildControls();
  sel.onchange = () => loadPreset(sel.value);
  $("#seed").onchange = () => { state.seed = parseInt($("#seed").value || "1", 10); refresh(); };
  $("#dice").onclick = () => { state.seed = Math.floor(Math.random() * 99999) + 1; $("#seed").value = state.seed; refresh(); };
  $("#tonic").onchange = () => { set(state.raw, "key.tonic", $("#tonic").value); refresh(); };
  $("#mode").onchange = () => { set(state.raw, "key.mode", $("#mode").value); refresh(); };
  $("#formtype").onchange = () => {
    set(state.raw, "form.type", $("#formtype").value || structuredClone(DATA.presets[state.presetKey].form?.type ?? DATA.defaults.form.type));
    refresh();
  };
  $("#newver").onclick = () => {   // nomor versi + nada dasar baru: menurut ukuran kemiripan, ini yang paling membedakan
    const cur = current().P.tonicName;
    let n; do { n = NOTE_NAMES[Math.floor(Math.random() * 12)]; } while (n === cur);
    set(state.raw, "key.tonic", n);
    state.seed = Math.floor(Math.random() * 99999) + 1; $("#seed").value = state.seed;
    refresh();
  };
  $("#timbre").onchange = () => { set(state.raw, "melody.timbre", $("#timbre").value); refresh(); };
  $("#consonance").onchange = () => { set(state.raw, "melody.consonance", $("#consonance").checked ? 1.0 : 0.0); refresh(); };
  $("#play").onclick = togglePlay;
  $("#reset").onclick = () => loadPreset(state.presetKey);
  $("#toml").onclick = downloadToml;
  $("#render").onclick = renderWav;
  $("#copy").onclick = () => navigator.clipboard?.writeText($("#cmd").textContent);
  loadPreset(Object.keys(DATA.presets)[0]);
  drawLoop();
}

function buildControls() {
  const host = $("#controls");
  for (const [group, items] of Object.entries(CONTROLS)) {
    const box = document.createElement("section"); box.className = "group";
    box.innerHTML = `<h3>${group}</h3>`;
    for (const [path, label, min, max, step, hint] of items) {
      const row = document.createElement("label"); row.className = "ctl";
      row.innerHTML = `<span class="name">${label}<i class="rnd" title="diacak per seed"></i>${hint ? `<small>${hint}</small>` : ""}</span>
        <input type="range" min="${min}" max="${max}" step="${step}" data-path="${path}">
        <output></output>`;
      const input = row.querySelector("input");
      input.oninput = () => {
        set(state.raw, path, parseFloat(input.value)); state.touched.add(path);
        row.querySelector("output").textContent = fmt(parseFloat(input.value), step);
        row.classList.remove("random");
        refresh();
      };
      box.appendChild(row);
    }
    host.appendChild(box);
  }
}

function loadPreset(key) {
  state.presetKey = key;
  state.raw = deepMerge(DATA.defaults, DATA.presets[key]);
  state.seed = state.raw.seed; state.touched.clear();
  $("#preset").value = key; $("#seed").value = state.seed;
  refresh();
}

function current() {
  const r = resolve(state.raw, state.seed);
  return { r, P: technical(r, DATA) };
}

/** Perbarui tampilan; kalau sedang memutar, mulai ulang mesin dengan crossfade (debounce). */
function refresh() {
  const { r, P } = current();
  $("#tonic").value = P.tonicName; $("#mode").value = P.mode;
  $("#formtype").value = Array.isArray(state.raw.form?.type) ? "" : r.form.type;
  $("#formtype").options[0].text = Array.isArray(state.raw.form?.type) ? `Pilihan preset (${FORM_NAMES[r.form.type]})` : "Pilihan preset";
  $("#timbre").value = r.melody.timbre; $("#consonance").checked = r.melody.consonance > 0;
  for (const input of document.querySelectorAll("#controls input")) {
    const path = input.dataset.path, raw = get(state.raw, path), v = get(r, path);
    input.value = v; input.nextElementSibling.textContent = fmt(+v, parseFloat(input.step));
    input.parentElement.classList.toggle("random", Array.isArray(raw) && !state.touched.has(path));
  }
  $("#keyinfo").textContent = `Nada ${P.tonicName}, ${MODE_NAMES[P.mode].toLowerCase()} · bentuk: ${FORM_NAMES[r.form.type].toLowerCase()} · volume akhir ${r.master.target_lufs} LUFS (${r.master.target_lufs >= -14.5 ? "standar YouTube" : "lebih pelan, untuk tidur/tenang"})`;
  $("#cmd").textContent = `python generate.py ${fileName()}.toml --duration 60`;
  if (engine) { clearTimeout(restartTimer); restartTimer = setTimeout(() => startEngine(true), 450); }
}

function fileName() {
  const base = (state.raw.name || "spacenight").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return `${base}_s${state.seed}`;
}

// ---------- pemutaran ----------
async function togglePlay() {
  if (engine) { engine.stop(); engine = null; clearInterval(timer); setPlayButton(false); return; }
  ctx ??= new AudioContext({ sampleRate: SR, latencyHint: "playback" });
  await ctx.resume();
  startEngine(false);
  setPlayButton(true);
}

function setPlayButton(on) {
  const b = $("#play");
  b.innerHTML = `<svg class="ic"><use href="#i-${on ? "stop" : "play"}"/></svg><span>${on ? "Berhenti" : "Putar"}</span>`;
  b.classList.toggle("on", on);
}

const agc = { hist: [], gainDb: 0 };
function startEngine(crossfade) {
  const { P } = current();
  const old = engine;
  engine = new Engine(ctx, P, state.seed, { total: null });
  engine.masterGain.gain.value = 10 ** (agc.gainDb / 20);
  if (crossfade) { engine.out.gain.setValueAtTime(0, ctx.currentTime); engine.out.gain.linearRampToValueAtTime(1, ctx.currentTime + 2.5); }
  if (old) old.stop(2.5);
  engine.scheduleUntil(20);
  setupMeter();
  clearInterval(timer);
  timer = setInterval(tick, 250);
}

// meter loudness kira-kira (K-weighting didekati dengan biquad) + penyesuaian volume otomatis pelan
let meter = null;
function setupMeter() {
  const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 38; hp.Q.value = 0.5;
  const sh = ctx.createBiquadFilter(); sh.type = "highshelf"; sh.frequency.value = 1500; sh.gain.value = 4;
  const sp = ctx.createChannelSplitter(2);
  const an = [ctx.createAnalyser(), ctx.createAnalyser()];
  an.forEach((a) => (a.fftSize = 16384));
  engine.meterTap.connect(hp).connect(sh).connect(sp);
  sp.connect(an[0], 0); sp.connect(an[1], 1);
  const viz = ctx.createAnalyser(); viz.fftSize = 4096; viz.smoothingTimeConstant = 0.85;
  engine.out.connect(viz);
  meter = { an, buf: new Float32Array(16384), viz };
  agc.hist = [];
}

function tick() {
  if (!engine) return;
  const t = engine.now();
  engine.scheduleUntil(t + 20);
  const { chord, intensity, section } = engine.info(t);
  $("#chord").textContent = chord || "–";
  $("#section").textContent = section ? describeSection(section) : "–";
  $("#intensity").style.width = `${Math.round(intensity * 100)}%`;
  const mm = Math.floor(t / 60), ss = Math.floor(t % 60);
  $("#time").textContent = `${mm}:${String(ss).padStart(2, "0")}`;
  // loudness: energi K-weighted rata-rata ~20 detik terakhir
  if (meter && t > 2) {
    let e = 0;
    for (const a of meter.an) { a.getFloatTimeDomainData(meter.buf); let s = 0; for (const v of meter.buf) s += v * v; e += s / meter.buf.length; }
    agc.hist.push(e); if (agc.hist.length > 80) agc.hist.shift();
    const mean = agc.hist.reduce((a, b) => a + b, 0) / agc.hist.length;
    const lufs = -0.691 + 10 * Math.log10(mean + 1e-12);     // sebelum gain master
    const target = current().r.master.target_lufs;
    if (agc.hist.length >= 24) {   // setelah ~6 s: arahkan gain master pelan-pelan ke target
      const want = Math.max(-24, Math.min(24, target - lufs));
      agc.gainDb += Math.max(-0.15, Math.min(0.15, want - agc.gainDb));
      engine.masterGain.gain.setTargetAtTime(10 ** (agc.gainDb / 20), ctx.currentTime, 0.5);
    }
    $("#lufs").textContent = `≈ ${(lufs + agc.gainDb).toFixed(1)} LUFS`;
  }
}

function describeSection(s) {
  const bits = [];
  if (s.melody === 0) bits.push("melodi istirahat");
  else if (s.melody > 1.15) bits.push("melodi lebih ramai");
  else if (s.melody < 0.85) bits.push("melodi lebih sepi");
  if (s.register > 0) bits.push("melodi lebih tinggi");
  if (s.register < 0) bits.push("melodi lebih rendah");
  if (s.texture > 1.25) bits.push("angin lebih kuat");
  if (s.texture < 0.75) bits.push("angin lebih lemah");
  return `${s.no}${bits.length ? " · " + bits.join(", ") : ""}`;
}

function drawLoop() {
  // spektrum sebagai satu garis tipis di atas grid frekuensi (100 Hz, 1 kHz, 10 kHz)
  const cv = $("#viz"), g = cv.getContext("2d");
  const css = getComputedStyle(document.documentElement);
  const color = (v) => css.getPropertyValue(v).trim();
  const fx = (f, w) => (Math.log(f / 30) / Math.log(16000 / 30)) * w;
  const draw = () => {
    const dpr = devicePixelRatio || 1;
    const w = (cv.width = cv.clientWidth * dpr), h = (cv.height = cv.clientHeight * dpr);
    g.clearRect(0, 0, w, h);
    g.font = `${10 * dpr}px "IBM Plex Mono", monospace`;
    g.fillStyle = color("--ink-3"); g.strokeStyle = color("--line"); g.lineWidth = 1;
    for (const [f, lab] of [[100, "100 Hz"], [1000, "1 kHz"], [10000, "10 kHz"]]) {
      const x = Math.round(fx(f, w)) + 0.5;
      g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke();
      const tw = g.measureText(lab).width;
      g.fillText(lab, x + 6 * dpr + tw > w ? x - 6 * dpr - tw : x + 6 * dpr, h - 8 * dpr);
    }
    if (engine && meter) {
      const a = meter.viz, d = new Float32Array(a.frequencyBinCount);
      a.getFloatFrequencyData(d);
      g.beginPath();
      for (let x = 0; x <= w; x += 2) {
        // rata-rata energi dalam jendela 1/6 oktaf -> garis halus, bukan sisir harmonik
        const f = 30 * (16000 / 30) ** (x / w), bin = (SR / 2) / d.length;
        const i0 = Math.max(0, Math.floor((f * 2 ** (-1 / 12)) / bin)), i1 = Math.min(d.length - 1, Math.ceil((f * 2 ** (1 / 12)) / bin));
        let e = 0; for (let i = i0; i <= i1; i++) e += 10 ** (d[i] / 10);
        const db = 10 * Math.log10(e / (i1 - i0 + 1) + 1e-12);
        const y = h - ((Math.max(-110, db) + 110) / 85) * h;
        x === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
      }
      g.strokeStyle = color("--accent"); g.lineWidth = 1.5 * dpr; g.stroke();
    }
    requestAnimationFrame(draw);
  };
  draw();
}

// ---------- ekspor ----------
function downloadToml() {
  // nilai yang PERSIS sedang terdengar: rentang [min,max] dan daftar pilihan sudah dipilih untuk seed ini,
  // supaya versi Python memakai warna suara yang sama (Python punya generator acak sendiri)
  const out = resolve(state.raw, state.seed);
  if (!out.name.includes("(studio)")) out.name = `${out.name} (studio)`;
  const text = `# Dibuat di Spacenight Studio. Render: python generate.py ${fileName()}.toml --duration 60\n` + toToml(out);
  download(new Blob([text], { type: "text/plain" }), `${fileName()}.toml`);
}

async function renderWav() {
  const minutes = Math.max(0.25, Math.min(15, parseFloat($("#minutes").value) || 2));
  const total = minutes * 60, btn = $("#render");
  btn.disabled = true;
  const { r, P } = current();
  const oc = new OfflineAudioContext(2, Math.round(total * SR), SR);
  const eng = new Engine(oc, P, state.seed, { total, offline: true, start: 0 });
  eng.scheduleUntil(total);
  const step = Math.max(5, Math.floor(total / 40));
  for (let t = step; t < total; t += step) oc.suspend(t).then(() => { $("#progress").value = t / total; oc.resume(); });
  $("#status").textContent = "Me-render…";
  const t0 = performance.now();
  const buf = await oc.startRendering();
  $("#status").textContent = "Mastering…";
  await new Promise((res) => setTimeout(res, 20));
  const ch = [buf.getChannelData(0), buf.getChannelData(1)];
  const lufs0 = integratedLoudness(ch, SR);
  const gain = 10 ** ((r.master.target_lufs - lufs0) / 20);
  for (const x of ch) for (let i = 0; i < x.length; i++) x[i] *= gain;
  limitInPlace(ch, SR, -1.0);
  const lufs = integratedLoudness(ch, SR);
  download(wavBlob(ch, SR), `${fileName()}_${Math.round(total)}s.wav`);
  $("#progress").value = 1;
  $("#status").textContent = `Selesai dalam ${((performance.now() - t0) / 1000).toFixed(0)} s · ${lufs.toFixed(1)} LUFS`;
  btn.disabled = false;
  window.__lastRender = { lufs, lufs0, seconds: total };
}

function download(blob, name) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

init();
