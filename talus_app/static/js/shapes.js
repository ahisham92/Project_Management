// Talus — the drawable shapes of a project: layer polygons, water, the sliding mass.
import { yAt, lower, upper, flat } from "../engine/geometry.js";

export function extent(geometry) {
  const g = geometry.ground;
  return { x0: g[0][0], x1: g[g.length - 1][0], y0: geometry.bottom, y1: Math.max(...g.map((p) => p[1])) };
}

/** [{ name, kind, poly }] from the top layer down, each a closed polygon in the user's frame. */
export function layerPolys(geometry) {
  const { x0, x1 } = extent(geometry);
  const bottom = flat(geometry.bottom, x0, x1);
  const L = geometry.layers;
  const tops = [];
  let T = geometry.ground.map((p) => [...p]);
  tops.push(T);
  for (let k = 1; k < L.length; k++) {
    T = lower(T, L[k].top, x0, x1);
    tops.push(T);
  }
  return L.map((layer, k) => {
    const top = upper(tops[k], bottom, x0, x1);
    const bot = k + 1 < L.length ? upper(tops[k + 1], bottom, x0, x1) : bottom;
    return { name: layer.mat.name, mat: layer.mat, poly: [...top, ...bot.slice().reverse()], top, bot };
  });
}

/** Water standing above the ground (polygon), or null. */
export function pondPoly(geometry, piezo) {
  if (!piezo) return null;
  const { x0, x1 } = extent(geometry);
  const top = upper(piezo, geometry.ground, x0, x1);
  let any = false;
  for (const [x, y] of top) if (y > yAt(geometry.ground, x) + 1e-6) any = true;
  if (!any) return null;
  const bot = geometry.ground;
  return [...top, ...bot.slice().reverse()];
}

/** The sliding mass: ground between the ends of the slip surface, back along the surface. */
export function massPoly(geometry, slip) {
  const a = slip[0][0], b = slip[slip.length - 1][0];
  const top = [[a, yAt(geometry.ground, a)]];
  for (const p of geometry.ground) if (p[0] > a && p[0] < b) top.push([...p]);
  top.push([b, yAt(geometry.ground, b)]);
  return [...top, ...slip.slice().reverse()];
}

const PALETTE = [
  [/armour|unit/i, "#7d8187"], [/underlayer/i, "#9aa0a6"], [/concrete/i, "#b8bcc2"],
  [/rock fill|quarry/i, "#8d8a83"], [/weathered rock/i, "#a08f7a"],
  [/soft clay/i, "#7a6650"], [/firm clay/i, "#8a6a4a"], [/stiff clay/i, "#6f5236"], [/clay fill/i, "#93724f"],
  [/silt/i, "#a89272"], [/loose sand/i, "#d9c08f"], [/dense sand|gravel/i, "#bfa173"], [/sand/i, "#cfb27e"],
  [/fill/i, "#a4926b"],
];
export function colourOf(name, k = 0) {
  for (const [re, c] of PALETTE) if (re.test(name)) return c;
  return ["#b08a5a", "#8f6b43", "#c9a874", "#6f5a44"][k % 4];
}

/** Red below 95% of the target, amber just short of it, green once it is met. */
export function fosColour(F, target) {
  const r = F / target;
  if (!Number.isFinite(r)) return "#898781";
  if (r < 0.95) return "#d03b3b";
  if (r < 1 - 1e-9) return "#e07a00";
  return "#0ca30c";
}

/** Continuous colour for trial surfaces from the minimum F (red) up to 2× it (blue-green). */
export function rampColour(F, Fmin) {
  const t = Math.max(0, Math.min(1, (F / Fmin - 1) / 0.6));
  const stops = [[208, 59, 59], [250, 178, 25], [12, 163, 12], [42, 120, 214]];
  const s = t * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(s)), f = s - i;
  const c = stops[i].map((v, j) => Math.round(v + (stops[i + 1][j] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
