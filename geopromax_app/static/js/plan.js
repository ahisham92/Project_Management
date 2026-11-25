// The plan view: settlement as a coloured map with contour lines, the loads'
// outlines, the query point and the section line. Drawn on a canvas.

import { outline, loadCentre } from "../engine/stress.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const dark = () => matchMedia("(prefers-color-scheme: dark)").matches
  ? document.documentElement.getAttribute("data-theme") !== "light"
  : document.documentElement.getAttribute("data-theme") === "dark";

// Sequential blues, light to dark (dark to light in the dark theme).
const RAMP_LIGHT = ["#f3f7fc", "#d4e4f7", "#a9c9ef", "#75a8e4", "#4589d9", "#2a6fc4", "#1d549c", "#143b70"];
const RAMP_DARK = ["#121a24", "#15294a", "#1b3d6e", "#245494", "#2f6dbd", "#4a8ae0", "#7aaced", "#b4d0f6"];
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

export function colourAt(u) {
  const ramp = (dark() ? RAMP_DARK : RAMP_LIGHT).map(hex);
  const x = Math.min(1, Math.max(0, u)) * (ramp.length - 1);
  const i = Math.min(ramp.length - 2, Math.floor(x)), f = x - i;
  return ramp[i].map((c, k) => Math.round(c + (ramp[i + 1][k] - c) * f));
}
export const rampCSS = () => `linear-gradient(90deg, ${(dark() ? RAMP_DARK : RAMP_LIGHT).join(", ")})`;

/** Round contour levels (in mm) between 0 and max. */
export function levels(maxMM, n = 8) {
  if (!(maxMM > 0)) return [];
  const raw = maxMM / n, p = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * p).find((s) => s >= raw) || raw;
  const out = [];
  for (let v = step; v < maxMM - 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

/** Contour segments of a scalar field at one level (marching squares). */
export function contour(values, nx, ny, level) {
  const segs = [];
  const at = (i, j) => values[j * nx + i];
  const lerp = (a, b) => (level - a) / (b - a);
  for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    const a = at(i, j), b = at(i + 1, j), c = at(i + 1, j + 1), d = at(i, j + 1);
    const pts = [];
    if ((a < level) !== (b < level)) pts.push([i + lerp(a, b), j]);
    if ((b < level) !== (c < level)) pts.push([i + 1, j + lerp(b, c)]);
    if ((d < level) !== (c < level)) pts.push([i + lerp(d, c), j + 1]);
    if ((a < level) !== (d < level)) pts.push([i, j + lerp(a, d)]);
    if (pts.length === 2) segs.push(pts);
    else if (pts.length === 4) segs.push([pts[0], pts[1]], [pts[2], pts[3]]);
  }
  return segs;
}

/** Fit the plan extents into the canvas with equal scales. */
export function frame(canvas, g) {
  const r = canvas.getBoundingClientRect();
  const W = r.width, H = r.height, pad = { l: 46, r: 16, t: 16, b: 34 };
  const sx = (W - pad.l - pad.r) / (g.x2 - g.x1), sy = (H - pad.t - pad.b) / (g.y2 - g.y1);
  const s = Math.max(1e-6, Math.min(sx, sy));
  const w = (g.x2 - g.x1) * s, h = (g.y2 - g.y1) * s;
  const ox = pad.l + (W - pad.l - pad.r - w) / 2, oy = pad.t + (H - pad.t - pad.b - h) / 2;
  return {
    W, H, s, ox, oy, w, h,
    X: (x) => ox + (x - g.x1) * s,
    Y: (y) => oy + h - (y - g.y1) * s,
    inv: (px, py) => [g.x1 + (px - ox) / s, g.y1 + (oy + h - py) / s],
  };
}

function niceStep(span, target) {
  const raw = span / target, p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((k) => k * p).find((s) => s >= raw);
}

