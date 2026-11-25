// The link with a structural model of the raft (CSI SAFE): soil and structure
// are solved in turn until they agree.
//
//   1. SAFE analyses the raft on springs and exports its soil pressures.
//   2. Here those pressures become the load on the ground, the settlement under
//      every part of the raft is worked out, and the spring each part needs is
//      k = pressure / settlement (the modulus of subgrade reaction).
//   3. SAFE runs again with those springs. The pressures shift towards the
//      stiffer parts, so the springs change a little; repeat until they do not.
//
// Units inside: m, kPa, kN. A subgrade modulus is in kN/m³.

import { computePoint, settlementAt, prepare, gridSubLayers } from "./settlement.js";
import { fieldCells } from "./stress.js";

// ---------------------------------------------------------------- reading tables

/** Rows of text cells from pasted or CSV text (tabs, commas or semicolons). */
export function parseDelimited(text) {
  const lines = String(text || "").replace(/\r/g, "").split("\n").filter((l) => l.trim() !== "");
  if (!lines.length) return [];
  const count = (ch) => lines.slice(0, 8).reduce((a, l) => a + l.split(ch).length - 1, 0);
  const sep = count("\t") > 0 ? "\t" : count(";") > count(",") ? ";" : ",";
  return lines.map((line) => {
    const out = [];
    let cur = "", quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (quoted) { if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') quoted = false; else cur += ch; }
      else if (ch === '"') quoted = true;
      else if (ch === sep) { out.push(cur.trim()); cur = ""; }
      else cur += ch;
    }
    out.push(cur.trim());
    return out;
  });
}

