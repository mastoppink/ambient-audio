// Judul, deskripsi, chapter & tag YouTube yang sesuai audio (port dari ambient-gen/judul.py).
// Kosakata sama (judul_kata.json, ikut di presets.json). Studio belum punya laporan QC, jadi kecerahan
// diambil dari pengaturan pad; versi Python memakai kecerahan terukur dari audio yang sudah jadi.
import { rngFor, Sections } from "./music.js";

const MAX_LEN = 100;

export function durasiLabel(menit) {
  const m = Math.round(menit);
  if (m >= 60 && m % 60 === 0) { const j = m / 60; return [`${j} Hour${j > 1 ? "s" : ""}`, `${j} Jam`]; }
  return [`${m} Minutes`, `${m} Menit`];
}

function ciri(r) {
  const melOn = (r.mix.melody ?? 0) > 0, b = Number(r.pad.brightness);
  return {
    mode: String(r.key.mode).toLowerCase(), timbre: melOn ? r.melody.timbre : "-", menit: Number(r.duration_min ?? 60),
    terang: b > 0.58 ? "terang" : b < 0.4 ? "gelap" : "netral", profil: r.qc?.profile ?? "default",
    bentuk: r.form.type, fungsi: r.fungsi ?? "", tonic: r.key.tonic, lufs: r.master.target_lufs, density: r.melody.density,
  };
}

export function tebakTujuan(c) {
  if (["tidur", "meditasi", "fokus", "santai"].includes(c.fungsi)) return c.fungsi;   // kategori dari preset
  if (c.profil === "sleep" || c.lufs <= -16) return "tidur";
  if (c.timbre === "-") return "meditasi";
  if (c.profil === "calm") return c.mode !== "phrygian" ? "santai" : "fokus";
  if (c.density > 0.75) return "belajar";
  return ["dorian", "phrygian", "mixolydian"].includes(c.mode) ? "fokus" : "santai";
}

const fill = (tpl, d) => {
  let t = tpl.replace(/\{(\w+)\}/g, (_, k) => d[k]);
  if (t.length > MAX_LEN) t = t.replace(` (${d.durasi})`, "");
  return t.replace(/\s+/g, " ").trim();
};

