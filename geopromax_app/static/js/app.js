// GeoProMax: the page. Inputs on the left; the plan or the section, the time
// bar, the headline numbers and the detail tabs on the right. Every result is
// worked out in the browser: the query point on this thread (it is quick), the
// plan grid and the section in a worker.

import { PRESETS, PRESET_GROUPS, LOAD_TYPES, LOAD_NAMES, STRUCTURES, structureOf, bearingLimit, layerFrom, loadFrom, padGrid, complete, checks, resultChecks, depthOf, describeLoad, TEMPLATES } from "../engine/project.js";
import { solvePoint, settlementAt, timeCurve, timeTo, initialStress, foundationResults, summarize, betweenFoundations, gridSubLayers, prepare } from "../engine/settlement.js";
import { extents, grossPressure, appliedPressure, foundingDepth, loadForce, loadCentre, equivalentRaft, parsePoints } from "../engine/stress.js";
import { runChecks } from "../engine/verify.js";
import { bearingAll } from "../engine/bearing.js";
import { readSafe, toCells, round as safeRound, springs, zonesOf, exportTables, parseDelimited, UNIT_SYSTEMS, unitSystem } from "../engine/ssi.js";
import { readXlsx } from "../engine/xlsx.js";
import { drawPlan, sample, rampCSS } from "./plan.js";
import { timeChart, depthChart, sectionView, soilColour, esc } from "./charts.js";

const G = window.__GEOPROMAX || { api: "api", base: "./", static: "static/", openId: null };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const fmt = (v, d = 1) => (Number.isFinite(v) ? (+v.toFixed(d)).toLocaleString(undefined, { maximumFractionDigits: d }) : "–");
const mm = (m, d = 0) => fmt(m * 1000, d);
const yrs = (t) => (!Number.isFinite(t) ? "–" : t < 1 / 12 ? `${fmt(t * 365, 0)} days` : t < 1 ? `${fmt(t * 12, 1)} months` : `${fmt(t, t < 10 ? 1 : 0)} year${t === 1 ? "" : "s"}`);

const state = {
  project: null, id: null, version: null, offline: false, dirty: false,
  res: null, grid: null, gridAsk: 0, view: "plan", tab: "found", depthMode: "stress",
  verify: null, playing: false, snap: null, found: null, summaryNow: [], summaryLife: [],
  gridForm: { nx: 4, ny: 3, sx: 6, sy: 6, B: 2.5, P: 1500, Df: 1.5 },
};

// ------------------------------------------------------------------ helpers

function get(obj, path) { return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj); }
function set(obj, path, v) {
  const ks = path.split(".");
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) { if (o[ks[i]] == null || typeof o[ks[i]] !== "object") o[ks[i]] = {}; o = o[ks[i]]; }
  o[ks[ks.length - 1]] = v;
}

let toastTimer;
function toast(text, bad) {
  const t = $(".toast");
  t.textContent = text;
  t.classList.toggle("error", !!bad);
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), bad ? 6000 : 2600);
}

// theme switch, shared with the rest of the site
(() => {
  const LABELS = { system: "Auto", light: "Light", dark: "Dark" }, NEXT = { system: "light", light: "dark", dark: "system" };
  const cur = () => { try { return localStorage.getItem("pm-theme") || "system"; } catch (e) { return "system"; } };
  const apply = (t) => {
    if (t === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
    const b = $("[data-theme-toggle]"); if (b) b.textContent = LABELS[t];
  };
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest("[data-theme-toggle]")) return;
    const t = NEXT[cur()] || "light";
    try { localStorage.setItem("pm-theme", t); } catch (e) { /* private mode */ }
    apply(t);
    renderView(); renderPanel();
  });
  apply(cur());
})();

// ------------------------------------------------------------------ the inputs

const ICONS = {
  layers: '<path d="M2 5h16M2 10h16M2 15h16" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
  water: '<path d="M10 3 C7 8 5 10 5 12.5a5 5 0 0010 0C15 10 13 8 10 3z" stroke="currentColor" stroke-width="1.6" fill="none"/>',
  load: '<path d="M4 4h12M6 4v7M10 4v7M14 4v7M4 11l2 3 2-3M8 11l2 3 2-3M12 11l2 3 2-3M2 16h16" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  calc: '<path d="M3 16 L8 9 L12 12 L17 4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  limit: '<path d="M3 5h14M3 15h14M10 5v10M7 8l3-3 3 3M7 12l3 3 3-3" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  link: '<path d="M8 12l4-4M6.5 9.5l-2 2a2.8 2.8 0 004 4l2-2M13.5 10.5l2-2a2.8 2.8 0 00-4-4l-2 2" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
  point: '<circle cx="10" cy="9" r="3" stroke="currentColor" stroke-width="1.6" fill="none"/><path d="M10 12v6" stroke="currentColor" stroke-width="1.6"/>',
};
const icon = (k) => `<svg class="icon" viewBox="0 0 20 20" aria-hidden="true">${ICONS[k] || ""}</svg>`;
const SVG = {
  up: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 10l4-4 4 4"/></svg>',
  down: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 6l4 4 4-4"/></svg>',
  copy: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="5" y="5" width="8" height="8" rx="1.5"/><path d="M3 10V4a1 1 0 011-1h6"/></svg>',
  del: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
};

/** A number field: label (with a hint below it), the box and its unit. */
function num(k, label, unit, o = {}) {
  const v = get(state.project, k);
  const val = v === null || v === undefined ? "" : v;
  const sub = typeof o.sub === "function" ? o.sub(state.project) : o.sub;
  return `<div class="f"><span class="lab">${label}${sub ? `<small data-sub="${k}">${esc(sub)}</small>` : ""}</span><span class="num"><input type="number" inputmode="decimal" data-k="${k}" value="${val}" step="${o.step ?? "any"}" ${o.min !== undefined ? `min="${o.min}"` : ""} ${o.max !== undefined ? `max="${o.max}"` : ""} ${o.blank ? `placeholder="${o.ph || "auto"}"` : ""} aria-label="${esc(label.replace(/<[^>]+>/g, ""))}"><span class="unit">${esc(unit || "")}</span></span>${o.picks ? `<div class="picks" style="grid-column:1/-1">${o.picks.map((p) => `<button type="button" data-pick="${k}" data-v="${p}">${p}</button>`).join("")}</div>` : ""}</div>`;
}
function seg(k, label, options) {
  const v = String(get(state.project, k));
  return `<div class="f wide">${label ? `<span class="lab">${label}</span>` : ""}<div class="seg" role="group" aria-label="${esc(label || k)}">${options.map(([o, n]) => `<button type="button" data-seg="${k}" data-v="${o}" aria-pressed="${String(o) === v}">${esc(n)}</button>`).join("")}</div></div>`;
}
const toggle = (k, label, sub) => `<label class="toggle"><span>${esc(label)}${sub ? `<span class="tsub">${esc(sub)}</span>` : ""}</span><input type="checkbox" data-k="${k}" ${get(state.project, k) ? "checked" : ""}></label>`;
const tools = (kind, i, n, dup) => `<div class="tools">
  ${kind === "layer" ? `<button type="button" class="iconbtn" data-act="${kind}-up" data-i="${i}" ${i === 0 ? "disabled" : ""} title="Move up" aria-label="Move up">${SVG.up}</button>
  <button type="button" class="iconbtn" data-act="${kind}-down" data-i="${i}" ${i === n - 1 ? "disabled" : ""} title="Move down" aria-label="Move down">${SVG.down}</button>` : ""}
  ${dup ? `<button type="button" class="iconbtn" data-act="${kind}-dup" data-i="${i}" title="Duplicate" aria-label="Duplicate">${SVG.copy}</button>` : ""}
  <button type="button" class="iconbtn" data-act="${kind}-del" data-i="${i}" title="Remove" aria-label="Remove">${SVG.del}</button></div>`;

const presetOptions = (sel) => PRESET_GROUPS.map(([g, keys]) => `<optgroup label="${esc(g)}">${keys.map((key) => `<option value="${key}" ${key === sel ? "selected" : ""}>${esc(PRESETS[key].name)}</option>`).join("")}</optgroup>`).join("");

function layersWidget(p) {
  const tops = [];
  let z = 0;
  for (const l of p.layers) { tops.push(z); z += +l.thickness || 0; }
  const cards = p.layers.map((l, i) => {
    const k = `layers.${i}`;
    const clay = l.consolidating ? `<div class="sub">
        ${seg(`${k}.model`, "Compressibility from", [["cc", "Cc and Cr"], ["mv", "mv"]])}
        <div class="two">
          ${l.model === "mv" ? num(`${k}.mv`, "mv", "m²/MN", { min: 0, step: 0.05, sub: "oedometer, for this stress range" })
            : num(`${k}.Cc`, "Compression Cc", "", { min: 0, step: 0.01 }) + num(`${k}.Cr`, "Recompression Cr", "", { min: 0, step: 0.005 })
            + num(`${k}.e0`, "Void ratio e0", "", { min: 0, step: 0.05 }) + num(`${k}.OCR`, "OCR", "", { min: 1, step: 0.1, sub: "σ'p / σ'v0" })
            + num(`${k}.POP`, "POP", "kPa", { min: 0, step: 5, sub: "added to σ'p" })}
          ${num(`${k}.cv`, "cv", "m²/yr", { min: 0, step: 0.1 })}
          ${num(`${k}.Ca`, "Creep Cα", "", { min: 0, step: 0.001 })}
        </div>
        ${seg(`${k}.drainage`, "Drains through", [["double", "Top and bottom"], ["single", "One face only"]])}
        ${toggle(`${k}.drains.on`, "Wick drains", "vertical drains that speed consolidation up")}
        ${l.drains.on ? `<div class="two">
          ${num(`${k}.drains.spacing`, "Spacing", "m", { min: 0.3, step: 0.1 })}
          ${num(`${k}.drains.ch`, "ch", "m²/yr", { min: 0, step: 0.5, sub: "horizontal" })}
          ${num(`${k}.drains.dw`, "Drain diameter", "m", { min: 0.01, step: 0.005, sub: "0.066 for a 100 mm band" })}
        </div>${seg(`${k}.drains.pattern`, "Pattern", [["tri", "Triangular"], ["square", "Square"]])}` : ""}
      </div>` : "";
    return `<div class="item" data-layer="${i}">
      <div class="item-head"><span class="chip" style="background:${soilColour(l, i)}"></span><input class="lname" data-k="${k}.name" value="${esc(l.name)}" aria-label="Layer name">${tools("layer", i, p.layers.length, true)}</div>
      <div class="note">${fmt(tops[i], 2)} to ${fmt(tops[i] + (+l.thickness || 0), 2)} m below ground</div>
      <div class="f wide"><span class="lab">Start from a typical soil<small>fills in the values below; change any of them after</small></span><select data-preset="${i}">
        <option value="">Choose…</option>${presetOptions(l.preset)}</select></div>
      <div class="two">
        ${num(`${k}.thickness`, "Thickness", "m", { min: 0, step: 0.1 })}
        ${num(`${k}.E`, "Young's modulus E", "kPa", { min: 0, step: 500, sub: "at the top; 0 skips" })}
        ${num(`${k}.gamma`, "Unit weight γ", "kN/m³", { min: 0, step: 0.5, sub: "above water" })}
        ${num(`${k}.gammaSat`, "Saturated γsat", "kN/m³", { min: 0, step: 0.5, sub: "below water" })}
        ${num(`${k}.nu`, "Poisson's ratio ν", "", { min: 0, max: 0.49, step: 0.05 })}
        ${num(`${k}.Einc`, "E grows by", "kPa/m", { step: 100, sub: "with depth" })}
        ${num(`${k}.phi`, "Friction angle φ'", "°", { min: 0, max: 50, step: 1, sub: "for bearing" })}
        ${num(`${k}.c`, "Cohesion c'", "kPa", { min: 0, step: 1 })}
        ${l.consolidating ? num(`${k}.su`, "Undrained strength su", "kPa", { min: 0, step: 5, sub: "0: not checked" }) : ""}
      </div>
      ${toggle(`${k}.consolidating`, "Consolidates", "clay, silt or organic soil: settles slowly as water drains")}
      ${clay}
    </div>`;
  }).join("");
  return `${cards || `<div class="note">No layers yet.</div>`}
    <div class="addrow"><select id="addPreset" aria-label="Soil for the new layer">${presetOptions("sand")}</select>
    <button type="button" class="btn btn-ghost btn-sm" data-act="layer-add">+ Add layer</button></div>`;
}

