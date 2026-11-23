// Antarmuka Spacenight Studio.
import { resolve, technical, deepMerge, clone, MODES, NOTE_NAMES, FORM_TYPES } from "./music.js";
import { Engine } from "./engine.js";
import { integratedLoudness, limitInPlace, wavBlob } from "./dsp.js";
import { toToml } from "./toml.js";
import { buatJudul } from "./judul.js";

const SR = 48000;
const $ = (s) => document.querySelector(s);
let DATA, ctx = null, engine = null, timer = null, restartTimer = null, updateTimer = null, playing = false, startToken = 0;
let bus = null, busAn = null;
let identity = "";   // preset|nomor versi|nada|suasana: kalau berubah, lagu dimulai ulang
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
const set = (o, path, v) => { const ks = path.split("."); let n = o; for (const k of ks.slice(0, -1)) n = n[k] ??= {}; n[ks[ks.length - 1]] = v; };
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
    set(state.raw, "form.type", $("#formtype").value || clone(DATA.presets[state.presetKey].form?.type ?? DATA.defaults.form.type));
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
  $("#copy").onclick = (e) => copyText($("#cmd").textContent, e.currentTarget);
  $("#judulTujuan").onchange = renderTitles;
  $("#judulBahasa").onchange = renderTitles;
  $("#judulDeskCopy").onclick = (e) => copyText($("#judulDesk").value, e.currentTarget);
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
  renderTitles();
  if (!playing) return;
  // nada dasar/suasana/preset/nomor versi mengubah isi lagu -> mulai ulang (crossfade).
  // Slider lain diterapkan langsung ke lagu yang sedang berjalan.
  const id = songIdentity(P);
  if (id !== identity) { clearTimeout(restartTimer); restartTimer = setTimeout(() => startEngine(true), 300); }
  else if (engine) { clearTimeout(updateTimer); updateTimer = setTimeout(() => engine?.update(current().P), 60); }
}

/** Judul & deskripsi YouTube untuk pengaturan yang sedang terdengar (versi 60 menit). */
function renderTitles() {
  if (!DATA?.judul) return;
  const r = resolve(state.raw, state.seed);
  r.duration_min = 60;
  const j = buatJudul(DATA.judul, r, { tujuan: $("#judulTujuan").value || null });
  const en = $("#judulBahasa").value === "en", list = (en ? j.judulEn : j.judulId).slice(0, 4);
  const ol = $("#judulList");
  ol.innerHTML = "";
  for (const t of list) {
    const li = document.createElement("li");
    const span = document.createElement("span"); span.textContent = t;
    const small = document.createElement("small"); small.textContent = `${t.length} karakter`; span.appendChild(small);
    const b = document.createElement("button"); b.className = "icon-btn quiet"; b.type = "button"; b.title = "Salin judul"; b.setAttribute("aria-label", "Salin judul");
    b.innerHTML = '<svg class="ic"><use href="#i-copy"/></svg>';
    b.onclick = () => copyText(t, b);
    li.append(span, b); ol.appendChild(li);
  }
  $("#judulDesk").value = (en ? j.deskripsiEn : j.deskripsiId) + "\n" + j.hashtag.join(" ");
  $("#judulTag").textContent = `Tujuan: ${j.tujuan} · Tag: ${j.tag.join(", ")}`;
}

function copyText(text, btn) {
  const done = () => { btn?.classList.add("copied"); setTimeout(() => btn?.classList.remove("copied"), 1200); };
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
  else fallbackCopy(text, done);
}

function fallbackCopy(text, done) {
  const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { /* tidak didukung */ }
  ta.remove();
}

function songIdentity(P) { return [state.presetKey, state.seed, P.tonic, P.mode].join("|"); }

function fileName() {
  const base = (state.raw.name || "spacenight").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return `${base}_s${state.seed}`;
}

// ---------- pemutaran ----------
async function togglePlay() {
  if (playing) {
    playing = false; startToken++;
    engine?.stop(); engine = null; clearInterval(timer); setPlayButton(false); return;
  }
  // iOS: semua langkah di bawah harus terjadi langsung di dalam ketukan tombol (sebelum await apa pun)
  unlockIOSAudio();
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    try { ctx = new AC({ sampleRate: SR, latencyHint: "playback" }); }
    catch (e) { ctx = new AC(); }   // sebagian iOS menolak sample rate yang diminta
    ctx.onstatechange = () => { if (playing && ctx.state !== "running") audioHint(); else audioHint(false); };
    bus = ctx.createGain(); bus.connect(ctx.destination);       // semua mesin lewat sini
    busAn = ctx.createAnalyser(); busAn.fftSize = 8192; bus.connect(busAn);
    window.__busAn = busAn;   // untuk pengujian otomatis: level keluaran sebenarnya
  }
  try { await ctx.resume(); } catch (e) { /* ditangani di bawah */ }
  playing = true; setPlayButton(true);
  setTimeout(() => { if (playing && ctx.state !== "running") audioHint(); }, 1200);
  startEngine(false);
}

