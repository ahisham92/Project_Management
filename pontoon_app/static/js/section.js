// Pontoon — the drawings: the cross-section heeled under the stability load, and the
// governing pile with its levels, bending moment and deflection. Plain SVG, so the
// same drawings go into the printed Report.
import { immersed } from "../engine/hydro.js";

export const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f = (v, d = 2) => (Number.isFinite(v) ? (+v.toFixed(d)).toString() : "–");

/** Heeled section: the element chosen (walkway or finger) under the AS 3962 stability load. */
export function heelSVG(r, which = "walkway", { width = 900, height = 480 } = {}) {
  const fl = r.floats[which], sec = fl.sec, eq = fl.stability;
  if (!eq) return `<svg class="section" viewBox="0 0 ${width} ${height}"><text x="20" y="40">No equilibrium.</text></svg>`;
  const th = eq.theta, c = Math.cos(th), s = -Math.sin(th);
  const rot = ([y, z]) => [y * c - z * s, y * s + z * c];
  const B = sec.B, D = sec.deck;
  const span = Math.max(B, D) * 1.9, sc = Math.min(width, height * 1.6) / span;
  const cx = width / 2, cy = height * 0.55;
  const P = ([y, z]) => [cx + y * sc, cy - (z - eq.h) * sc];
  const poly = (pts, attrs) => `<polygon points="${pts.map((p) => P(rot(p)).map((v) => v.toFixed(1)).join(",")).join(" ")}" ${attrs}/>`;
  let out = `<svg class="section" viewBox="0 0 ${width} ${height}" role="img" aria-label="Heeled cross-section">`;
  out += `<rect x="0" y="${cy}" width="${width}" height="${height - cy}" fill="rgba(42,120,214,.18)"/><line x1="0" x2="${width}" y1="${cy}" y2="${cy}" stroke="#2a78d6" stroke-width="2"/>`;
  // deck/frame outline then the flotation
  out += poly([[-B / 2, sec.top], [B / 2, sec.top], [B / 2, D], [-B / 2, D]], `fill="var(--grid)" stroke="var(--ink-2)" stroke-width="1"`);
  for (const q of sec.rects) out += poly([[q.y0, q.z0], [q.y1, q.z0], [q.y1, q.z1], [q.y0, q.z1]], `fill="${r.project.type === "framed" ? "#3b3f45" : r.project.type === "modular" ? "#2a78d6" : "#c9c6bd"}" stroke="var(--ink)" stroke-width="1.2"`);
  // stability load on half the width
  const q0 = rot([0, D]), q1 = rot([B / 2, D]);
  for (let i = 0; i <= 6; i++) {
    const t = i / 6, y = q0[0] + t * (q1[0] - q0[0]), z = q0[1] + t * (q1[1] - q0[1]);
    const [X, Y] = P([y, z]);
    out += `<line x1="${X}" y1="${Y - 34}" x2="${X}" y2="${Y - 4}" stroke="#e34948" stroke-width="2"/><path d="M${X - 4} ${Y - 9} L${X} ${Y - 2} L${X + 4} ${Y - 9}" fill="#e34948"/>`;
  }
  // G and B
  const W = sec.w + (r.project.access === "restricted" ? 1.5 : 2.0) * B / 2;
  const ws = W - sec.w, yg = (ws * B / 4) / W, zg = (sec.w * sec.zg + ws * D) / W;
  const G = P(rot([yg, zg]));
  const im = immersed(sec.rects, th, eq.h);
  const Bp = [cx + im.y * sc, cy - (im.z - eq.h) * sc];
  out += `<circle cx="${G[0]}" cy="${G[1]}" r="5" fill="var(--ink)"/><text x="${G[0] + 8}" y="${G[1] - 6}" class="lbl">G</text>`;
  out += `<circle cx="${Bp[0]}" cy="${Bp[1]}" r="5" fill="#2a78d6"/><text x="${Bp[0] + 8}" y="${Bp[1] + 14}" class="lbl">B</text>`;
  out += `<line x1="${G[0]}" y1="${G[1]}" x2="${G[0]}" y2="${cy + 60}" stroke="var(--ink)" stroke-dasharray="4 3"/><line x1="${Bp[0]}" y1="${Bp[1]}" x2="${Bp[0]}" y2="${Bp[1] - 140}" stroke="#2a78d6" stroke-dasharray="4 3"/>`;
  const deg = (th * 180) / Math.PI;
  out += `<text x="${width - 16}" y="${height - 34}" text-anchor="end" class="lbl">${esc(fl.name)} · ${f(B, 2)} m wide · stability load ${r.project.access === "restricted" ? "1.5" : "2.0"} kPa on half the width</text>`;
  out += `<text x="${width - 16}" y="${height - 14}" text-anchor="end" class="lbl">Heel ${f(deg, 2)}° · flotation top on the low side ${f((fl.checks.find((c) => c.name.startsWith("Freeboard to flotation, stability"))?.value ?? NaN) * 1000, 0)} mm above water</text>`;
  out += `</svg>`;
  return out;
}