const overburden = (z) => initialStress(state.project.layers, +state.project.waterTable || 0, z).total;
const loadSub = (l) => {
  const q = grossPressure(l), qa = appliedPressure(l, overburden);
  const parts = [];
  if (l.type === "embankment") parts.push(`q = γ·H = ${fmt(q, 0)} kPa${+l.slope > 0 && +l.H > 0 ? `, sides 1 in ${fmt(+l.slope / +l.H, 1)}` : ""}`);
  else if (l.type === "pilegroup") { const e = equivalentRaft(l); parts.push(`equivalent raft ${fmt(e.B, 1)} × ${fmt(e.L, 1)} m at ${fmt(e.zf, 1)} m deep, ${fmt(q, 0)} kPa`); }
  else parts.push(`${fmt(q, 0)} kPa on the ground${l.net ? `, ${fmt(qa, 0)} kPa net of the soil dug out` : ""}`);
  if (l.type !== "pilegroup") parts.push(`${fmt(loadForce(l) / 1000, 1)} MN in all`);
  return parts.join(" · ");
};
const FOOTING = ["pad", "strip", "rect", "building", "ring", "circle", "polygon"];
function loadFields(l, k) {
  const BL = (b = "Width B", ln = "Length L") => num(`${k}.B`, b, "m", { min: 0, step: 0.1 }) + num(`${k}.L`, ln, "m", { min: 0, step: 0.5 });
  switch (l.type) {
    case "pad": return BL() + num(`${k}.P`, "Column load", "kN", { step: 50, sub: "with the footing" });
    case "strip": return BL("Width B", "Length") + num(`${k}.w`, "Wall load", "kN/m", { step: 10 });
    case "building": return BL() + num(`${k}.storeys`, "Storeys", "", { min: 0, step: 1 }) + num(`${k}.perStorey`, "Load per storey", "kPa", { min: 0, step: 0.5, sub: "10 to 15 is usual" })
      + num(`${k}.extra`, "Raft and basement", "kPa", { min: 0, step: 1 });
    case "circle": return num(`${k}.R`, "Radius R", "m", { min: 0, step: 0.5 }) + num(`${k}.q`, "Pressure q", "kPa", { step: 5 });
    case "ring": return num(`${k}.R`, "Outer radius", "m", { min: 0, step: 0.5 }) + num(`${k}.Ri`, "Inner radius", "m", { min: 0, step: 0.5 }) + num(`${k}.q`, "Pressure q", "kPa", { step: 5 });
    case "polygon": return num(`${k}.q`, "Pressure q", "kPa", { step: 5 });
    case "embankment": return num(`${k}.H`, "Height H", "m", { min: 0, step: 0.25 }) + num(`${k}.gamma`, "Fill γ", "kN/m³", { min: 0, step: 0.5 })
      + num(`${k}.crest`, "Crest width", "m", { min: 0, step: 0.5 }) + num(`${k}.slope`, "Side slope run", "m", { min: 0, step: 0.5, sub: "each side" }) + num(`${k}.L`, "Length", "m", { min: 0, step: 5 });
    case "pilegroup": return BL("Group width", "Group length") + num(`${k}.Lp`, "Pile length", "m", { min: 0, step: 0.5, sub: "below the cap" }) + num(`${k}.Q`, "Load on the group", "kN", { step: 500 });
    default: return BL() + num(`${k}.q`, "Pressure q", "kPa", { step: 5 });
  }
}
function loadsWidget(p) {
  const cards = p.loads.map((l, i) => {
    const k = `loads.${i}`;
    const isPoly = l.type === "polygon", emb = l.type === "embankment";
    if (l.type === "field") return `<div class="item ${l.on === false ? "off" : ""}" data-load="${i}">
      <div class="item-head"><input class="lname" data-k="${k}.name" value="${esc(l.name)}" aria-label="Name">${tools("load", i, p.loads.length, true)}</div>
      <div class="note">Soil pressures brought in from SAFE: ${esc(describeLoad(l))}. Bring new ones in under CSI SAFE link.</div>
      <div class="two">${num(`${k}.Df`, "Founded at", "m", { min: 0, step: 0.25, sub: "below ground" })}${num(`${k}.t0`, "Applied at", "yr", { min: 0, step: 0.25, sub: "0 = start" })}</div>
      ${+l.Df > 0 ? toggle(`${k}.net`, "Take off the soil dug out", "net pressure: only the load beyond the excavated soil's weight settles the ground") : ""}
      ${toggle(`${k}.on`, "Switched on")}
    </div>`;
    // with many foundations, each is one line until it is opened
    if (p.loads.length > 4 && state.openLoad !== i) return `<div class="item compact ${l.on === false ? "off" : ""}" data-load="${i}">
      <div class="item-head"><button type="button" class="lopen" data-act="load-open" data-i="${i}" aria-expanded="false"><b>${esc(l.name || `Load ${i + 1}`)}</b><span>${esc(LOAD_NAMES[l.type] || l.type)} at (${fmt(loadCentre(l)[0], 1)}, ${fmt(loadCentre(l)[1], 1)}) · ${esc(describeLoad(l))}</span></button>${tools("load", i, p.loads.length, true)}</div>
    </div>`;
    return `<div class="item ${l.on === false ? "off" : ""}" data-load="${i}">
      <div class="item-head"><input class="lname" data-k="${k}.name" value="${esc(l.name)}" aria-label="Name">${tools("load", i, p.loads.length, true)}</div>
      <div class="f wide"><select data-loadtype="${i}" aria-label="Kind of foundation or load">${LOAD_TYPES.map(([t, n, d]) => `<option value="${t}" ${t === l.type ? "selected" : ""}>${esc(n)}: ${esc(d)}</option>`).join("")}</select></div>
      ${isPoly ? `<div class="f wide"><span class="lab">Corners<small>one "x, y" per line, in metres, going round the shape</small></span><textarea class="pts" data-k="${k}.pts" rows="${Math.min(10, Math.max(4, String(l.pts || "").split("\n").length + 1))}" spellcheck="false" aria-label="Corners">${esc(l.pts || "")}</textarea></div>` : ""}
      <div class="two">
        ${isPoly ? "" : num(`${k}.x`, "Centre x", "m", { step: 0.5 }) + num(`${k}.y`, "Centre y", "m", { step: 0.5 })}
        ${loadFields(l, k)}
        ${emb ? "" : num(`${k}.Df`, l.type === "pilegroup" ? "Cap founded at" : "Founded at", "m", { min: 0, step: 0.25, sub: "below ground" })}
        ${["pad", "strip", "rect", "building", "pilegroup"].includes(l.type) ? num(`${k}.angle`, "Turned by", "°", { step: 5, sub: "anticlockwise" }) : ""}
        ${num(`${k}.t0`, "Applied at", "yr", { min: 0, step: 0.25, sub: "0 = start" })}
      </div>
      ${emb ? seg(`${k}.axis`, "Runs along", [["y", "y"], ["x", "x"]]) : ""}
      ${l.type === "pilegroup" ? seg(`${k}.pileType`, "The piles carry their load by", [["friction", "Shaft friction"], ["end", "End bearing"]]) : ""}
      ${FOOTING.includes(l.type) && !isPoly ? toggle(`${k}.rigid`, "Rigid foundation", "settles evenly and tilts as one piece; off for a flexible raft or tank") : ""}
      ${FOOTING.includes(l.type) && +l.Df > 0 ? toggle(`${k}.net`, "Take off the soil dug out", "net pressure: only the load beyond the excavated soil's weight settles the ground") : ""}
      ${toggle(`${k}.on`, "Switched on")}
      <div class="note" data-loadsub="${i}">${esc(loadSub(l))}</div>
    </div>`;
  }).join("");
  const g = state.gridForm;
  return `${cards || `<div class="note">No loads yet.</div>`}
    <div class="addrow"><select id="addLoad" aria-label="Kind of foundation or load to add">${LOAD_TYPES.map(([t, n]) => `<option value="${t}">${esc(n)}</option>`).join("")}</select>
    <button type="button" class="btn btn-primary btn-sm" data-act="load-add">+ Add</button></div>
    <details class="gridform"><summary>Add a grid of column footings</summary>
      <div class="two" style="margin-top:8px">
        ${gf("nx", "Columns along x", "", 1)}${gf("ny", "Columns along y", "", 1)}
        ${gf("sx", "Spacing along x", "m", 0.5)}${gf("sy", "Spacing along y", "m", 0.5)}
        ${gf("B", "Footing size", "m", 0.1)}${gf("P", "Inner column load", "kN", 50)}
        ${gf("Df", "Founded at", "m", 0.25)}
      </div>
      <div class="note">Edge columns get 60% and corner columns 40% of the inner load. Each footing can be changed after.</div>
      <div class="addrow"><button type="button" class="btn btn-ghost btn-sm" data-act="grid-add">Add ${g.nx * g.ny} footings</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="grid-replace">Replace all loads with them</button></div>
    </details>`;
}
// ---- the loop with CSI SAFE
const fieldIndex = () => state.project.loads.findIndex((l) => l.type === "field");
function safeList() {
  const i = fieldIndex();
  if (i < 0) return [];
  if (!state.safeList) state.safeList = springs(state.project, state.project.loads[i], life());
  return state.safeList;
}
function zoneMap(list, size, zoning) {
  if (!list.length) return "";
  const xs = list.map((s) => s.x), ys = list.map((s) => s.y), x1 = Math.min(...xs) - size / 2, y2 = Math.max(...ys) + size / 2;
  const w = Math.max(...xs) + size / 2 - x1, h = y2 - (Math.min(...ys) - size / 2), n = zoning.zones.length;
  const col = (z) => `color-mix(in srgb, var(--series-1) ${n > 1 ? Math.round(18 + (72 * z) / (n - 1)) : 60}%, var(--surface))`;
  return `<svg class="zonemap" viewBox="0 0 ${w} ${h}" role="img" aria-label="Where each soil property goes">${list.map((s, i) => `<rect x="${(s.x - size / 2 - x1).toFixed(3)}" y="${(y2 - s.y - size / 2).toFixed(3)}" width="${size.toFixed(3)}" height="${size.toFixed(3)}" fill="${col(zoning.of[i])}"><title>${zoning.zones[zoning.of[i]]?.name || ""} at (${fmt(s.x, 1)}, ${fmt(s.y, 1)}): ${mm(s.s, 1)} mm</title></rect>`).join("")}</svg>
    <div class="zonekey">${zoning.zones.map((z, i) => `<span><i style="background:${col(i)}"></i>${z.name}</span>`).join("")}<span class="muted">soft to stiff</span></div>`;
}
function safeWidget(p) {
  const s = p.safe, u = unitSystem(s.units), d = state.safeDraft, K = 1 / u[6];
  const kf = (k) => fmt(k * K, k * K >= 100 ? 0 : k * K >= 1 ? 2 : 5);
  const opt = (list, sel) => list.map((c) => `<option value="${esc(c)}" ${c === sel ? "selected" : ""}>${esc(c)}</option>`).join("");
  const draft = d ? (d.error ? `<div class="warn bad-text">✕ ${esc(d.error)}</div>` : `<div class="ok">✓ ${esc(d.name)}: ${d.info.kind === "pressure" ? "soil pressures" : "vertical reactions"} at ${fmt(d.info.points.length, 0)} points${d.info.table && d.info.table !== "pasted" ? ` from the sheet "${esc(d.info.table)}"` : ""}, units ${esc(d.info.units)}.</div>
      ${d.info.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("")}
      ${d.info.cases.length > 1 ? `<div class="f wide"><span class="lab">Load case or combination<small>use the long-term service one</small></span><select data-safe="kase">${opt(d.info.cases, d.info.kase)}</select></div>` : ""}
      ${d.info.steps.length > 1 ? `<div class="f wide"><span class="lab">Step</span><select data-safe="step">${opt(d.info.steps, d.info.step)}</select></div>` : ""}
      <button type="button" class="btn btn-primary btn-sm" data-act="safe-run">Bring it in and work out the springs</button>`) : "";
  const rounds = s.rounds.length ? `<div class="table-scroll"><table class="tight"><thead><tr><th>Round</th><th class="num">Settlement (mm)</th><th class="num">Springs (${u[5]})</th><th class="num">Change</th></tr></thead><tbody>
      ${s.rounds.map((r, i) => `<tr><td><b>${i + 1}</b><div class="note">${r.kase ? `${esc(r.kase)}, ` : ""}${fmt(r.force / 1000, 1)} MN</div></td><td class="num">${mm(r.sMin)}<div class="note">to ${mm(r.sMax)}</div></td><td class="num">${kf(r.kMin)}<div class="note">to ${kf(r.kMax)}</div></td><td class="num">${r.mean === null ? "first" : `${fmt(r.mean * 100, 1)}%<div class="note">most ${fmt(r.max * 100, 1)}%</div>`}</td></tr>`).join("")}
      </tbody></table></div>` : "";
  const last = s.rounds.at(-1), i = fieldIndex();
  let out = "";
  if (last && i >= 0) {
    const list = safeList(), zoning = zonesOf(list, +s.zones || 5);
    out = `${last.converged ? `<div class="ok">✓ Converged: the springs moved by ${fmt(last.mean * 100, 1)}% on average since the round before, under the ${fmt(+s.tol, 0)}% asked for. SAFE and the ground agree.</div>`
      : `<div class="warn">▲ ${last.mean === null ? "First round." : `The springs moved by ${fmt(last.mean * 100, 1)}% on average (most ${fmt(last.max * 100, 1)}%).`} Put these springs into SAFE, run it again, and bring the new soil pressures in.</div>`}
      ${zoneMap(list, +p.loads[i].size, zoning)}
      <div class="table-scroll"><table class="tight"><thead><tr><th>Soil property</th><th class="num">Subgrade modulus (${u[5]})</th><th class="num">Cells</th></tr></thead><tbody>${zoning.zones.map((z) => `<tr><td>${z.name}</td><td class="num"><b>${kf(z.k)}</b></td><td class="num">${z.n}</td></tr>`).join("")}</tbody></table></div>
      <div class="addrow"><button type="button" class="btn btn-primary btn-sm" data-act="safe-props">Download the soil properties</button><button type="button" class="btn btn-ghost btn-sm" data-act="safe-cells">Download where each one goes</button></div>
      <div class="note">Springs are pressure over settlement at the design life (${yrs(life())}). In SAFE: Define, Soil Subgrade Properties for the values; Assign, Support Data, Soil Properties to put each one on its part of the raft, following the map.</div>`;
  }
  return `<div class="note">SAFE solves the raft on springs; GeoProMax works out the springs the ground really gives. Pass the results back and forth until they stop changing.<br><b>1.</b> In SAFE, run the analysis and export the <b>Soil Pressures</b> table to Excel. <b>2.</b> Open it here. <b>3.</b> Put the springs below into SAFE and run it again. Repeat.</div>
    <div class="addrow"><label class="btn btn-ghost btn-sm filebtn">Open SAFE's Excel or CSV file<input type="file" id="safeFile" accept=".xlsx,.csv,.txt,.tsv" hidden></label></div>
    <textarea class="pts" id="safePaste" rows="3" spellcheck="false" placeholder="or paste the table here from Excel, with its headings" aria-label="Paste the table from SAFE"></textarea>
    <div class="addrow"><button type="button" class="btn btn-ghost btn-sm" data-act="safe-paste">Read the pasted table</button></div>
    ${draft}
    <div class="f wide"><span class="lab">Units<small>for the springs, and for a table that does not say its own</small></span><select data-safe="units" aria-label="Units">${UNIT_SYSTEMS.map(([k, n]) => `<option value="${k}" ${k === s.units ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
    <div class="two">
      ${num("safe.tol", "Converged under", "%", { min: 0.5, step: 0.5, sub: "mean change" })}
      ${num("safe.zones", "Soil properties", "", { min: 1, max: 12, step: 1, sub: "bands of springs" })}
    </div>
    ${rounds}${out}
    ${s.rounds.length ? `<div class="addrow"><button type="button" class="btn btn-ghost btn-sm" data-act="safe-reset">Start the rounds again</button></div>` : ""}`;
}
function safeRead(name, tables) {
  const s = state.project.safe;
  try { state.safeDraft = { name, tables, info: readSafe(tables, { units: s.units, kase: s.kase, step: s.step }) }; }
  catch (e) { state.safeDraft = { name, tables: null, error: e.message }; }
  renderInputs();
}
function safeRun() {
  const d = state.safeDraft, p = state.project;
  if (!d || !d.info) return;
  const c = toCells(d.info.points, d.info.kind);
  let i = fieldIndex();
  const first = i < 0;
  if (first) { p.loads.push(loadFrom("field")); i = p.loads.length - 1; }
  p.loads[i].cells = c.cells.map((r) => r.map((v) => +v.toFixed(4)));
  p.loads[i].size = +c.size.toFixed(4);
  let r;
  try { r = safeRound(p, p.loads[i], life(), p.safe.k, { tol: (+p.safe.tol || 5) / 100 }); }
  catch (e) { toast("The springs could not be worked out: " + e.message, true); return; }
  p.safe.rounds.push({ ...r.summary, kase: d.info.kase, file: d.name });
  p.safe.k = r.list.map((x) => [x.x, x.y, x.k === null ? 0 : +x.k.toPrecision(6)]);
  p.safe.kase = d.info.kase; p.safe.step = d.info.step;
  state.safeDraft = null;
  const others = p.loads.filter((l, n) => n !== i && l.on !== false).length;
  changed(true);
  state.safeList = r.list;
  toast(r.summary.converged ? "Converged: SAFE and the ground agree." : first && others ? `Round 1 done. ${others} other load${others === 1 ? " is" : "s are"} still switched on: switch off any that SAFE's raft replaces.` : `Round ${p.safe.rounds.length} done. Put the springs into SAFE and run it again.`);
}
function safeDownload(which) {
  const p = state.project, i = fieldIndex();
  if (i < 0) return;
  const list = safeList(), t = exportTables(list, +p.loads[i].size, zonesOf(list, +p.safe.zones || 5), p.safe.units);
  download(`${safeName()} springs round ${p.safe.rounds.length} ${which === "props" ? "properties" : "cells"}.csv`, which === "props" ? t.props : t.cells, "text/csv");
}

const gf = (k, label, unit, step) => `<div class="f"><span class="lab">${label}</span><span class="num"><input type="number" inputmode="decimal" data-grid="${k}" value="${state.gridForm[k]}" min="${k === "nx" || k === "ny" ? 1 : 0}" step="${step}" aria-label="${label}"><span class="unit">${unit}</span></span></div>`;

const limitText = (p) => `${fmt(+p.limits.total, 0)} mm${+p.limits.tilt > 0 ? ` · 1/${fmt(+p.limits.tilt, 0)}` : ""}`;
const GROUPS = [
  { g: "Structure and limits", icon: "limit", open: true, sum: limitText,
    body: (p) => `<div class="f wide"><span class="lab">What is being built<small>sets the usual limits; type your own over them</small></span><select data-structure aria-label="Kind of structure">${STRUCTURES.map(([k, n]) => `<option value="${k}" ${k === p.limits.preset ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
      <div class="two">${num("limits.total", "Settlement limit", "mm", { min: 0, step: 5 })}${num("limits.tilt", "Tilt limit, 1 in", "", { min: 0, step: 50, sub: "0: not checked" })}${num("limits.fos", "Bearing safety factor", "", { min: 0, step: 0.1, sub: "at least" })}</div>
      <div class="note">${esc(structureOf(p.limits.preset)[4] || "Your own limits.")}</div>` },
  { g: "Soil profile", icon: "layers", open: true, sum: (p) => `${p.layers.length} layer${p.layers.length === 1 ? "" : "s"} · ${fmt(depthOf(p), 1)} m`, body: layersWidget },
  { g: "Groundwater", icon: "water", open: false, sum: (p) => `${fmt(+p.waterTable, 2)} m deep`,
    body: () => num("waterTable", "Water table depth", "m", { min: 0, step: 0.25, sub: "below ground; hydrostatic below it" }) },
  { g: "Foundations and loads", icon: "load", open: true, sum: (p) => `${p.loads.filter((l) => l.on !== false).length} on`, body: loadsWidget },
  { g: "CSI SAFE link", icon: "link", open: false, sum: (p) => { const r = p.safe.rounds; return !r.length ? "not used" : r.at(-1).converged ? `converged, round ${r.length}` : `round ${r.length}`; }, body: safeWidget },
  { g: "Analysis", icon: "calc", open: false, sum: (p) => `${p.method === "westergaard" ? "Westergaard" : "Boussinesq"} · ${fmt(+p.life, 0)} yr`,
    body: (p) => seg("method", "Stress distribution", [["boussinesq", "Boussinesq"], ["westergaard", "Westergaard"]])
      + `<div class="note">${p.method === "westergaard" ? "Westergaard: a soil reinforced by thin stiff layers (varved clays). It spreads the load more, so stresses under the centre are lower." : "Boussinesq: a uniform elastic half-space. The usual choice."}</div>`
      + num("life", "Design life", "years", { min: 0.1, step: 1, picks: [10, 25, 50, 100], sub: "the end of the time axis" })
      + num("subLayers", "Sub-layers per layer", "", { min: 2, max: 200, step: 1, blank: true, ph: "auto", sub: "blank refines until the answer stops changing" })
      + num("grid.n", "Plan grid", "pts", { min: 11, max: 81, step: 2, sub: "points along the longer side" })
      + num("grid.margin", "Plan margin", "m", { min: 0, step: 1, blank: true, ph: "auto", sub: "around the loads; blank = soil depth" })
      + seg("section", "Section A–A′ runs along", [["x", "x"], ["y", "y"]]) },
  { g: "Query point", icon: "point", open: false, sum: (p) => `(${fmt(+p.query.x, 1)}, ${fmt(+p.query.y, 1)})`,
    body: () => `<div class="two" style="display:grid;grid-template-columns:1fr 1fr;gap:8px 10px">${num("query.x", "x", "m", { step: 0.5 })}${num("query.y", "y", "m", { step: 0.5 })}</div>
      <div class="note">Or click anywhere on the plan. The headline, the charts and the section are for this point.</div>
      <div class="picks"><button type="button" data-act="query-max">Go to the largest settlement</button>${state.project.loads.slice(0, 6).map((l, i) => `<button type="button" data-act="query-load" data-i="${i}">Centre of ${esc(l.name || `load ${i + 1}`)}</button>`).join("")}</div>` },
];

function renderInputs() {
  const p = state.project;
  const host = $("#inputs");
  const openNow = new Set($$("details.group[open]", host).map((d) => d.dataset.g));
  const first = !host.dataset.ready;
  host.dataset.ready = "1";
  const scroll = host.scrollTop;
  host.innerHTML = GROUPS.map((G2) => {
    const open = first ? G2.open : openNow.has(G2.g);
    return `<details class="group" data-g="${G2.g}" ${open ? "open" : ""}><summary>${icon(G2.icon)}${G2.g}<span class="sum">${esc(G2.sum(p))}</span></summary><div class="group-body">${G2.body(p)}</div></details>`;
  }).join("");
  host.scrollTop = scroll;
}
function refreshSums() {
  for (const d of $$("details.group", $("#inputs"))) {
    const G2 = GROUPS.find((x) => x.g === d.dataset.g);
    d.querySelector(".sum").textContent = G2.sum(state.project);
  }
  state.project.loads.forEach((l, i) => { const el = $(`[data-loadsub="${i}"]`); if (el) el.textContent = loadSub(l); });
}

function onInput(ev) {
  const el = ev.target;
  const p = state.project;
  if (el.dataset.preset !== undefined) {
    if (!el.value) return;
    const i = +el.dataset.preset, old = p.layers[i];
    p.layers[i] = { ...layerFrom(el.value, old.thickness), name: PRESETS[el.value].name };
    changed(true);
    return;
  }
  if (el.dataset.loadtype !== undefined) {
    const i = +el.dataset.loadtype, old = p.loads[i];
    const [cx, cy] = loadCentre(old);
    const next = loadFrom(el.value, { x: cx, y: cy, t0: old.t0, on: old.on });
    // keep a name the user gave, and the size where the new kind has one
    if (old.name && old.name !== loadFrom(old.type).name) next.name = old.name;
    for (const key of ["B", "L", "R"]) if (key in next && +old[key] > 0 && !["strip"].includes(el.value) && !["strip"].includes(old.type)) next[key] = old[key];
    p.loads[i] = next;
    changed(true);
    return;
  }
  if (el.dataset.structure !== undefined) {
    const st = structureOf(el.value);
    p.limits = el.value === "custom" ? { ...p.limits, preset: "custom" } : { preset: st[0], total: st[2], tilt: st[3], fos: bearingLimit(st[0]) };
    changed(true);
    return;
  }
  if (el.dataset.grid) {
    const v = +el.value;
    if (Number.isFinite(v)) state.gridForm[el.dataset.grid] = ["nx", "ny"].includes(el.dataset.grid) ? Math.max(1, Math.min(20, Math.round(v))) : Math.max(0, v);
    const b = $('[data-act="grid-add"]'); if (b) b.textContent = `Add ${state.gridForm.nx * state.gridForm.ny} footings`;
    return;
  }
  if (el.id === "safeFile") {
    const f = el.files?.[0];
    if (!f) return;
    (async () => {
      if (/\.xls$/i.test(f.name)) { state.safeDraft = { name: f.name, error: "this is an old .xls workbook. Save it as .xlsx (or CSV) in Excel and open that." }; renderInputs(); return; }
      try { safeRead(f.name, /\.xlsx$/i.test(f.name) ? await readXlsx(await f.arrayBuffer()) : [{ name: "pasted", rows: parseDelimited(await f.text()) }]); }
      catch (e) { state.safeDraft = { name: f.name, error: e.message }; renderInputs(); }
    })();
    return;
  }
  if (el.dataset.safe) {
    p.safe[el.dataset.safe] = el.value;
    if (state.safeDraft?.tables) safeRead(state.safeDraft.name, state.safeDraft.tables); else renderInputs();
    scheduleSave();
    return;
  }
  if (el.id === "safePaste") return;
  if (!el.dataset.k) return;
  let v;
  if (el.type === "checkbox") v = el.checked;
  else if (el.type === "text" || el.tagName === "SELECT" || el.tagName === "TEXTAREA") v = el.value;
  else v = el.value === "" ? null : +el.value;
  set(p, el.dataset.k, v);
  if (/^layers\.\d+\.name$/.test(el.dataset.k) || /^loads\.\d+\.name$/.test(el.dataset.k)) { changed(false, true); return; }
  if (/^limits\.(total|tilt)$/.test(el.dataset.k)) {
    const st = structureOf(p.limits.preset);
    if (+p.limits.total !== st[2] || +p.limits.tilt !== st[3]) p.limits.preset = "custom";
  }
  changed(el.type === "checkbox" || /\.thickness$/.test(el.dataset.k));
}

function onClick(ev) {
  const b = ev.target.closest("button");
  if (!b) return;
  const p = state.project;
  if (b.dataset.seg) {
    set(p, b.dataset.seg, b.dataset.v);
    changed(true);
    return;
  }
  if (b.dataset.pick) { set(p, b.dataset.pick, +b.dataset.v); changed(true); return; }
  const act = b.dataset.act, i = +b.dataset.i;
  if (!act) return;
  if (act === "layer-add") { const key = $("#addPreset").value; p.layers.push({ ...layerFrom(key, 3), name: PRESETS[key].name }); }
  else if (act === "layer-del") p.layers.splice(i, 1);
  else if (act === "layer-dup") p.layers.splice(i + 1, 0, JSON.parse(JSON.stringify(p.layers[i])));
  else if (act === "layer-up" && i > 0) [p.layers[i - 1], p.layers[i]] = [p.layers[i], p.layers[i - 1]];
  else if (act === "layer-down" && i < p.layers.length - 1) [p.layers[i + 1], p.layers[i]] = [p.layers[i], p.layers[i + 1]];
  else if (act === "load-add") {
    const e = p.loads.length ? extents(p.loads, 0) : null;
    const l = loadFrom($("#addLoad").value);
    if (e) { if (l.type === "polygon") l.pts = parsePoints(l.pts).map(([x, y]) => `${x + Math.round(e.x2 + 5)}, ${y}`).join("\n"); else l.x = Math.round(e.x2 + 10); }
    if (p.loads.some((o) => o.name === l.name)) l.name = `${l.name} ${p.loads.length + 1}`;
    p.loads.push(l); state.openLoad = p.loads.length - 1;
  }
  else if (act === "grid-add" || act === "grid-replace") {
    const pads = padGrid(state.gridForm);
    if (act === "grid-replace") p.loads = pads;
    else {
      const e = p.loads.length ? extents(p.loads, 0) : null, w = (state.gridForm.nx - 1) * state.gridForm.sx;
      const dx = e ? Math.round(e.x2 + 6 + w / 2) : 0;
      p.loads.push(...pads.map((l) => ({ ...l, x: l.x + dx })));
    }
    toast(`${pads.length} footings added. Undo takes them back.`);
  }
  else if (act === "safe-paste") { const t = $("#safePaste").value; if (t.trim()) safeRead("Pasted table", [{ name: "pasted", rows: parseDelimited(t) }]); return; }
  else if (act === "safe-run") { safeRun(); return; }
  else if (act === "safe-props" || act === "safe-cells") { safeDownload(act === "safe-props" ? "props" : "cells"); return; }
  else if (act === "safe-reset") { p.safe.rounds = []; p.safe.k = null; }
  else if (act === "load-open") { state.openLoad = i; renderInputs(); return; }
  else if (act === "load-del") { p.loads.splice(i, 1); state.openLoad = null; }
  else if (act === "load-dup") {
    const c = JSON.parse(JSON.stringify(p.loads[i])); c.name += " (copy)";
    const e = extents([c], 0), w = e.x2 - e.x1 + 2;
    if (c.type === "polygon") c.pts = parsePoints(c.pts).map(([x, y]) => `${+(x + w).toFixed(3)}, ${y}`).join("\n"); else c.x = +((+c.x || 0) + w).toFixed(3);
    p.loads.splice(i + 1, 0, c);
  }
  else if (act === "query-load") { const [x, y] = loadCentre(p.loads[i]); p.query = { x: +x.toFixed(2), y: +y.toFixed(2) }; }
  else if (act === "query-max") {
    if (!state.grid) return;
    const g = state.grid.g; let k = 0;
    for (let n = 1; n < state.grid.values.length; n++) if (state.grid.values[n] > state.grid.values[k]) k = n;
    p.query = { x: +(g.x1 + ((g.x2 - g.x1) * (k % g.nx)) / (g.nx - 1)).toFixed(2), y: +(g.y1 + ((g.y2 - g.y1) * Math.floor(k / g.nx)) / (g.ny - 1)).toFixed(2) };
  }
  else return;
  changed(true);
}

// ------------------------------------------------------------------ undo, redo, saving

const undo = [], redo = [];
let burst = null;
const snapNow = () => JSON.stringify(state.project);
function remember() {
  if (!burst) { if (state.snap && state.snap !== snapNow()) { undo.push(state.snap); if (undo.length > 60) undo.shift(); redo.length = 0; } }
  clearTimeout(burst);
  burst = setTimeout(() => { burst = null; state.snap = snapNow(); undoButtons(); }, 700);
  undoButtons();
}
function undoButtons() {
  $("#btnUndo").disabled = !undo.length && !(burst && state.snap !== snapNow());
  $("#btnRedo").disabled = !redo.length;
}
function stepHistory(back) {
  if (burst) { clearTimeout(burst); burst = null; const now = snapNow(); if (now !== state.snap) { undo.push(state.snap); redo.length = 0; } state.snap = now; }
  const from = back ? undo : redo, to = back ? redo : undo;
  if (!from.length) return;
  to.push(state.snap);
  state.snap = from.pop();
  state.project = complete(JSON.parse(state.snap));
  $("#projectName").value = state.project.name;
  renderInputs(); analyse(); scheduleSave(); undoButtons();
}
function resetHistory() { undo.length = 0; redo.length = 0; clearTimeout(burst); burst = null; state.snap = snapNow(); undoButtons(); }

function changed(structural, nameOnly) {
  remember();
  if (structural) renderInputs(); else refreshSums();
  scheduleSave();
  if (nameOnly) { renderView(); renderPanel(); return; }
  analyse();
}

async function api(path, opt = {}) {
  const r = await fetch(G.api + path, { credentials: "same-origin", headers: { "Content-Type": "application/json", Accept: "application/json" }, ...opt });
  if (!r.ok) throw Object.assign(new Error((await r.json().catch(() => ({}))).error || r.statusText), { status: r.status });
  return r.json();
}
let saveTimer;
function scheduleSave() {
  state.dirty = true;
  $("#saveState").textContent = "Editing…";
  $("#saveState").className = "save-state";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 1200);
}
async function save() {
  const data = state.project;
  try { localStorage.setItem("geopromax-last", JSON.stringify({ id: state.id, data })); } catch (e) { /* private mode */ }
  if (state.offline) { $("#saveState").textContent = "Saved on this device"; return; }
  try {
    const r = state.id ? await api(`/projects/${state.id}`, { method: "PUT", body: JSON.stringify({ data }) })
      : await api(`/projects`, { method: "POST", body: JSON.stringify({ data }) });
    state.id = r.id; state.version = r.version; state.dirty = false;
    history.replaceState(null, "", `${G.base}p/${r.id}`);
    $("#saveState").textContent = "Saved";
    $("#saveState").className = "save-state saved";
  } catch (e) {
    $("#saveState").textContent = "Not saved: " + e.message;
  }
}
window.addEventListener("beforeunload", (ev) => { if (state.dirty && !state.offline) { save(); } });

// ------------------------------------------------------------------ calculating

const TMIN = 0.01;
const tFromSlider = (u) => 10 ** (Math.log10(TMIN) + (u / 1000) * (Math.log10(life()) - Math.log10(TMIN)));
const sliderFromT = (t) => Math.round(((Math.log10(Math.max(TMIN, t)) - Math.log10(TMIN)) / (Math.log10(life()) - Math.log10(TMIN))) * 1000);
const life = () => Math.max(0.1, +state.project.life || 50);
const nowT = () => Math.min(life(), Math.max(TMIN, +state.project.t || 1));

function sectionLine() {
  const p = state.project, e = gridBox();
  const along = p.section === "y" ? "y" : "x";
  return along === "x"
    ? { along, at: +p.query.y || 0, a1: e.x1, a2: e.x2, depth: depthOf(p) || 10 }
    : { along, at: +p.query.x || 0, a1: e.y1, a2: e.y2, depth: depthOf(p) || 10 };
}
function gridBox() {
  const p = state.project;
  // By default the plan reaches about as far past the loads as the soil is deep:
  // the settlement trough dies out over roughly that distance.
  const auto = Math.max(5, Math.min(depthOf(p) || 10, 60));
  const e = extents(p.loads, p.grid.margin === null || p.grid.margin === "" ? auto : +p.grid.margin);
  // keep the query point on the plan
  const qx = +p.query.x || 0, qy = +p.query.y || 0, pad = 2;
  return { x1: Math.min(e.x1, qx - pad), x2: Math.max(e.x2, qx + pad), y1: Math.min(e.y1, qy - pad), y2: Math.max(e.y2, qy + pad) };
}

let worker = null, gridTimer = null, waitingTime = false, pendingTime = null;
function newWorker() {
  if (worker) worker.terminate();
  worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
  worker.onmessage = onWorker;
  worker.onerror = (e) => { setBusy(false); toast("The plan could not be worked out: " + (e.message || "worker error"), true); };
}
function askGrid() {
  clearTimeout(gridTimer);
  gridTimer = setTimeout(() => {
    const p = state.project;
    const n = Math.max(11, Math.min(81, Math.round(+p.grid.n || 41)));
    const b = gridBox();
    // equal spacing in x and y, with about n points along the longer side
    const span = Math.max(b.x2 - b.x1, b.y2 - b.y1), d = span / (n - 1);
    const g = { ...b, nx: Math.max(5, Math.round((b.x2 - b.x1) / d) + 1), ny: Math.max(5, Math.round((b.y2 - b.y1) / d) + 1) };
    newWorker();
    state.gridAsk++;
    waitingTime = false;
    setBusy(true, "Working out the plan…");
    worker.postMessage({ id: state.gridAsk, kind: "grid", project: JSON.parse(JSON.stringify(p)), g, t: nowT(), life: life(), section: sectionLine(),
      sub: gridSubLayers(p, state.res?.subLayers) });
  }, 180);
}
function askTime() {
  if (!state.grid || !worker) return;
  if (waitingTime) { pendingTime = nowT(); return; }
  waitingTime = true;
  worker.postMessage({ id: state.gridAsk, kind: "time", t: nowT() });
}
function onWorker(ev) {
  const m = ev.data;
  if (m.id !== state.gridAsk) return;
  if (m.kind === "progress") { $("#busyText").textContent = `Working out the plan… ${Math.round(m.done * 100)}%`; return; }
  if (m.kind === "error") { setBusy(false); toast("The plan could not be worked out: " + m.message, true); return; }
  if (m.kind === "found") { state.found = m; renderVerdict(); renderKpis(); if (state.tab === "found") renderPanel(); return; }
  if (m.kind === "grid") { state.grid = m; setBusy(false); }
  if (m.kind === "time") {
    state.grid = { ...state.grid, values: m.values, min: m.min, max: m.max, tilt: m.tilt, line: m.line };
    state.found = m.found;
    waitingTime = false;
    if (pendingTime !== null) { pendingTime = null; askTime(); }
    if (state.tab === "found" && !state.playing) renderPanel();
  }
  renderView(); renderVerdict(); renderKpis();
}
function setBusy(on, text) {
  $("#busy").classList.toggle("hidden", !on);
  if (text) $("#busyText").textContent = text;
}

function analyse() {
  const p = state.project;
  try {
    state.res = solvePoint(p, +p.query.x || 0, +p.query.y || 0);
  } catch (e) {
    state.res = null;
    toast("Could not work out the settlement: " + e.message, true);
  }
  state.curve = state.res ? timeCurve(state.res, life()) : null;
  state.found = null; state.safeList = null;
  try { state.bearing = bearingAll(p); } catch (e) { state.bearing = []; }
  syncTimebar();
  renderVerdict(); renderKpis(); renderTabs(); renderPanel();
  askGrid();
}

// ------------------------------------------------------------------ the answer

function syncTimebar() {
  $("#tSlider").value = sliderFromT(nowT());
  $("#tValue").textContent = yrs(nowT());
}

/** The design against its limits: the worst foundation at the design life. */
function judge() {
  const f = state.found, lim = state.project.limits;
  if (!f) return null;
  const live = f.life.filter((x) => !x.off);
  if (!live.length) return null;
  const worst = live.reduce((a, b) => (b.governing > a.governing ? b : a));
  const within = live.reduce((a, b) => (b.tilt > a.tilt ? b : a));
  const between = f.betweenLife;
  const tilt = Math.max(within.tilt, between.tilt);
  const limS = +lim.total > 0 ? +lim.total / 1000 : Infinity, limT = +lim.tilt > 0 ? 1 / +lim.tilt : Infinity;
  const names = state.project.loads, limB = +lim.fos > 0 ? +lim.fos : 0;
  const bear = (state.bearing || []).map((b, i) => b && b.checked ? { ...b, name: names[i]?.name || `Load ${i + 1}` } : null).filter(Boolean).reduce((a, b) => (!a || b.fos < a.fos ? b : a), null);
  return {
    worst, within, between, tilt, limS, limT, bear, limB, okB: !bear || !limB || bear.fos >= limB - 1e-9,
    okS: worst.governing <= limS + 1e-9, okT: tilt <= limT + 1e-12,
    tiltWhere: between.tilt > within.tilt ? `between ${between.a} and ${between.b}` : `across ${within.name}`,
  };
}
const tiltLimit = () => (+state.project.limits.tilt > 0 ? `1/${fmt(+state.project.limits.tilt, 0)}` : "not checked");
const fosText = (f) => (!Number.isFinite(f) ? "no net load" : f >= 20 ? "over 20" : fmt(f, f < 10 ? 2 : 1));
const oneIn = (t) => (t > 1e-7 ? `1/${fmt(1 / t, 0)}` : "none");

function renderVerdict() {
  const host = $("#ovVerdict");
  if (!state.res) { host.innerHTML = ""; return; }
  const now = settlementAt(state.res, nowT()), fin = settlementAt(state.res, life());
  const j = judge(), lim = state.project.limits;
  const pill = $("#fpill");
  if (!j) {
    host.innerHTML = `<div class="glass verdict"><div class="fos">${mm(now.total)}<span class="unit">mm</span></div>
      <div class="lines"><b>at (${fmt(+state.project.query.x, 1)}, ${fmt(+state.project.query.y, 1)}) after ${yrs(nowT())}</b><br>${mm(fin.total)} mm at ${yrs(life())}</div></div>`;
    pill.className = "fpill" + (pill.classList.contains("on") ? " on" : "");
    pill.innerHTML = `<b>${mm(now.total)} mm</b><span>after ${yrs(nowT())}</span>`;
    return;
  }
  const ok = j.okS && j.okT && j.okB;
  host.innerHTML = `<div class="glass verdict ${ok ? "pass" : "fail"}"><div class="fos">${mm(j.worst.governing)}<span class="unit">mm</span></div>
    <div class="lines"><b>${ok ? "✓ Within the limits" : "✕ Over the limits"}</b> at ${yrs(life())}<br>
    ${esc(j.worst.name)} settles most (limit ${fmt(+lim.total, 0)} mm) · steepest tilt ${oneIn(j.tilt)} (${+lim.tilt > 0 ? `limit ${tiltLimit()}` : "not checked"})${j.bear ? ` · bearing safety ${fosText(j.bear.fos)}${j.limB ? ` (at least ${fmt(j.limB, 1)})` : ""}` : ""}</div></div>`;
  pill.className = `fpill ${ok ? "pass" : "fail"}` + (pill.classList.contains("on") ? " on" : "");
  pill.innerHTML = `<b>${mm(j.worst.governing)} mm</b><span>${ok ? "✓ within" : "✕ over"} the limits at ${yrs(life())}</span>`;
}

const verdictBadge = (ok, yes, no) => (ok ? `<span class="badge good">✓ ${yes}</span>` : `<span class="badge critical">✕ ${no}</span>`);
function renderKpis() {
  const host = $("#kpis");
  const r = state.res;
  if (!r) { host.innerHTML = ""; return; }
  const now = settlementAt(r, nowT()), fin = settlementAt(r, life());
  const t90 = Math.max(0, ...r.layers.filter((l) => l.layer.consolidating && l.primary > 0).map((l) => timeTo(l.layer, 0.9)));
  const j = judge(), lim = state.project.limits;
  host.innerHTML = [
    [`Largest settlement`, j ? `${mm(j.worst.governing)} mm` : "…", j ? `${esc(j.worst.name)} at ${yrs(life())} ${verdictBadge(j.okS, `within ${fmt(+lim.total, 0)} mm`, `over ${fmt(+lim.total, 0)} mm`)}` : "working it out", j ? (j.okS ? "main" : "main bad") : ""],
    [`Steepest tilt`, j ? oneIn(j.tilt) : "…", j ? `${esc(j.tiltWhere)} ${+lim.tilt > 0 ? verdictBadge(j.okT, `flatter than ${tiltLimit()}`, `steeper than ${tiltLimit()}`) : `<span class="badge">no limit set</span>`}` : "working it out", j ? (j.okT ? "main" : "main bad") : ""],
    [`Bearing safety`, j ? (j.bear ? fosText(j.bear.fos) : "–") : "…", j ? (j.bear ? `${esc(j.bear.name)}${j.bear.layer ? `, ${j.bear.mode} in ${esc(j.bear.layer)}` : ""} ${j.limB ? verdictBadge(j.okB, `at least ${fmt(j.limB, 1)}`, `under ${fmt(j.limB, 1)}`) : ""}` : "not checked: see Checks") : "working it out", j ? (j.okB ? "main" : "main bad") : ""],
    [`At the query point`, `${mm(now.total)} mm`, `after ${yrs(nowT())} · ${mm(fin.total)} mm at ${yrs(life())}`],
    [`Immediate`, `${mm(r.immediate)} mm`, `elastic, as the loads go on`],
    [`Primary consolidation`, `${mm(r.primary)} mm`, Math.abs(r.primary) > 1e-9 ? `${fmt(now.U * 100, 0)}% done now · 90% ${t90 > 0 ? `after ${yrs(t90 + (r.stages.at(-1)?.t || 0))}` : "straight away"}` : "no consolidating layer under load"],
    [`Creep`, `${mm(fin.secondary)} mm`, `secondary compression by ${yrs(life())}`],
  ].map(([k, v, s, cls]) => `<div class="kpi ${cls || ""}"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
}

function renderLegend() {
  const g = state.grid;
  $("#legend").innerHTML = state.view === "plan" && g
    ? `<div><div>Total settlement after ${yrs(nowT())} (mm)</div><div class="ramp" style="background:${rampCSS()}"></div><div class="ends"><span>0</span><span>${mm(g.max)}</span></div></div>`
    : `<span><b>A–A′</b> ${sectionLine().along === "x" ? `along x at y = ${fmt(sectionLine().at, 1)} m` : `along y at x = ${fmt(sectionLine().at, 1)} m`}</span><span><i style="background:var(--critical)"></i>Settled ground after ${yrs(nowT())}, drawn deeper than scale</span><span><i style="background:var(--series-2)"></i>Δσ as a share of the largest on the section</span><span><i style="background:var(--water)"></i>Water table</span>`;
}

let planFrame = null;
function renderView() {
  const plan = $("#plan"), sec = $("#sectionHost");
  $$("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
  plan.classList.toggle("hidden", state.view !== "plan");
  sec.classList.toggle("hidden", state.view !== "section");
  renderLegend();
  if (state.view === "plan") {
    planFrame = drawPlan(plan, state.project, state.grid, { query: state.project.query, section: sectionLine() });
  } else {
    const box = $("#view").getBoundingClientRect();
    sec.innerHTML = sectionView(state.project, sectionLine(), state.grid, box);
  }
}

const TABS = [
  ["found", "Foundations"], ["time", "Time"], ["depth", "With depth"], ["layers", "Layers"], ["rows", "Sub-layers"], ["checks", "Checks"], ["verify", "Verification"], ["about", "Methods"],
];
function renderTabs() {
  const n = allChecks().filter((x) => x.level !== "info").length;
  $("#dtabs").innerHTML = TABS.map(([k, name]) => `<button role="tab" data-tab="${k}" aria-selected="${state.tab === k}">${name}${k === "checks" && n ? ` <span class="pill warn">${n}</span>` : ""}</button>`).join("");
}

function renderPanel() { $("#dpanel").innerHTML = panelHTML(state.tab); }
const bearingNotes = () => (state.bearing || []).flatMap((b, i) => {
  const n = state.project.loads[i]?.name || `Load ${i + 1}`, lim = +state.project.limits.fos;
  if (!b) return [];
  if (!b.checked) return [{ level: "warning", text: `${n}: bearing is not checked, because ${b.why}.` }];
  const out = [];
  if (lim > 0 && b.fos < lim) out.push({ level: b.fos < 1 ? "critical" : "warning", text: `${n}: the bearing safety factor is ${fosText(b.fos)}, under the ${fmt(lim, 1)} asked for (${b.mode} in ${b.layer}: the ground can carry ${fmt(b.qult, 0)} kPa net and ${fmt(b.qnet, 0)} kPa is applied). ${b.fos < 1 ? "The ground fails before it settles: the settlement shown means nothing." : "Widen or deepen the foundation, or lighten it."}` });
  if (b.stacked && b.gain > 0) out.push({ level: "info", text: `${n}: it stands on an earlier load, so bearing is checked with both on the ground, and the clay is given the ${fmt(b.gain, 0)} kPa of strength it has gained by the time it goes on.` });
  if (b.partial) out.push({ level: "warning", text: `${n}: a layer under it has no strength given, so it was left out of the bearing check.` });
  return out;
});
const allChecks = () => [...checks(state.project), ...bearingNotes(), ...resultChecks(state.project, state.res)];

function foundationsHTML(which = "life") {
  const f = state.found, p = state.project, lim = p.limits;
  if (!f) return `<div class="note">Working out the foundations…</div>`;
  const t = which === "life" ? life() : nowT(), rows = f[which], between = which === "life" ? f.betweenLife : f.betweenNow;
  const limS = +lim.total > 0 ? +lim.total / 1000 : Infinity, limT = +lim.tilt > 0 ? 1 / +lim.tilt : Infinity;
  const body = rows.map((x) => {
    const l = p.loads[x.index];
    if (x.off) return `<tr class="muted"><td>${esc(x.name)}</td><td colspan="9">switched off</td></tr>`;
    const okS = x.governing <= limS + 1e-9, okT = x.tilt <= limT + 1e-12;
    const b = (state.bearing || [])[x.index], okB = !b || !b.checked || !(+lim.fos > 0) || b.fos >= +lim.fos - 1e-9;
    return `<tr><td><b>${esc(x.name)}</b><div class="note">${esc(LOAD_NAMES[l.type] || l.type)}${l.rigid && x.rigid !== null ? ", rigid" : ""}</div></td>
      <td class="num">${fmt(foundingDepth(l), 2)}</td><td class="num">${fmt(appliedPressure(l, overburden), 0)}</td>
      <td class="num">${x.rigid !== null ? mm(x.rigid, 1) : mm(x.centre, 1)}</td><td class="num">${mm(x.max, 1)}</td><td class="num">${mm(x.min, 1)}</td><td class="num">${mm(x.diff, 1)}</td>
      <td class="num">${oneIn(x.tilt)}</td><td class="num">${b && b.checked ? `${fosText(b.fos)}${b.layer ? `<div class="note">${b.mode}, ${esc(b.layer)}</div>` : ""}` : "–"}</td><td>${okS && okT && okB ? `<span class="pill good">✓ within</span>` : `<span class="pill bad">✕ ${!okB ? "bearing" : !okS ? "settlement" : "tilt"}</span>`}</td></tr>`;
  }).join("");
  const live = rows.filter((x) => !x.off);
  const bt = live.length > 1 ? `<p class="explain" style="margin-top:10px">Between foundations, the steepest slope is <b>${oneIn(between.tilt)}</b>${between.a ? `, from ${esc(between.a)} to ${esc(between.b)} (${mm(between.diff, 1)} mm over ${fmt(between.d, 1)} m)` : ""}. ${!(+lim.tilt > 0) ? "" : between.tilt <= limT + 1e-12 ? `<span class="pill good">✓ flatter than ${tiltLimit()}</span>` : `<span class="pill bad">✕ steeper than ${tiltLimit()}</span>`}</p>` : "";
  return `<div class="table-scroll"><table class="tight"><thead><tr><th>Foundation</th><th class="num">Founded at (m)</th><th class="num">Pressure (kPa)</th><th class="num">Settlement (mm)</th><th class="num">Most (mm)</th><th class="num">Least (mm)</th><th class="num">Differential (mm)</th><th class="num">Tilt</th><th class="num">Bearing safety</th><th>Against ${fmt(+lim.total, 0)} mm${+lim.tilt > 0 ? `, ${tiltLimit()}` : ""}${+lim.fos > 0 ? `, ${fmt(+lim.fos, 1)}` : ""}</th></tr></thead><tbody>${body}</tbody></table></div>
    ${bt}
    <p class="note" style="margin-top:8px">After ${yrs(t)}. Settlement is at the centre of a flexible foundation and the even settlement of a rigid one. Tilt is the steepest slope from the centre to an edge, or the lean of a rigid foundation. Bearing safety is the net pressure the ground can carry over the net pressure applied. The plan and the section show the ground as it would settle under flexible loads.</p>`;
}

function panelHTML(tab) {
  const r = state.res, p = state.project;
  if (!r) return `<div class="note">Nothing to show yet.</div>`;
  if (tab === "found") {
    return `<div class="seg" style="max-width:360px;margin-bottom:8px" role="group" aria-label="When">
      <button type="button" data-foundwhen="life" aria-pressed="${state.foundWhen !== "now"}">At design life (${yrs(life())})</button><button type="button" data-foundwhen="now" aria-pressed="${state.foundWhen === "now"}">At the time shown (${yrs(nowT())})</button></div>
      ${foundationsHTML(state.foundWhen === "now" ? "now" : "life")}`;
  }
  if (tab === "time") {
    const keyTimes = [0.1, 0.5, 1, 2, 5, 10, 25, 50, 100].filter((t) => t <= life());
    if (!keyTimes.includes(life())) keyTimes.push(life());
    return `${timeChart(state.curve, { t: nowT(), now: settlementAt(r, nowT()), stages: r.stages })}
      <div class="table-scroll" style="margin-top:12px"><table class="tight"><thead><tr><th>Time</th><th class="num">Immediate (mm)</th><th class="num">Primary (mm)</th><th class="num">Creep (mm)</th><th class="num">Total (mm)</th><th class="num">Primary done</th></tr></thead>
      <tbody>${keyTimes.map((t) => { const s = settlementAt(r, t); return `<tr><td>${yrs(t)}</td><td class="num">${mm(s.immediate, 1)}</td><td class="num">${mm(s.primary, 1)}</td><td class="num">${mm(s.secondary, 1)}</td><td class="num"><b>${mm(s.total, 1)}</b></td><td class="num">${fmt(s.U * 100, 0)}%</td></tr>`; }).join("")}</tbody></table></div>`;
  } else if (tab === "depth") {
    return `<div class="seg" style="max-width:320px;margin-bottom:8px" role="group" aria-label="What to plot">
      <button type="button" data-depth="stress" aria-pressed="${state.depthMode === "stress"}">Stresses</button><button type="button" data-depth="strain" aria-pressed="${state.depthMode === "strain"}">Strains</button></div>
      ${depthChart(p, r, state.depthMode)}`;
  } else if (tab === "layers") {
    const fin = (lr) => { const one = { ...r, layers: [lr] }; return settlementAt(one, life()); };
    const total = settlementAt(r, life()).total || 1;
    return `<div class="table-scroll"><table class="tight"><thead><tr><th>Layer</th><th class="num">Depth (m)</th><th class="num">Immediate (mm)</th><th class="num">Primary (mm)</th><th class="num">Creep at ${yrs(life())} (mm)</th><th class="num">90% consolidated</th><th class="num">Share</th></tr></thead><tbody>
      ${r.layers.map((lr, i) => { const f = fin(lr); const share = (f.total / total) * 100; return `<tr><td><span class="swatch" style="background:${soilColour(lr.layer, i)}"></span>${esc(lr.name)}</td><td class="num">${fmt(lr.top, 2)}–${fmt(lr.bottom, 2)}</td><td class="num">${mm(lr.immediate, 1)}</td><td class="num">${mm(lr.primary, 1)}</td><td class="num">${mm(f.secondary, 1)}</td><td class="num">${lr.layer.consolidating && lr.primary > 0 ? yrs(timeTo(lr.layer, 0.9)) : "–"}</td><td class="num">${fmt(share, 0)}%</td></tr>`; }).join("")}
      </tbody><tfoot><tr><td>All layers</td><td></td><td class="num">${mm(r.immediate, 1)}</td><td class="num">${mm(r.primary, 1)}</td><td class="num">${mm(settlementAt(r, life()).secondary, 1)}</td><td></td><td class="num">100%</td></tr></tfoot></table></div>
      <p class="note" style="margin-top:8px">Times to 90% are from when each load goes on. Creep starts once a layer is 95% consolidated under the last stage.</p>`;
  } else if (tab === "rows") {
    return `<div class="table-scroll"><table class="tight"><thead><tr><th>Layer</th><th class="num">z (m)</th><th class="num">u0 (kPa)</th><th class="num">σ'v0 (kPa)</th><th class="num">σ'p (kPa)</th><th class="num">Δσ (kPa)</th><th class="num">σ'f (kPa)</th><th class="num">ε imm. (%)</th><th class="num">ε cons. (%)</th><th class="num">s (mm)</th></tr></thead><tbody>
      ${r.rows.map((x) => `<tr><td>${esc(x.name)}</td><td class="num">${fmt(x.z, 2)}</td><td class="num">${fmt(x.u0, 1)}</td><td class="num">${fmt(x.sv0, 1)}</td><td class="num">${x.sp === null ? "–" : fmt(x.sp, 1)}</td><td class="num">${fmt(x.dsig, 1)}</td><td class="num">${fmt(x.svf, 1)}</td><td class="num">${fmt(x.epsImm * 100, 3)}</td><td class="num">${fmt(x.epsCons * 100, 3)}</td><td class="num">${mm(x.sImm + x.sCons, 2)}</td></tr>`).join("")}
      </tbody></table></div>`;
  } else if (tab === "checks") {
    const c = allChecks();
    const conv = r.converged === null ? `<div class="note">Using ${r.subLayers} sub-layers per layer, as set in Analysis.</div>`
      : r.converged ? `<div class="ok">✓ Converged: with ${r.subLayers} sub-layers per layer the settlement changes by ${(r.change * 100).toFixed(2)}% on refining, under the 0.5% asked for.</div>` : "";
    return `<div class="checks">${conv}${c.length ? c.map((x) => `<div class="${x.level === "critical" ? "warn bad-text" : x.level === "info" ? "note" : "warn"}">${x.level === "critical" ? "✕" : x.level === "info" ? "ⓘ" : "▲"} ${esc(x.text)}</div>`).join("")
      : `<div class="ok">✓ Nothing to flag in the inputs.</div>`}</div>`;
  } else if (tab === "verify") {
    if (!state.verify) state.verify = runChecks();
    const v = state.verify, ok = v.filter((x) => x.pass).length;
    return `<div class="${ok === v.length ? "ok" : "warn"}" style="margin-bottom:10px">${ok === v.length ? "✓" : "▲"} ${ok} of ${v.length} checks agree with the reference. The same checks run on every change to the code.</div>
      <div class="table-scroll"><table class="tight"><thead><tr><th>What</th><th>Reference</th><th class="num">Expected</th><th class="num">GeoProMax</th><th></th></tr></thead><tbody>
      ${v.map((x) => `<tr><td>${esc(x.name)}<div class="note">${esc(x.group)}</div></td><td class="ink2">${esc(x.reference)}</td><td class="num">${fmtCheck(x.expected)} ${esc(x.unit)}</td><td class="num">${fmtCheck(x.got)} ${esc(x.unit)}</td><td>${x.pass ? `<span class="pill good">✓ agrees</span>` : `<span class="pill bad">✕ differs</span>`}</td></tr>`).join("")}
      </tbody></table></div>`;
  } else if (tab === "about") {
    return METHODS;
  }
  return "";
}
const fmtCheck = (v) => (Math.abs(v) < 1 ? v.toFixed(4) : v.toFixed(2));

const METHODS = `<div class="explain" style="display:grid;gap:10px;max-width:820px">
  <p><b>Stresses.</b> The increase in vertical stress Δσ is found from <b>Boussinesq</b> (a uniform elastic half-space) or <b>Westergaard</b> (a half-space reinforced by thin stiff layers, using the layer's Poisson's ratio). Rectangles are solved exactly with the corner method (Newmark 1935), so points outside a load are as exact as points under it. Circles, rings, polygons, turned footings and embankment side slopes are split into thin strips of the same area. Loads add together.</p>
  <p><b>Foundations.</b> A pad carries a column load P and a strip a wall load per metre; a building is storeys times a load per storey. A foundation below ground spreads its stress from its <b>founding depth</b>, and the soil above that level is not compressed by it. With <b>net pressure</b> on, the weight of the soil dug out is taken off; a load lighter than that soil makes the ground heave along Cr.</p>
  <p><b>Pile groups.</b> Tomlinson's equivalent raft: for friction piles the load acts at two thirds of the pile length, spread at 1 in 4 from the group; for end-bearing piles it acts at the toes over the group's own area.</p>
  <p><b>Rigid foundations.</b> A flexible load dishes; a stiff raft or footing settles evenly. A rigid foundation's even settlement is read at its characteristic points (0.74 of the half-width from the centre, 0.845 R for a circle), where flexible and rigid settlements agree, and its tilt is the lean between them.</p>
  <p><b>In-situ stresses.</b> σ'v0 = σv − u, with the unit weight above the water table and the saturated unit weight below it, and hydrostatic pore pressure (γw = 9.81 kN/m³).</p>
  <p><b>Immediate settlement.</b> Each sub-layer compresses by <code>Δσ·h / M</code>, with the constrained modulus <code>M = E(1−ν)/((1+ν)(1−2ν))</code>. E can grow with depth inside a layer. Set E to 0 to leave a layer out.</p>
  <p><b>Primary consolidation.</b> For layers that consolidate: σ'p = OCR·σ'v0 + POP. Then <code>Δe = Cr·log(σ'f/σ'v0)</code> while σ'f ≤ σ'p, <code>Cc·log(σ'f/σ'v0)</code> when the soil is normally consolidated, and <code>Cr·log(σ'p/σ'v0) + Cc·log(σ'f/σ'p)</code> across σ'p; the settlement is <code>Δe·h/(1+e0)</code>. A layer can use <code>mv·Δσ·h</code> instead, from oedometer tests.</p>
  <p><b>Rate.</b> Terzaghi's one-dimensional theory for each layer: <code>Tv = cv·t / Hdr²</code>, with Hdr half the layer for drainage through both faces and the whole layer for one. With <b>wick drains</b>, water also flows sideways to the drains (Hansbo 1981) and the two add by Carrillo's rule: <code>U = 1 − (1−Uv)(1−Ur)</code>. Loads that go on later (Applied at) are stages: each stage's extra settlement consolidates from its own time.</p>
  <p><b>Creep.</b> Once a layer is 95% consolidated under the last stage (at t95), it keeps settling by <code>Cα·h/(1+ep)·log(t/t95)</code>. Where the soil stays overconsolidated it creeps less, by Cα·Cr/Cc, because Cα/Cc is a constant of the soil (Mesri and Castro 1987).</p>
  <p><b>Convergence.</b> With sub-layers on automatic, each layer is cut finer and finer until the settlement changes by less than 0.5% from one refinement to the next. The Checks tab says how many it took, or warns if it did not get there.</p>
  <p><b>CSI SAFE link.</b> SAFE solves a raft on springs, and the right springs depend on how the ground settles under the raft's own pressures. So the two are solved in turn: SAFE's soil pressures become the load here (gathered into square cells that keep the total load), the settlement under each cell at the design life gives its spring, <code>k = pressure / settlement</code>, and SAFE runs again on those springs. The rounds stop when the springs change by less than the tolerance on average, and by less than three times it anywhere. Springs are banded into a few soil properties, because SAFE takes one subgrade modulus per property.</p>
  <p><b>Bearing capacity.</b> Before settlement, each foundation is checked against the ground failing under it, with the general bearing capacity equation: <code>q = c'·Nc·sc·dc + q'·Nq·sq·dq + ½·γ'·B·Nγ·sγ</code> drained, and <code>(π+2)·su·sc·dc</code> undrained for clays, the lower of the two governing (factors of Prandtl, Reissner and Vesic; depth factors of Hansen). The water table comes in through the effective stresses. Weaker layers within one footing width below the base are checked with the load spread at 2 to 1. The safety factor is the net pressure the ground can carry over the net pressure applied; 3 is usual for buildings and 1.5 for embankments. A load placed on top of an earlier one, such as a second stage of fill, is checked with both on the ground, and the clay below is given the strength it has gained by then: <code>Δsu = 0.22·U·Δσ</code> (Ladd 1991). Loads are taken as vertical and central, on level ground; the capacity of piles is not checked.</p>
  <p><b>Limits.</b> Each kind of structure comes with a usual limit on total settlement and on tilt (angular distortion), after Skempton and MacDonald (1956), Bjerrum (1963), Eurocode 7 Annex H and API 653 for tanks. They are starting points: set your own under Structure and limits. Tilt is checked across each foundation and between neighbouring ones.</p>
  <p class="note">Results are for design and checking by an engineer. One-dimensional strain is assumed; loads are vertical and central. Units: m, kN, kPa, years; settlement in mm.</p>
</div>`;

// ------------------------------------------------------------------ events on the answer

$("#dtabs").addEventListener("click", (ev) => { const b = ev.target.closest("[data-tab]"); if (!b) return; state.tab = b.dataset.tab; renderTabs(); renderPanel(); });
$("#dpanel").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-depth], [data-foundwhen]");
  if (!b) return;
  if (b.dataset.depth) state.depthMode = b.dataset.depth; else state.foundWhen = b.dataset.foundwhen;
  renderPanel();
});
$$("[data-view]").forEach((b) => b.addEventListener("click", () => { state.view = b.dataset.view; renderView(); }));

$("#plan").addEventListener("click", (ev) => {
  if (!planFrame || !state.grid) return;
  const r = ev.currentTarget.getBoundingClientRect();
  const [x, y] = planFrame.inv(ev.clientX - r.left, ev.clientY - r.top);
  const g = state.grid.g;
  if (x < g.x1 || x > g.x2 || y < g.y1 || y > g.y2) return;
  state.project.query = { x: +x.toFixed(1), y: +y.toFixed(1) };
  changed(true);
});
$("#plan").addEventListener("mousemove", (ev) => {
  const hv = $("#hover");
  if (!planFrame || !state.grid) { hv.classList.add("hidden"); return; }
  const r = ev.currentTarget.getBoundingClientRect();
  const [x, y] = planFrame.inv(ev.clientX - r.left, ev.clientY - r.top);
  const s = sample(state.grid, x, y);
  if (s === null) { hv.classList.add("hidden"); return; }
  hv.classList.remove("hidden");
  hv.innerHTML = `x ${fmt(x, 1)}, y ${fmt(y, 1)} m · <b>${mm(s)} mm</b>`;
});
$("#plan").addEventListener("mouseleave", () => $("#hover").classList.add("hidden"));

$("#tSlider").addEventListener("input", (ev) => {
  state.project.t = +tFromSlider(+ev.target.value).toPrecision(3);
  $("#tValue").textContent = yrs(nowT());
  renderVerdict(); renderKpis();
  if (state.tab === "time") renderPanel();
  askTime();
  scheduleSave();
});
let playStart = 0;
function playFrame(now) {
  if (!state.playing) return;
  const u = Math.min(1000, ((now - playStart) / 7000) * 1000);
  state.project.t = +tFromSlider(u).toPrecision(3);
  syncTimebar(); renderVerdict(); renderKpis(); askTime();
  if (u >= 1000) { stopPlay(); if (state.tab === "time") renderPanel(); return; }
  requestAnimationFrame(playFrame);
}
function stopPlay() { state.playing = false; $("#btnPlay").setAttribute("aria-pressed", "false"); }
$("#btnPlay").addEventListener("click", () => {
  if (state.playing) { stopPlay(); return; }
  state.playing = true; $("#btnPlay").setAttribute("aria-pressed", "true");
  state.view = "plan"; renderView();
  playStart = performance.now();
  requestAnimationFrame(playFrame);
});

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderView, 80); });