/** @returns {{tujuan, judulEn, judulId, deskripsiEn, deskripsiId, chapter, tag, hashtag}} */
export function buatJudul(K, r, { tujuan = null, n = 5 } = {}) {
  const seed = Number(r.seed) || 0, rng = rngFor(seed, "judul"), c = ciri(r);
  tujuan = tujuan || tebakTujuan(c);
  const T = K.tujuan[tujuan], [durEn, durId] = durasiLabel(c.menit);
  const mood = K.mode[c.mode] || K.mode.lydian, cit = K.citra[c.terang], mel = K.melodi[c.timbre];
  const pick = (a) => a[Math.floor(rng() * a.length)];
  const aman = (t) => t.length <= MAX_LEN && K.terlarang.every((w) => !t.toLowerCase().includes(w));
  const kandidat = (lang) => {
    const out = [], used = new Set(), tpls = K.templat[lang];
    for (let it = 0; it < 120 && out.length < tpls.length + 2; it++) {   // semua pola dicoba dulu
      const ti = Math.floor(rng() * tpls.length);
      if (used.has(ti) && used.size < tpls.length) continue;      // tiap pola dipakai sekali dulu
      const citra = pick(cit[lang]);
      if (tpls[ti].includes("{mood} {citra}") && citra.split(" ").length > 1) continue;
      if (tpls[ti].includes("Cosmic Drones") && c.timbre === "-") continue;
      if (tpls[ti].includes("Calm Nights") && !["tidur", "santai", "meditasi"].includes(tujuan)) continue;
      const m = [...mood[lang]].sort(() => rng() - 0.5);
      const ext = c.terang === "netral" ? [] : K[c.terang === "terang" ? "terang" : "gelap"][lang];
      const d = { citra, mood: m[0], mood2: ext.length ? pick(ext) : m[1 % m.length], melodi: mel[lang], tujuan: pick(T[lang]),
        verb: T.verb_en, durasi: lang === "en" ? durEn : durId };
      const kc = new Set(citra.toLowerCase().split(" "));
      if (kc.has(d.mood.toLowerCase()) || kc.has(d.mood2.toLowerCase()) || d.mood === d.mood2) continue;
      let t = fill(tpls[ti], d);
      if (lang === "id") t = t.replace("yang " + d.mood, "yang " + d.mood.toLowerCase());
      if (aman(t) && !out.includes(t)) { out.push(t); used.add(ti); }
    }
    return out.sort((a, b) => Math.abs(a.length - 88) - Math.abs(b.length - 88)).slice(0, n);   // panjang & deskriptif, <= 100
  };
  const judulEn = kandidat("en"), judulId = kandidat("id");
  // chapter dari babak (sama seperti mesin audio: Sections dengan seed & variasi yang sama)
  const total = c.menit * 60, chapter = [];
  const variation = r.variation?.amount ?? 0;
  if (variation > 0 && total >= 600) {
    const sec = new Sections(seed, variation, (r.mix.melody ?? 0) > 0, total);
    const starts = sec.list.map((s) => s.start).filter((s) => s < total - 60);
    if (starts.length >= 3) {
      const rest = K.babak.en.map((_, i) => i).slice(1).sort(() => rng() - 0.5);
      const jam = Math.max(...starts) >= 3600;
      starts.forEach((st, i) => {
        const j = i === 0 ? 0 : rest[(i - 1) % rest.length];
        const h = Math.floor(st / 3600), mm = Math.floor((st % 3600) / 60), ss = Math.floor(st % 60);
        // YouTube: chapter pertama harus 0:00; lagu panjang: nama dipakai lagi dengan "II", "III"
        const ts = i === 0 ? "0:00" : jam ? `${h}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}` : `${mm}:${String(ss).padStart(2, "0")}`;
        const akhir = ["", " II", " III", " IV"][Math.min(i ? Math.floor((i - 1) / rest.length) : 0, 3)];
        chapter.push([ts, K.babak.en[j] + akhir, K.babak.id[j] + akhir]);
      });
    }
  }
  const bentuk = K.bentuk[c.bentuk] || K.bentuk.arc, kunci = `${c.tonic} ${c.mode}`;
  const frasa = { glass: "glass bells", kalimba: "kalimba notes", piano: "soft piano notes", soft: "soft tones" };
  const melEn = c.timbre !== "-" ? `Sparse ${frasa[c.timbre] || "notes"} drift above slow pads and deep drones`
    : "Slow pads and deep drones with no melody, so nothing pulls your attention";
  const melId = c.timbre !== "-" ? `${mel.id.charAt(0).toUpperCase()}${mel.id.slice(1)} sesekali terdengar di atas pad yang pelan dan dengung yang dalam`
    : "Pad yang pelan dan dengung yang dalam tanpa melodi, sehingga tidak ada yang menarik perhatian";
  const tidur = c.lufs <= -16;
  const deskripsiEn = `${durEn} of ${mood.en[0].toLowerCase()} space ambient for ${T.en[0].toLowerCase()}. ${melEn}. `
    + `The music is ${bentuk.en}, in ${kunci}, mastered ${tidur ? "kept quieter for sleep" : "at a steady volume"} with no sudden changes.\n\n`
    + "Made with original synthesizers and a generative process. No samples or stock music.\n"
    + (chapter.length ? `\nChapters\n${chapter.map(([t, e]) => `${t} ${e}`).join("\n")}\n` : "");
  const deskripsiId = `${durId} musik ambient luar angkasa yang ${mood.id[0].toLowerCase()} untuk ${T.id[0].toLowerCase()}. ${melId}. `
    + `Musiknya ${bentuk.id}, dalam nada ${kunci}, ${tidur ? "dibuat lebih pelan untuk tidur" : "dengan volume yang stabil"} tanpa perubahan mendadak.\n\n`
    + "Dibuat dengan synth dan proses generatif buatan sendiri, tanpa sampel atau musik orang lain.\n"
    + (chapter.length ? `\nBabak\n${chapter.map(([t, , i]) => `${t} ${i}`).join("\n")}\n` : "");
  const tagT = { tidur: ["sleep music", "#sleepmusic"], fokus: ["focus music", "#focusmusic"], belajar: ["study music", "#studymusic"],
    santai: ["relaxing music", "#relaxingmusic"], meditasi: ["meditation music", "#meditationmusic"] }[tujuan];
  const tag = ["ambient", "space ambient", "ambient music", tagT[0], mel.en.toLowerCase(), "space music", "calm music", `${durEn.toLowerCase()} ambient`];
  return { tujuan, judulEn, judulId, deskripsiEn, deskripsiId, chapter, tag, hashtag: ["#ambient", "#spacemusic", tagT[1]] };
}