/** Draw everything. `grid` is the worker's answer; values in m. */
export function drawPlan(canvas, project, grid, opts = {}) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  if (!grid) return null;
  const g = grid.g, F = frame(canvas, g);
  const maxMM = Math.max(1e-9, grid.max * 1000);

  // the map, smoothed by drawing the grid as a small image scaled up
  const img = new ImageData(g.nx, g.ny);
  for (let j = 0; j < g.ny; j++) for (let i = 0; i < g.nx; i++) {
    const [r, gg, b] = colourAt((grid.values[j * g.nx + i] * 1000) / maxMM);
    const k = ((g.ny - 1 - j) * g.nx + i) * 4;
    img.data[k] = r; img.data[k + 1] = gg; img.data[k + 2] = b; img.data[k + 3] = 255;
  }
  const off = new OffscreenCanvas(g.nx, g.ny);
  off.getContext("2d").putImageData(img, 0, 0);
  ctx.save();
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(off, 0, 0, g.nx, g.ny, F.ox - F.s * (g.x2 - g.x1) / (2 * (g.nx - 1)), F.oy - F.s * (g.y2 - g.y1) / (2 * (g.ny - 1)),
    F.w + F.s * (g.x2 - g.x1) / (g.nx - 1), F.h + F.s * (g.y2 - g.y1) / (g.ny - 1));
  ctx.restore();
  // keep the image inside the frame
  ctx.save();
  ctx.fillStyle = css("--surface");
  ctx.fillRect(0, 0, F.W, F.oy); ctx.fillRect(0, F.oy + F.h, F.W, F.H - F.oy - F.h);
  ctx.fillRect(0, 0, F.ox, F.H); ctx.fillRect(F.ox + F.w, 0, F.W - F.ox - F.w, F.H);
  ctx.restore();

  // contours, labelled in mm
  const lv = levels(maxMM);
  const mm = Array.from(grid.values, (v) => v * 1000);
  const gx = (i) => F.X(g.x1 + ((g.x2 - g.x1) * i) / (g.nx - 1)), gy = (j) => F.Y(g.y1 + ((g.y2 - g.y1) * j) / (g.ny - 1));
  ctx.lineWidth = 1;
  ctx.font = "10px system-ui, sans-serif";
  const placed = [];
  for (const L of lv) {
    const segs = contour(mm, g.nx, g.ny, L);
    const strong = L / maxMM > 0.55;
    ctx.strokeStyle = strong !== dark() ? "rgba(255,255,255,.75)" : "rgba(11,11,11,.45)";
    ctx.beginPath();
    for (const [[i1, j1], [i2, j2]] of segs) { ctx.moveTo(gx(i1), gy(j1)); ctx.lineTo(gx(i2), gy(j2)); }
    ctx.stroke();
    // one label on the longest-reaching segment to the right
    if (segs.length) {
      const s = segs.reduce((a, b) => (Math.max(b[0][0], b[1][0]) > Math.max(a[0][0], a[1][0]) ? b : a));
      const x = gx((s[0][0] + s[1][0]) / 2), y = gy((s[0][1] + s[1][1]) / 2);
      const t = String(+L.toFixed(1));
      const w = ctx.measureText(t).width + 6;
      if (placed.some(([px, py]) => Math.abs(px - x) < w && Math.abs(py - y) < 15)) continue;
      placed.push([x, y]);
      ctx.fillStyle = css("--surface");
      ctx.globalAlpha = 0.85; ctx.fillRect(x - w / 2, y - 7, w, 14); ctx.globalAlpha = 1;
      ctx.fillStyle = css("--ink-2"); ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(t, x, y);
    }
  }

  // load outlines
  project.loads.forEach((l, idx) => {
    if (l.on === false) return;
    const polys = outline(l);
    polys.forEach((poly, k) => {
      ctx.beginPath();
      poly.forEach(([x, y], i) => (i ? ctx.lineTo(F.X(x), F.Y(y)) : ctx.moveTo(F.X(x), F.Y(y))));
      ctx.closePath();
      ctx.strokeStyle = idx === opts.selectedLoad ? css("--series-2") : css("--ink");
      ctx.lineWidth = idx === opts.selectedLoad ? 2.2 : k ? 1 : 1.6;
      ctx.setLineDash(k ? [4, 3] : []);
      ctx.stroke();
      ctx.setLineDash([]);
    });
    // the name just above the load's outline
    if (l.name && polys[0] && (project.loads.length <= 8 || idx === opts.selectedLoad)) {
      const top = Math.min(...polys[0].map(([, y]) => F.Y(y)));
      ctx.font = "600 11px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
      const w = ctx.measureText(l.name).width + 8, cx = F.X(loadCentre(l)[0]);
      ctx.fillStyle = css("--surface"); ctx.globalAlpha = 0.85; ctx.fillRect(cx - w / 2, top - 18, w, 15); ctx.globalAlpha = 1;
      ctx.fillStyle = css("--ink"); ctx.fillText(l.name, cx, top - 4);
    }
  });

  // section line
  if (opts.section) {
    const s = opts.section;
    ctx.strokeStyle = css("--series-2"); ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
    ctx.beginPath();
    if (s.along === "x") { ctx.moveTo(F.X(s.a1), F.Y(s.at)); ctx.lineTo(F.X(s.a2), F.Y(s.at)); }
    else { ctx.moveTo(F.X(s.at), F.Y(s.a1)); ctx.lineTo(F.X(s.at), F.Y(s.a2)); }
    ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = css("--series-2"); ctx.font = "600 11px system-ui, sans-serif";
    const [ax, ay] = s.along === "x" ? [F.X(s.a1) + 10, F.Y(s.at) - 9] : [F.X(s.at) + 10, F.Y(s.a2) + 10];
    ctx.textAlign = "left"; ctx.fillText("A", ax, ay);
    const [bx, by] = s.along === "x" ? [F.X(s.a2) - 10, F.Y(s.at) - 9] : [F.X(s.at) + 10, F.Y(s.a1) - 10];
    ctx.textAlign = "right"; ctx.fillText("A′", bx, by);
  }

  // query point
  if (opts.query) {
    const x = F.X(+opts.query.x), y = F.Y(+opts.query.y);
    ctx.fillStyle = css("--series-2"); ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  }

  // axes
  ctx.strokeStyle = css("--axis"); ctx.lineWidth = 1;
  ctx.strokeRect(F.ox + 0.5, F.oy + 0.5, F.w, F.h);
  ctx.fillStyle = css("--muted"); ctx.font = "10px system-ui, sans-serif";
  const step = niceStep(Math.max(g.x2 - g.x1, g.y2 - g.y1), 8);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let x = Math.ceil(g.x1 / step) * step; x <= g.x2 + 1e-9; x += step) {
    ctx.fillText(+x.toFixed(3), F.X(x), F.oy + F.h + 5);
    ctx.fillRect(F.X(x), F.oy + F.h, 1, 4);
  }
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let y = Math.ceil(g.y1 / step) * step; y <= g.y2 + 1e-9; y += step) {
    ctx.fillText(+y.toFixed(3), F.ox - 6, F.Y(y));
    ctx.fillRect(F.ox - 4, F.Y(y), 4, 1);
  }
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.fillText("x (m)", F.ox + F.w / 2, F.H - 2);
  ctx.save(); ctx.translate(10, F.oy + F.h / 2); ctx.rotate(-Math.PI / 2); ctx.textBaseline = "top"; ctx.fillText("y (m)", 0, 0); ctx.restore();
  return F;
}

/** Settlement at a plan point from the grid, by bilinear interpolation (m). */
export function sample(grid, x, y) {
  const g = grid.g;
  const fi = ((x - g.x1) / (g.x2 - g.x1)) * (g.nx - 1), fj = ((y - g.y1) / (g.y2 - g.y1)) * (g.ny - 1);
  if (fi < 0 || fj < 0 || fi > g.nx - 1 || fj > g.ny - 1) return null;
  const i = Math.min(g.nx - 2, Math.floor(fi)), j = Math.min(g.ny - 2, Math.floor(fj)), u = fi - i, v = fj - j;
  const at = (a, b) => grid.values[b * g.nx + a];
  return at(i, j) * (1 - u) * (1 - v) + at(i + 1, j) * u * (1 - v) + at(i, j + 1) * (1 - u) * v + at(i + 1, j + 1) * u * v;
}