// the answer follows you down the page on a phone
new IntersectionObserver(([e]) => $("#fpill").classList.toggle("on", !e.isIntersecting)).observe($("#view"));
$("#fpill").addEventListener("click", () => $("#view").scrollIntoView({ behavior: "smooth", block: "start" }));

// ------------------------------------------------------------------ projects

async function openDrawer() {
  $("#drawer").classList.remove("hidden");
  const list = $("#projList");
  list.innerHTML = `<div class="note">Loading…</div>`;
  if (state.offline) { list.innerHTML = `<div class="note">Projects are kept on this device only here: the site could not be reached.</div>`; return; }
  try {
    const { projects } = await api("/projects");
    list.innerHTML = projects.length ? projects.map((p) => `<div class="proj ${p.id === state.id ? "current" : ""}" data-open="${p.id}"><span class="pn">${esc(p.name)}</span><span class="pm">version ${p.version}</span><span class="pm">${new Date(p.updated * 1000).toLocaleString()}</span><span><button class="btn btn-ghost btn-sm" data-hist="${p.id}">History</button> <button class="btn btn-ghost btn-sm" data-dup="${p.id}">Copy</button> <button class="btn btn-danger btn-sm" data-del="${p.id}">Delete</button></span></div>`).join("")
      : `<div class="note">No projects yet. Everything you do is saved as you go.</div>`;
  } catch (e) { list.innerHTML = `<div class="note">Projects could not be listed (${esc(e.message)}).</div>`; }
}
$("#btnProjects").addEventListener("click", openDrawer);
$("#drawer").addEventListener("click", async (ev) => {
  if (ev.target === $("#drawer") || ev.target.closest("[data-close]")) { $("#drawer").classList.add("hidden"); return; }
  const tpl = ev.target.closest("[data-new]");
  if (tpl) { newProject(tpl.dataset.new); return; }
  const del = ev.target.closest("[data-del]"), dup = ev.target.closest("[data-dup]"), open = ev.target.closest("[data-open]");
  const hist = ev.target.closest("[data-hist]"), back = ev.target.closest("[data-restore]");
  try {
    if (hist) {
      ev.stopPropagation();
      const row = hist.closest(".proj"), old = row.nextElementSibling;
      if (old?.classList.contains("versions")) { old.remove(); return; }
      const { versions } = await api(`/projects/${hist.dataset.hist}/versions`);
      row.insertAdjacentHTML("afterend", `<div class="versions">${versions.length ? versions.map((v) => `<div class="ver"><span>Version ${v.version}</span><span class="pm">${new Date(v.saved * 1000).toLocaleString()}</span><button class="btn btn-ghost btn-sm" data-restore="${hist.dataset.hist}:${v.id}">Bring back</button></div>`).join("") : `<div class="note">No earlier versions yet: each save keeps the one before it (up to 30).</div>`}</div>`);
      return;
    }
    if (back) {
      ev.stopPropagation();
      const [pid, vid] = back.dataset.restore.split(":");
      const r = await api(`/projects/${pid}/versions/${vid}/restore`, { method: "POST", body: "{}" });
      loadProject(r); $("#drawer").classList.add("hidden"); toast("Earlier version brought back. The one before is in History too."); return;
    }
    if (del) {
      ev.stopPropagation();
      if (!confirm("Delete this project? Its earlier versions go with it.")) return;
      await api(`/projects/${del.dataset.del}`, { method: "DELETE" });
      if (+del.dataset.del === state.id) state.id = null;
      openDrawer(); return;
    }
    if (dup) { ev.stopPropagation(); const r = await api(`/projects/${dup.dataset.dup}/duplicate`, { method: "POST", body: "{}" }); loadProject(r); $("#drawer").classList.add("hidden"); return; }
    if (open) { const r = await api(`/projects/${open.dataset.open}`); loadProject(r); $("#drawer").classList.add("hidden"); }
  } catch (e) { toast(e.message, true); }
});
$("#fileOpen").addEventListener("change", async (ev) => {
  const f = ev.target.files?.[0];
  ev.target.value = "";
  if (!f) return;
  try {
    const data = JSON.parse(await f.text());
    if (!Array.isArray(data.layers) || !Array.isArray(data.loads)) throw new Error("this is not a GeoProMax project file");
    state.id = null;
    state.project = complete(data);
    startOver();
    $("#drawer").classList.add("hidden");
    save();
    toast(`Opened ${f.name} as a new project.`);
  } catch (e) { toast("Could not open the file: " + e.message, true); }
});