// ---------- iPhone / iPad ----------
// Di iOS, Web Audio memakai kategori audio "ambient": dibisukan oleh tombol senyap di samping iPhone.
// Dua cara agar dianggap pemutar musik: navigator.audioSession (iOS 16.4+), dan untuk iOS lama
// sebuah elemen <audio> berisi keheningan yang diputar berulang di dalam ketukan tombol.
let silentEl = null;
function unlockIOSAudio() {
  try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) { /* tidak didukung */ }
  if (!silentEl) {
    silentEl = document.createElement("audio");
    silentEl.src = silentWavUrl();
    silentEl.loop = true;
    silentEl.setAttribute("playsinline", "");
    silentEl.setAttribute("aria-hidden", "true");
    silentEl.style.display = "none";
    document.body.appendChild(silentEl);
  }
  const p = silentEl.play();
  if (p && p.catch) p.catch(() => {});
}

function silentWavUrl() {   // WAV 0,5 detik berisi nol (16-bit mono 8 kHz)
  const n = 4000, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const w = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 8000, true); v.setUint32(28, 16000, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, n * 2, true);
  return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
}

/** Pesan kalau audio browser tidak berjalan (iOS bisa menghentikannya setelah telepon/kunci layar). */
function audioHint(show = true) {
  const el = $("#audiohint");
  if (!el) return;
  el.hidden = !show;
}

// iOS: kembali ke halaman / ketukan berikutnya -> coba lanjutkan audio yang terhenti
document.addEventListener("visibilitychange", () => { if (!document.hidden && playing && ctx && ctx.state !== "running") ctx.resume().catch(() => {}); });
document.addEventListener("touchend", () => {
  if (playing && ctx && ctx.state !== "running") { unlockIOSAudio(); ctx.resume().then(() => audioHint(false)).catch(() => {}); }
}, { passive: true });

function setPlayButton(on) {
  const b = $("#play");
  b.innerHTML = `<svg class="ic"><use href="#i-${on ? "stop" : "play"}"/></svg><span>${on ? "Berhenti" : "Putar"}</span>`;
  b.classList.toggle("on", on);
}

const agc = { hist: [], gainDb: 0, target: null, byPreset: {}, ticks: 0 };
const XFADE = 3;      // detik crossfade saat ganti preset/nada/nomor versi sambil memutar
const WARM = 24;      // lagu baru dimulai "panas": seolah sudah berjalan 24 detik

async function startEngine(crossfade) {
  // mesin baru disiapkan di latar (reverb dirender async); lagu lama tetap berbunyi sampai siap
  const token = ++startToken, { r, P } = current();
  const next = await Engine.create(ctx, P, state.seed, { total: null, destination: bus });
  if (token !== startToken || !playing) { next.stop(0.05); return; }
  // volume otomatis: pakai gain yang pernah dipelajari untuk preset ini, atau tebakan dari target
  const prevTarget = agc.target ?? r.master.target_lufs;
  agc.gainDb = agc.byPreset[state.presetKey] ?? agc.gainDb + (r.master.target_lufs - prevTarget);
  agc.target = r.master.target_lufs;
  next.masterGain.gain.value = 10 ** (agc.gainDb / 20);
  next.begin(crossfade ? WARM : 0);
  if (crossfade) { next.out.gain.value = 0; next.fadeIn(XFADE); }
  const old = engine;
  engine = next; identity = songIdentity(P);
  if (old) old.stop(XFADE);
  engine.scheduleUntil(engine.now() + 20);
  setupMeter();
  clearInterval(timer);
  timer = setInterval(tick, 250);
}

// meter loudness kira-kira (K-weighting didekati dengan biquad) + penyesuaian volume otomatis pelan
let meter = null;
function setupMeter() {
  if (meter) for (const n of meter.nodes) n.disconnect();   // lepas alat ukur mesin sebelumnya
  const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 38; hp.Q.value = 0.5;
  const sh = ctx.createBiquadFilter(); sh.type = "highshelf"; sh.frequency.value = 1500; sh.gain.value = 4;
  const sp = ctx.createChannelSplitter(2);
  const an = [ctx.createAnalyser(), ctx.createAnalyser()];
  an.forEach((a) => (a.fftSize = 16384));
  engine.meterTap.connect(hp).connect(sh).connect(sp);
  sp.connect(an[0], 0); sp.connect(an[1], 1);
  const viz = ctx.createAnalyser(); viz.fftSize = 4096; viz.smoothingTimeConstant = 0.85;
  engine.out.connect(viz);
  meter = { an, buf: new Float32Array(16384), viz, nodes: [hp, sh, sp, ...an, viz] };
  window.__meterViz = viz;   // untuk pengujian otomatis
  agc.hist = []; agc.ticks = 0;
}