/** The governing pile: levels, bending moment and deflection down its length. */
export function pileSVG(r, { width = 900, height = 520 } = {}) {
  const P = r.piles, g = P.gov, resp = g.resp;
  const top = P.pileTop, toe = P.toe, ground = P.ground, head = ground + g.e;
  const zOf = (x) => head - x; // x measured down from the guide
  const zmin = toe - 0.5, zmax = top + 0.5;
  const H = height - 150, Y = (z) => 100 + ((zmax - z) / (zmax - zmin)) * H;
  const px = 150;
  let out = `<svg class="section" viewBox="0 0 ${width} ${height}" role="img" aria-label="Pile diagram">`;
  // water and bed
  out += `<rect x="40" y="${Y(g.level)}" width="${width - 80}" height="${Y(ground) - Y(g.level)}" fill="rgba(42,120,214,.16)"/>`;
  out += `<rect x="40" y="${Y(ground)}" width="${width - 80}" height="${Y(zmin) - Y(ground)}" fill="rgba(205,185,143,.35)"/>`;
  const lvl = (z, t, col = "var(--ink-2)", right = false) => `<line x1="40" x2="${width - 40}" y1="${Y(z)}" y2="${Y(z)}" stroke="${col}" stroke-dasharray="5 4"/><text x="${right ? width - 44 : 44}" y="${Y(z) + (right ? 13 : -4)}"${right ? ' text-anchor="end"' : ""} class="lbl sm">${esc(t)} ${f(z, 2)}</text>`;
  out += lvl(top, "Pile top") + lvl(g.level, `Water (${g.combo.level})`, "#2a78d6") + lvl(+r.project.site.seabed, "Seabed") + (Math.abs(ground - +r.project.site.seabed) > 0.01 ? lvl(ground, "Scoured bed", "var(--ink-2)", true) : "") + lvl(toe, "Toe");
  const w = Math.max(6, P.ps.D * 18);
  out += `<rect x="${px - w / 2}" y="${Y(top)}" width="${w}" height="${Y(toe) - Y(top)}" fill="var(--axis)" stroke="var(--ink)"/>`;
  out += `<path d="M${px - 40} ${Y(head)} L${px - w / 2 - 2} ${Y(head)}" stroke="#e34948" stroke-width="3"/><path d="M${px - w / 2 - 10} ${Y(head) - 5} L${px - w / 2 - 2} ${Y(head)} L${px - w / 2 - 10} ${Y(head) + 5}" fill="#e34948"/><text x="${px - 120}" y="${Y(head) - 8}" class="lbl sm">H* ${f(g.H, 1)} kN</text>`;
  // moment and deflection plots
  const plot = (x0, wdt, vals, colour, label, unit, scale = 1) => {
    const m = Math.max(...vals.map((v) => Math.abs(v))) || 1;
    const pts = vals.map((v, i) => `${(x0 + wdt / 2 + (v / m) * (wdt / 2 - 10)).toFixed(1)},${Y(zOf(resp.x[i])).toFixed(1)}`);
    let s = `<line x1="${x0 + wdt / 2}" x2="${x0 + wdt / 2}" y1="${Y(head)}" y2="${Y(toe)}" stroke="var(--grid)"/>`;
    s += `<polyline points="${pts.join(" ")}" fill="none" stroke="${colour}" stroke-width="2.2"/>`;
    s += `<text x="${x0 + wdt / 2}" y="${height - 30}" text-anchor="middle" class="lbl">${esc(label)} · max ${f(m * scale, 1)} ${unit}</text>`;
    return s;
  };
  out += plot(260, 300, resp.M, "#eb6834", "Bending moment", "kN·m");
  out += plot(580, 280, resp.w.map((v) => v * 1000), "#1baf7a", "Deflection", "mm");
  out += `<text x="${width - 40}" y="${height - 10}" text-anchor="end" class="lbl sm">${esc(P.ps.desc)} · embedded ${f(P.Lreq, 1)} m · ${esc(g.combo.name)}</text>`;
  out += `</svg>`;
  return out;
}