function startOver() {
  state.grid = null; state.verify = null; state.openLoad = null; state.safeDraft = null;
  $("#projectName").value = state.project.name;
  renderInputs(); analyse(); resetHistory();
}
function loadProject(r) {
  state.id = r.id; state.version = r.version;
  state.project = complete(r.data);
  history.replaceState(null, "", `${G.base}p/${r.id}`);
  $("#saveState").textContent = "Saved"; $("#saveState").className = "save-state saved";
  startOver();
}
function newProject(template) {
  state.id = null;
  state.project = complete({ template });
  $("#drawer").classList.add("hidden");
  startOver(); save();
}
$("#projectName").addEventListener("input", (ev) => { state.project.name = ev.target.value; scheduleSave(); });

// ------------------------------------------------------------------ report and downloads

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
const safeName = () => (state.project.name || "GeoProMax").replace(/[^\w\- ]+/g, "").trim() || "GeoProMax";

function csv() {
  const r = state.res, q = (v) => (typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : Number.isFinite(v) ? +v.toPrecision(6) : "");
  const lines = [[`GeoProMax settlement: ${state.project.name}`], [`Query point x (m)`, +state.project.query.x, `y (m)`, +state.project.query.y], [],
    ["Layer", "z (m)", "u0 (kPa)", "sv0' (kPa)", "sp' (kPa)", "dsigma (kPa)", "sf' (kPa)", "strain immediate (%)", "strain consolidation (%)", "settlement (mm)"],
    ...r.rows.map((x) => [x.name, x.z, x.u0, x.sv0, x.sp ?? "", x.dsig, x.svf, x.epsImm * 100, x.epsCons * 100, (x.sImm + x.sCons) * 1000]),
    [], ["Time (years)", "Immediate (mm)", "Primary (mm)", "Creep (mm)", "Total (mm)", "Primary done (%)"],
    ...state.curve.map((s) => [s.t, s.immediate * 1000, s.primary * 1000, s.secondary * 1000, s.total * 1000, s.U * 100])];
  download(`${safeName()}.csv`, lines.map((l) => l.map(q).join(",")).join("\r\n"), "text/csv");
}

