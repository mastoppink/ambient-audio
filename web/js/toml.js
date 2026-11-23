// Penulis TOML minimal (cukup untuk preset), sama seperti settings.to_toml di Python.
function val(v) {
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return JSON.stringify(v);
  if (typeof v === "number") return Number.isInteger(v) ? `${v}` : `${Math.round(v * 1e4) / 1e4}`;
  if (Array.isArray(v)) return `[${v.map(val).join(", ")}]`;
  if (v && typeof v === "object") return `{ ${Object.entries(v).map(([k, x]) => `${k} = ${val(x)}`).join(", ")} }`;
  return String(v);
}

export function toToml(d, prefix = "") {
  const lines = [], tables = [];
  for (const [k, v] of Object.entries(d)) {
    if (v && typeof v === "object" && !Array.isArray(v) && k !== "chord_weights") tables.push([k, v]);
    else lines.push(`${k} = ${val(v)}`);
  }
  for (const [k, v] of tables) {
    lines.push("", `[${prefix}${k}]`);
    lines.push(toToml(v, `${prefix}${k}.`).trim());
  }
  return lines.join("\n") + "\n";
}
