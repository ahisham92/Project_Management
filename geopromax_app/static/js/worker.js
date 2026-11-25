// The heavy work, off the page's thread: settlement over the plan grid and along
// the section. Each grid point's result is kept, so moving the time slider only
// re-reads them (fast) instead of solving the stresses again.

import { computePoint, settlementAt, stagesOf, stressSection } from "../engine/settlement.js";
import { buildRects } from "../engine/stress.js";

let kept = null; // { id, g, points: [result], line: {xs, results} }

function values(t) {
  const { g, points } = kept;
  const v = new Float64Array(points.length);
  let min = Infinity, max = -Infinity;
  for (let i = 0; i < points.length; i++) {
    const s = settlementAt(points[i], t).total;
    v[i] = s; if (s < min) min = s; if (s > max) max = s;
  }
  // steepest slope between neighbouring grid points (angular distortion)
  let tilt = 0;
  const dx = (g.x2 - g.x1) / (g.nx - 1), dy = (g.y2 - g.y1) / (g.ny - 1);
  for (let j = 0; j < g.ny; j++) for (let i = 0; i < g.nx; i++) {
    const a = v[j * g.nx + i];
    if (i + 1 < g.nx) tilt = Math.max(tilt, Math.abs(v[j * g.nx + i + 1] - a) / dx);
    if (j + 1 < g.ny) tilt = Math.max(tilt, Math.abs(v[(j + 1) * g.nx + i] - a) / dy);
  }
  const line = kept.line ? kept.line.results.map((r) => settlementAt(r, t).total) : null;
  return { values: v, min, max, tilt, line };
}

self.onmessage = (ev) => {
  const m = ev.data;
  try {
    if (m.kind === "grid") {
      const { project: p, g, section } = m;
      const stages = stagesOf(p.loads).map((s) => ({ ...s, rects: buildRects(s.loads) }));
      // the same sub-layers as the query point, so the plan and the cards agree
      const subLayers = Math.max(2, Math.min(+p.subLayers || 10, 12));
      const points = new Array(g.nx * g.ny);
      for (let j = 0; j < g.ny; j++) {
        const y = g.y1 + ((g.y2 - g.y1) * j) / (g.ny - 1);
        for (let i = 0; i < g.nx; i++) {
          const x = g.x1 + ((g.x2 - g.x1) * i) / (g.nx - 1);
          points[j * g.nx + i] = strip(computePoint(p, x, y, { stages, subLayers }));
        }
        if (j % 4 === 0) self.postMessage({ id: m.id, kind: "progress", done: (j + 1) / g.ny });
      }
      // the section line: settlement along it and the stress bulbs under it
      const n = 81, xs = [], results = [];
      for (let i = 0; i < n; i++) {
        const u = section.a1 + ((section.a2 - section.a1) * i) / (n - 1);
        const [x, y] = section.along === "x" ? [u, section.at] : [section.at, u];
        xs.push(u);
        results.push(strip(computePoint(p, x, y, { stages, subLayers })));
      }
      const sp = section.along === "x" ? p : { ...p, loads: p.loads.map(swapXY) };
      const bulbs = stressSection(sp, section.at, section.a1, section.a2, section.depth, 61, 41);
      kept = { id: m.id, g, points, line: { xs, results } };
      self.postMessage({ id: m.id, kind: "grid", g, xs, bulbs, ...values(m.t) });
    } else if (m.kind === "time" && kept) {
      self.postMessage({ id: m.id, kind: "time", g: kept.g, xs: kept.line.xs, ...values(m.t) });
    }
  } catch (e) {
    self.postMessage({ id: m.id, kind: "error", message: String(e && e.message || e) });
  }
};

// Keep only what settlementAt needs.
function strip(r) {
  return { stages: r.stages, layers: r.layers.map((l) => ({ layer: l.layer, stage: l.stage, primary: l.primary, creep: l.creep, t95: l.t95 })) };
}

// A section along y is the same as one along x with the plan turned over.
function swapXY(l) {
  const o = { ...l, x: l.y, y: l.x };
  if (l.type === "rect") { o.B = l.L; o.L = l.B; }
  if (l.type === "embankment") o.axis = l.axis === "x" ? "y" : "x";
  return o;
}