function printReport() {
  const p = state.project, r = state.res;
  if (!r) return;
  // A report is printed on white paper: draw it in the light theme, then put the theme back.
  const theme = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute("data-theme", "light");
  const restore = () => {
    if (theme) document.documentElement.setAttribute("data-theme", theme); else document.documentElement.removeAttribute("data-theme");
    window.removeEventListener("afterprint", restore);
    renderView();
  };
  window.addEventListener("afterprint", restore);
  const now = settlementAt(r, nowT()), fin = settlementAt(r, life());
  // the plan as an image, drawn off screen at a print-friendly size
  const c = document.createElement("canvas");
  c.style.cssText = "position:fixed;left:-9999px;top:0;width:900px;height:620px";
  document.body.appendChild(c);
  drawPlan(c, p, state.grid, { query: p.query, section: sectionLine() });
  const planImg = state.grid ? c.toDataURL("image/png") : "";
  c.remove();
  const kv = (k, v) => `<div>${k}<b>${v}</b></div>`;
  const layerRows = p.layers.map((l) => {
    const cons = !l.consolidating ? "–" : `${l.model === "mv" ? `mv ${l.mv} m²/MN` : `Cc ${l.Cc}, Cr ${l.Cr}, e0 ${l.e0}, OCR ${l.OCR}${+l.POP ? `, POP ${l.POP} kPa` : ""}`}, cv ${l.cv} m²/yr, Cα ${l.Ca}, ${l.drainage === "single" ? "one face" : "both faces"}${l.drains?.on ? `, wick drains at ${l.drains.spacing} m (${l.drains.pattern === "square" ? "square" : "triangular"}), ch ${l.drains.ch} m²/yr` : ""}`;
    return `<tr><td>${esc(l.name)}</td><td>${fmt(+l.thickness, 2)}</td><td>${l.gamma} / ${l.gammaSat}</td><td>${l.E}${+l.Einc ? ` + ${l.Einc}/m` : ""}</td><td>${l.nu}</td><td>φ' ${+l.phi || 0}°, c' ${+l.c || 0} kPa${l.consolidating && +l.su > 0 ? `, su ${l.su} kPa` : ""}</td><td>${cons}</td></tr>`;
  }).join("");
  const loadRows = p.loads.map((l) => { const [cx, cy] = loadCentre(l); return `<tr><td>${esc(l.name)}${l.on === false ? " (off)" : ""}</td><td>${esc(LOAD_NAMES[l.type] || l.type)}${l.rigid ? ", rigid" : ""}</td><td>(${fmt(cx, 2)}, ${fmt(cy, 2)})</td><td>${esc(describeLoad(l))}</td><td>${fmt(foundingDepth(l), 2)}</td><td>${fmt(grossPressure(l), 1)}${l.net ? ` (net ${fmt(appliedPressure(l, overburden), 1)})` : ""}</td><td>${fmt(+l.t0 || 0, 2)}</td></tr>`; }).join("");
  const c2 = allChecks();
  const j = judge(), lim = p.limits, st = structureOf(p.limits.preset);
  const conv = r.converged ? `converged with ${r.subLayers} sub-layers per layer (change on refining ${(r.change * 100).toFixed(2)}%)` : `${r.subLayers} sub-layers per layer`;
  const ver = runChecks(), vok = ver.filter((x) => x.pass).length;
  $("#report").innerHTML = `
    <h1>${esc(p.name)}</h1>
    <p class="rnote">GeoProMax ${esc(G.version || "")} · settlement analysis · ${new Date().toLocaleDateString()}${G.me?.name ? ` · ${esc(G.me.name)}` : ""}</p>
    ${j ? `<h2>Against the limits at ${yrs(life())}</h2>
    <p class="rverdict ${j.okS && j.okT && j.okB ? "pass" : "fail"}"><b>${j.okS && j.okT && j.okB ? "✓ Within the limits" : "✕ Over the limits"}</b> · ${esc(st[1])}: ${fmt(+lim.total, 0)} mm${+lim.tilt > 0 ? ` and ${tiltLimit()}` : ", tilt not checked"}${+lim.fos > 0 ? `, bearing safety at least ${fmt(+lim.fos, 1)}` : ""}</p>
    <div class="kv">${kv("Largest settlement", `${mm(j.worst.governing)} mm`)}${kv("Where", esc(j.worst.name))}${kv("Steepest tilt", oneIn(j.tilt))}${kv("Where", esc(j.tiltWhere))}${j.bear ? kv("Lowest bearing safety", fosText(j.bear.fos)) + kv("Where", esc(j.bear.name)) : ""}</div>
    <h2>Foundations at ${yrs(life())}</h2>${foundationsHTML("life")}` : ""}
    <h2>At the query point (${fmt(+p.query.x, 2)}, ${fmt(+p.query.y, 2)})</h2>
    <div class="kv">${kv(`After ${yrs(nowT())}`, `${mm(now.total)} mm`)}${kv(`At design life (${yrs(life())})`, `${mm(fin.total)} mm`)}${kv("Immediate", `${mm(r.immediate)} mm`)}${kv("Primary consolidation", `${mm(r.primary)} mm`)}${kv(`Creep by ${yrs(life())}`, `${mm(fin.secondary)} mm`)}${kv("Largest on the plan now", state.grid ? `${mm(state.grid.max)} mm` : "–")}</div>
    ${planImg ? `<h2>Plan: total settlement after ${yrs(nowT())} (mm)</h2><img src="${planImg}" alt="Plan of settlement">` : ""}
    <h2>Settlement with time</h2>${timeChart(state.curve, { t: nowT(), now, stages: r.stages })}
    <div class="page"></div>
    <h2>Cross-section A–A′</h2>${sectionView(p, sectionLine(), state.grid, { width: 900, height: 460 }, { titles: true })}
    <h2>Stresses with depth</h2>${depthChart(p, r, "stress")}
    <div class="page"></div>
    <h2>Inputs</h2>
    <p class="rnote">Water table ${fmt(+p.waterTable, 2)} m below ground · ${p.method === "westergaard" ? "Westergaard" : "Boussinesq"} stresses · ${conv} · design life ${yrs(life())}</p>
    <table><thead><tr><th>Layer</th><th>Thickness (m)</th><th>γ / γsat (kN/m³)</th><th>E (kPa)</th><th>ν</th><th>Strength</th><th>Consolidation</th></tr></thead><tbody>${layerRows}</tbody></table>
    <table style="margin-top:8pt"><thead><tr><th>Foundation or load</th><th>Kind</th><th>Centre (m)</th><th>Size</th><th>Founded at (m)</th><th>Pressure (kPa)</th><th>Applied at (yr)</th></tr></thead><tbody>${loadRows}</tbody></table>
    <h2>Results by layer</h2>${panelHTML("layers")}
    <h2>Checks</h2>${c2.length ? `<ul>${c2.map((x) => `<li>${esc(x.text)}</li>`).join("")}</ul>` : `<p>Nothing to flag in the inputs.</p>`}
    <p class="rnote">Verification: ${vok} of ${ver.length} checks against closed-form solutions and hand calculations agree. Methods: Boussinesq / Westergaard stresses (corner method) from the founding level, constrained-modulus immediate settlement, Cc–Cr or mv consolidation with Terzaghi's rate (and Hansbo's for wick drains), Cα creep after t95, Tomlinson's equivalent raft for pile groups.</p>`;
  window.print();
}
$("#btnReport").addEventListener("click", (ev) => {
  ev.stopPropagation();
  const m = $("#reportMenu"), open = m.classList.toggle("hidden");
  $("#btnReport").setAttribute("aria-expanded", String(!open));
});
document.addEventListener("click", (ev) => { if (!ev.target.closest(".menu-wrap")) $("#reportMenu").classList.add("hidden"); });
$("#reportMenu").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-report]");
  if (!b) return;
  $("#reportMenu").classList.add("hidden");
  if (b.dataset.report === "pdf") printReport();
  if (b.dataset.report === "csv") csv();
  if (b.dataset.report === "json") download(`${safeName()}.json`, JSON.stringify(state.project, null, 2), "application/json");
});