function tick() {
  if (!engine) return;
  const t = engine.now();
  engine.scheduleUntil(t + 20);
  const { chord, intensity, section } = engine.info(t);
  $("#chord").textContent = chord || "–";
  $("#section").textContent = section ? describeSection(section) : "–";
  $("#intensity").style.width = `${Math.round(intensity * 100)}%`;
  const shown = Math.max(0, t - (engine.warm || 0));   // jam di layar dihitung sejak lagu ini terdengar
  const mm = Math.floor(shown / 60), ss = Math.floor(shown % 60);
  $("#time").textContent = `${mm}:${String(ss).padStart(2, "0")}`;
  // loudness: energi K-weighted rata-rata ~20 detik terakhir
  if (meter && t > 2) {
    let e = 0;
    for (const a of meter.an) { a.getFloatTimeDomainData(meter.buf); let s = 0; for (const v of meter.buf) s += v * v; e += s / meter.buf.length; }
    agc.hist.push(e); if (agc.hist.length > 80) agc.hist.shift();
    agc.ticks++;
    const mean = agc.hist.reduce((a, b) => a + b, 0) / agc.hist.length;
    const lufs = -0.691 + 10 * Math.log10(mean + 1e-12);     // sebelum gain master
    const target = current().r.master.target_lufs;
    if (agc.hist.length >= 8) {   // setelah ~2 s: arahkan gain master ke target (cepat dulu, lalu pelan)
      const want = Math.max(-24, Math.min(24, target - lufs)), step = agc.ticks < 40 ? 0.3 : 0.1;
      agc.gainDb += Math.max(-step, Math.min(step, want - agc.gainDb));
      engine.masterGain.gain.setTargetAtTime(10 ** (agc.gainDb / 20), ctx.currentTime, 0.5);
      if (agc.ticks > 40) agc.byPreset[state.presetKey] = agc.gainDb;
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
      const a = meter.viz, d = (meter.fd ??= new Float32Array(a.frequencyBinCount));
      a.getFloatFrequencyData(d);
      const cum = (meter.cum ??= new Float64Array(d.length + 1));   // jumlah kumulatif energi per bin
      for (let i = 0; i < d.length; i++) cum[i + 1] = cum[i] + 10 ** (d[i] / 10);
      g.beginPath();
      for (let x = 0; x <= w; x += 2) {
        // rata-rata energi dalam jendela 1/6 oktaf -> garis halus, bukan sisir harmonik
        const f = 30 * (16000 / 30) ** (x / w), bin = (SR / 2) / d.length;
        const i0 = Math.max(0, Math.floor((f * 2 ** (-1 / 12)) / bin)), i1 = Math.min(d.length - 1, Math.ceil((f * 2 ** (1 / 12)) / bin));
        const db = 10 * Math.log10((cum[i1 + 1] - cum[i0]) / (i1 - i0 + 1) + 1e-12);
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
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const oc = new OAC(2, Math.round(total * SR), SR);
  const eng = await Engine.create(oc, P, state.seed, { total, offline: true, start: 0 });
  eng.scheduleUntil(total);
  await Promise.all(eng.pending);   // tunggu nada piano selesai dirender sebelum mulai
  const step = Math.max(5, Math.floor(total / 40));
  for (let t = step; t < total; t += step) oc.suspend(t).then(() => { $("#progress").value = t / total; oc.resume(); });
  $("#status").textContent = "Me-render…";
  const t0 = performance.now();
  const buf = await oc.startRendering();
  $("#status").textContent = "Mastering…";
  await new Promise((res) => setTimeout(res, 20));
  const ch = [buf.getChannelData(0), buf.getChannelData(1)];
  // fade-out di akhir lagu, sama dengan pipeline Python: 30 detik (atau 1/4 durasi untuk lagu pendek)
  const nFade = Math.floor(Math.min(30, total / 4) * SR), nAll = ch[0].length;
  for (const x of ch) for (let i = nAll - nFade; i < nAll; i++) { const k = (nAll - i) / nFade; x[i] *= k * k; }
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