const COLS = {
  x: /^(global\s*)?x(\s*(coord\w*|ord\w*))?$|^globalx$|^x\s*\(/i,
  y: /^(global\s*)?y(\s*(coord\w*|ord\w*))?$|^globaly$|^y\s*\(/i,
  p: /press|soil\s*stress|bearing/i,
  fz: /^f\s*z\b|^fz|^p\s*z$|reaction.*z|vertical\s*(force|reaction)/i,
  kase: /output\s*case|outputcase|load\s*(case|combo)|^case$|^combo/i,
  step: /step\s*type|steptype/i,
  joint: /^(joint|point|node)(\s*(label|id|name|object))?$|^unique\s*name$|^uniquename$/i,
};
const find = (headers, re) => headers.findIndex((h) => re.test(String(h).trim()));
const isNum = (v) => v !== "" && v !== null && v !== undefined && Number.isFinite(+String(v).replace(/,/g, ""));
const toNum = (v) => +String(v).replace(/,/g, "");

/** Where the header row is and which columns matter. */
export function locate(rows) {
  for (let r = 0; r < Math.min(rows.length, 12); r++) {
    const h = rows[r].map((c) => String(c ?? "").trim());
    if (h.filter(Boolean).length < 3) continue; // a title line, not the headings
    const c = Object.fromEntries(Object.entries(COLS).map(([k, re]) => [k, find(h, re)]));
    if (c.p >= 0 || c.fz >= 0 || (c.x >= 0 && c.y >= 0)) return { row: r, headers: h, cols: c };
  }
  return null;
}

// What one unit is in metres or kPa (or kN for forces).
const LENGTH = [[/^mm$/i, 0.001], [/^cm$/i, 0.01], [/^m$/i, 1], [/^(ft|feet)$/i, 0.3048], [/^(in|inch(es)?)$/i, 0.0254]];
const PRESSURE = [
  [/^kn\/m(²|2|\^2)$|^kpa$/i, 1], [/^n\/mm(²|2|\^2)$|^mpa$/i, 1000], [/^n\/m(²|2|\^2)$|^pa$/i, 0.001], [/^kn\/mm(²|2|\^2)$/i, 1e6], [/^kn\/cm(²|2|\^2)$/i, 1e4], [/^n\/cm(²|2|\^2)$/i, 10],
  [/^kgf\/cm(²|2|\^2)$/i, 98.0665], [/^kgf\/m(²|2|\^2)$/i, 0.00980665], [/^tonf\/m(²|2|\^2)$/i, 9.80665], [/^kgf\/mm(²|2|\^2)$/i, 9806.65],
  [/^(lb|lbf)\/ft(²|2|\^2)$|^psf$/i, 0.04788026], [/^kip\/ft(²|2|\^2)$|^ksf$/i, 47.88026], [/^(lb|lbf)\/in(²|2|\^2)$|^psi$/i, 6.894757], [/^kip\/in(²|2|\^2)$|^ksi$/i, 6894.757],
];
const FORCE = [[/^kn$/i, 1], [/^n$/i, 0.001], [/^kgf$/i, 0.00980665], [/^tonf$/i, 9.80665], [/^(lb|lbf)$/i, 0.004448222], [/^kip$/i, 4.448222]];
const unitOf = (table, text) => { const t = String(text ?? "").trim().replace(/\s+/g, ""); const hit = table.find(([re]) => re.test(t)); return hit ? hit[1] : null; };

/** The unit systems offered when the table does not say: [key, name, length, pressure, force, k name, kN/m³ per unit]. */
export const UNIT_SYSTEMS = [
  ["kN-m", "kN, m", 1, 1, 1, "kN/m³", 1],
  ["N-mm", "N, mm", 0.001, 1000, 0.001, "N/mm³", 1e6],
  ["kN-mm", "kN, mm", 0.001, 1e6, 1, "kN/mm³", 1e9],
  ["kgf-m", "kgf, m", 1, 0.00980665, 0.00980665, "kgf/m³", 0.00980665],
  ["kgf-cm", "kgf, cm", 0.01, 98.0665, 0.00980665, "kgf/cm³", 9806.65],
  ["tonf-m", "tonf, m", 1, 9.80665, 9.80665, "tonf/m³", 9.80665],
  ["kip-ft", "kip, ft", 0.3048, 47.88026, 4.448222, "kip/ft³", 157.0875],
  ["kip-in", "kip, in", 0.0254, 6894.757, 4.448222, "kip/in³", 271447.1],
  ["lb-ft", "lb, ft", 0.3048, 0.04788026, 0.004448222, "lb/ft³", 0.1570875],
  ["lb-in", "lb, in", 0.0254, 6.894757, 0.004448222, "lb/in³", 271.4471],
];
export const unitSystem = (key) => UNIT_SYSTEMS.find((u) => u[0] === key) || UNIT_SYSTEMS[0];

/**
 * Soil pressures (or support reactions) at points, from one or more tables.
 * `tables` is [{ name, rows }]; text pasted from Excel is one table.
 * Returns { points: [{x, y, p} or {x, y, f}], kind, cases, kase, steps, step, units, table, notes }.
 * Pressures come back positive when they press on the ground.
 */
export function readSafe(tables, opts = {}) {
  const list = (Array.isArray(tables) ? tables : [{ name: "pasted", rows: parseDelimited(tables) }]).map((t) => ({ ...t, at: locate(t.rows) })).filter((t) => t.at);
  const notes = [];
  const main = list.find((t) => t.at.cols.p >= 0) || list.find((t) => t.at.cols.fz >= 0);
  if (!main) {
    const seen = (Array.isArray(tables) ? tables : []).map((t) => `${t.name}: ${(t.rows.find((r) => r.filter((c) => c !== "").length > 2) || []).filter((c) => c !== "").slice(0, 8).join(", ")}`).join(" | ");
    throw new Error(`no column of soil pressures or vertical reactions was found. Export SAFE's Soil Pressures table (or the support reactions), with its headings.${seen ? ` Found: ${seen}` : ""}`);
  }
  const { row, headers, cols } = main.at;
  const kind = cols.p >= 0 ? "pressure" : "force";
  const vcol = kind === "pressure" ? cols.p : cols.fz;
  const body = main.rows.slice(row + 1);
  // a units row right under the headings, as SAFE writes it
  const first = body[0] || [], hasUnits = !isNum(first[vcol]) && first.some((c) => String(c).trim() !== "");
  const sys = unitSystem(opts.units);
  let fl = sys[2], fv = kind === "pressure" ? sys[3] : sys[4], said = false;
  if (hasUnits) {
    const uv = unitOf(kind === "pressure" ? PRESSURE : FORCE, first[vcol]), ul = cols.x >= 0 ? unitOf(LENGTH, first[cols.x]) : null;
    if (uv !== null) { fv = uv; said = true; }
    if (ul !== null) fl = ul;
  }
  // coordinates: in this table, or in another one that lists the joints
  let coords = null;
  if (cols.x < 0 || cols.y < 0) {
    const jt = list.find((t) => t !== main && t.at.cols.joint >= 0 && t.at.cols.x >= 0 && t.at.cols.y >= 0);
    if (!jt || cols.joint < 0) throw new Error(`the ${kind === "pressure" ? "soil pressures" : "reactions"} table has no X and Y columns, and no table of joint coordinates came with it. Its headings are: ${headers.filter(Boolean).join(", ")}`);
    const jb = jt.rows.slice(jt.at.row + 1), ju = jb[0] || [];
    const jl = !isNum(ju[jt.at.cols.x]) ? unitOf(LENGTH, ju[jt.at.cols.x]) : null;
    coords = new Map();
    for (const r of jb) if (isNum(r[jt.at.cols.x]) && isNum(r[jt.at.cols.y])) coords.set(String(r[jt.at.cols.joint]).trim(), [toNum(r[jt.at.cols.x]) * (jl ?? fl), toNum(r[jt.at.cols.y]) * (jl ?? fl)]);
    notes.push(`Coordinates taken from the table "${jt.name}".`);
  }
  const rowsNum = body.filter((r) => isNum(r[vcol]));
  const uniq = (c) => (c >= 0 ? [...new Set(rowsNum.map((r) => String(r[c] ?? "").trim()).filter(Boolean))] : []);
  const cases = uniq(cols.kase), steps = uniq(cols.step);
  const kase = cases.includes(opts.kase) ? opts.kase : cases[0] ?? null;
  const step = steps.includes(opts.step) ? opts.step : steps[0] ?? null;
  // the same joint is listed once for every element that meets at it: average them
  const at = new Map();
  let skipped = 0;
  for (const r of rowsNum) {
    if (kase !== null && String(r[cols.kase] ?? "").trim() !== kase) continue;
    if (step !== null && String(r[cols.step] ?? "").trim() !== step) continue;
    let xy;
    if (coords) xy = coords.get(String(r[cols.joint]).trim());
    else if (isNum(r[cols.x]) && isNum(r[cols.y])) xy = [toNum(r[cols.x]) * fl, toNum(r[cols.y]) * fl];
    if (!xy) { skipped++; continue; }
    const key = `${xy[0].toFixed(4)},${xy[1].toFixed(4)}`, v = toNum(r[vcol]) * fv;
    const a = at.get(key) || { x: xy[0], y: xy[1], sum: 0, n: 0 };
    a.sum += v; a.n++;
    at.set(key, a);
  }
  if (skipped) notes.push(`${skipped} rows had no coordinates and were left out.`);
  let pts = [...at.values()].map((a) => ({ x: a.x, y: a.y, v: kind === "pressure" ? a.sum / a.n : a.sum / a.n }));
  if (!pts.length) throw new Error("the table has headings but no rows of numbers for this load case.");
  // SAFE writes compression as negative: turn the table so that pressing down is positive
  const total = pts.reduce((s, q) => s + q.v, 0);
  if (total < 0) { pts = pts.map((q) => ({ ...q, v: -q.v })); notes.push("Pressures were negative for compression, as SAFE writes them; they are taken as pressing down."); }
  const lifted = pts.filter((q) => q.v < 0).length;
  if (lifted) notes.push(`${lifted} points are in tension (the raft lifts off there); they are taken as carrying nothing.`);
  return {
    points: pts.map((q) => (kind === "pressure" ? { x: q.x, y: q.y, p: Math.max(0, q.v) } : { x: q.x, y: q.y, f: Math.max(0, q.v) })),
    kind, cases, kase, steps, step, table: main.name, notes,
    units: said ? "from the table" : sys[1],
  };
}

// ---------------------------------------------------------------- pressures to cells

/**
 * The points gathered into square cells, few enough to solve quickly.
 * Returns { cells: [[x, y, q, p], ...], size, force, area }: q is the cell's
 * load over its whole square (what the ground feels), p the mean contact
 * pressure of its points (what a spring there carries). They differ at the
 * raft's edges, where the raft covers only part of a cell.
 */
export function toCells(points, kind = "pressure", maxCells = 300) {
  if (!points.length) return { cells: [], size: 1, force: 0, area: 0 };
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const x1 = Math.min(...xs), y1 = Math.min(...ys), w = Math.max(...xs) - x1, h = Math.max(...ys) - y1;
  // start a little above the points' own spacing and coarsen until there are few enough cells
  // The points' own spacing (exact for a regular mesh), then whole multiples of it
  // until there are few enough cells: a regular mesh then falls evenly into the cells.
  const n1 = Math.sqrt(points.length);
  const d = Math.max(w > 1e-9 && h > 1e-9 && n1 > 1.5 ? Math.sqrt(w * h) / (n1 - 1) : Math.max(w, h) / Math.max(1, points.length - 1), Math.max(w, h) / 2000, 1e-3);
  for (let m = 1; ; m++) {
    const size = d * m;
    const cells = new Map();
    // the first row and column of points sit in the middle of the first cells
    for (const p of points) {
      const i = Math.round((p.x - x1) / size), j = Math.round((p.y - y1) / size), key = `${i},${j}`;
      const c = cells.get(key) || { i, j, sum: 0, n: 0 };
      c.sum += kind === "pressure" ? p.p : p.f; c.n++;
      cells.set(key, c);
    }
    if (cells.size > maxCells) continue;
    const list = [...cells.values()], full = size * size;
    if (kind !== "pressure") {
      const out = list.map((c) => [x1 + c.i * size, y1 + c.j * size, c.sum / full, c.sum / full]);
      return { cells: out, size, force: list.reduce((a, c) => a + c.sum, 0), area: list.length * full };
    }
    // The area one point stands for, from the cells in the middle of the raft; a
    // point on the raft's edge stands for half of that, which the last factor allows for.
    const has = (i, j) => cells.has(`${i},${j}`);
    const sides = (c) => [has(c.i - 1, c.j), has(c.i + 1, c.j), has(c.i, c.j - 1), has(c.i, c.j + 1)].filter(Boolean).length;
    const inner = list.filter((c) => sides(c) === 4);
    const each = inner.length ? (inner.length * full) / inner.reduce((a, c) => a + c.n, 0) : Math.min(full, d * d);
    const exposed = list.reduce((a, c) => a + 4 - sides(c), 0) * size;
    const edge = Math.max(0.5, 1 - (exposed * Math.sqrt(each)) / 2 / (points.length * each));
    const out = list.map((c) => { const p = c.sum / c.n; return [x1 + c.i * size, y1 + c.j * size, (p * c.n * each * edge) / full, p]; });
    return { cells: out, size, force: out.reduce((a, c) => a + c[2], 0) * full, area: points.length * each * edge };
  }
}

// ---------------------------------------------------------------- springs

/**
 * The spring every cell of a pressure field needs at time t:
 * [{x, y, p, q, s, k}] with s in m and k = p / s in kN/m³ (p is the contact
 * pressure, q the cell's load over its square). A cell that carries
 * nothing, or sits on ground that does not settle, gets no spring (k null).
 */
export function springs(project, load, t, opts = {}) {
  const stages = opts.stages || prepare(project), subLayers = opts.subLayers || gridSubLayers(project);
  return fieldCells(load).map(([x, y, q, pc]) => {
    const s = settlementAt(computePoint(project, x, y, { stages, subLayers }), t).total;
    const p = Number.isFinite(pc) ? pc : q;
    return { x, y, p, q, s, k: p > 0 && s > 1e-5 ? p / s : null };
  });
}

/** How far the springs moved since the last round: the mean and the largest change, as fractions. */
export function compare(now, before) {
  if (!before || !before.length) return null;
  let sum = 0, weight = 0, max = 0, n = 0;
  for (const a of now) {
    if (a.k === null) continue;
    // the nearest cell of the round before (the mesh, and so the cells, can differ a little)
    let best = null, bd = Infinity;
    for (const b of before) { const d = (a.x - b[0]) ** 2 + (a.y - b[1]) ** 2; if (d < bd) { bd = d; best = b; } }
    if (!best || !(best[2] > 0)) continue;
    const ch = Math.abs(a.k - best[2]) / best[2];
    sum += ch * a.p; weight += a.p; max = Math.max(max, ch); n++;
  }
  return n ? { mean: weight > 0 ? sum / weight : 0, max, n } : null;
}

/**
 * Springs gathered into a few bands, because SAFE takes a subgrade modulus per
 * soil property and a property per area. Returns { zones: [{name, k, from, to, n}], of: [zone index per spring] }.
 */
export function zonesOf(list, count = 5) {
  const ks = list.filter((s) => s.k !== null).map((s) => s.k).sort((a, b) => a - b);
  if (!ks.length) return { zones: [], of: list.map(() => -1) };
  const lo = ks[0], hi = ks[ks.length - 1], n = hi - lo < 1e-9 * hi ? 1 : Math.max(1, Math.min(12, Math.round(count)));
  // equal steps of log k: each band then holds springs within the same ratio of each other
  const band = (k) => (n === 1 ? 0 : Math.min(n - 1, Math.floor((Math.log(k / lo) / Math.log(hi / lo)) * n)));
  const zones = Array.from({ length: n }, (_, i) => ({ name: `GPM-K${i + 1}`, from: lo * (hi / lo) ** (i / n), to: lo * (hi / lo) ** ((i + 1) / n), sum: 0, n: 0 }));
  const softest = band(lo);
  const of = list.map((s) => { const z = s.k === null ? softest : band(s.k); if (s.k !== null) { zones[z].sum += s.k; zones[z].n++; } return z; });
  for (const z of zones) { z.k = z.n ? z.sum / z.n : Math.sqrt(z.from * z.to); delete z.sum; }
  return { zones, of };
}

/** One round of the loop, ready to keep in the project and to show. */
export function round(project, load, t, before, opts = {}) {
  const list = springs(project, load, t, opts);
  const live = list.filter((s) => s.k !== null);
  const change = compare(list, before);
  const tol = opts.tol || 0.05;
  return {
    list, change,
    summary: {
      cells: list.length, force: list.reduce((a, s) => a + s.q, 0) * (+load.size || 0) ** 2,
      sMax: Math.max(0, ...list.map((s) => s.s)), sMin: list.length ? Math.min(...list.map((s) => s.s)) : 0,
      kMin: live.length ? Math.min(...live.map((s) => s.k)) : 0, kMax: live.length ? Math.max(...live.map((s) => s.k)) : 0,
      kMean: live.length ? live.reduce((a, s) => a + s.k * s.p, 0) / live.reduce((a, s) => a + s.p, 0) : 0,
      mean: change ? change.mean : null, max: change ? change.max : null,
      converged: !!change && change.mean <= tol && change.max <= 3 * tol,
    },
  };
}

// ---------------------------------------------------------------- tables for SAFE

const q = (v) => (typeof v === "string" ? (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v) : Number.isFinite(v) ? String(+v.toPrecision(6)) : "");
const csv = (rows) => rows.map((r) => r.map(q).join(",")).join("\r\n");

/** The soil properties to define in SAFE, and where each one goes, in the unit system asked for. */
export function exportTables(list, size, zoning, unitsKey = "kN-m") {
  const u = unitSystem(unitsKey), L = 1 / u[2], P = 1 / u[3], K = 1 / u[6], lu = u[1].split(", ")[1], pu = u[5].replace(/³$/, "²");
  const props = csv([["Soil subgrade properties for SAFE (Define > Soil Subgrade Properties)"], ["Property", `Subgrade modulus (${u[5]})`, `From (${u[5]})`, `To (${u[5]})`, "Cells"],
    ...zoning.zones.map((z) => [z.name, z.k * K, z.from * K, z.to * K, z.n])]);
  const cells = csv([["Where each property goes (Assign > Support Data > Soil Properties), and the spring at every cell"],
    [`X (${lu})`, `Y (${lu})`, `Cell size (${lu})`, `Soil pressure (${pu})`, "Settlement (mm)", `Subgrade modulus (${u[5]})`, "Property"],
    ...list.map((s, i) => [s.x * L, s.y * L, size * L, s.p * P, s.s * 1000, s.k === null ? "" : s.k * K, zoning.zones[zoning.of[i]]?.name || ""])]);
  return { props, cells };
}