// ------------------------------------------------------------------ start

const inputs = $("#inputs");
inputs.addEventListener("input", (ev) => { if (ev.target.tagName === "SELECT" || ev.target.type === "checkbox") return; onInput(ev); });
inputs.addEventListener("change", (ev) => { if (ev.target.tagName === "SELECT" || ev.target.type === "checkbox") onInput(ev); });
inputs.addEventListener("click", onClick);
$("#btnUndo").addEventListener("click", () => stepHistory(true));
$("#btnRedo").addEventListener("click", () => stepHistory(false));

document.addEventListener("keydown", (ev) => {
  const typing = ev.target.closest?.("input, textarea, select");
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z" && !typing) { ev.preventDefault(); stepHistory(!ev.shiftKey); return; }
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y" && !typing) { ev.preventDefault(); stepHistory(false); return; }
  if (ev.key === "Escape") { $("#reportMenu").classList.add("hidden"); $("#drawer").classList.add("hidden"); }
});

async function start() {
  let opened = null;
  try {
    if (G.openId) opened = await api(`/projects/${G.openId}`);
    else {
      const { projects } = await api("/projects");
      if (projects.length) opened = await api(`/projects/${projects[0].id}`);
    }
  } catch (e) {
    state.offline = true;
  }
  if (opened) { loadProject(opened); return; }
  let last = null;
  try { last = JSON.parse(localStorage.getItem("geopromax-last") || "null"); } catch (e) { /* none */ }
  state.project = complete(last?.data || { template: "building" });
  startOver();
  if (!state.offline) save();
}
start();

export { TEMPLATES };
