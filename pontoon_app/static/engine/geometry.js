// Where everything is, in one place, for the 3D view and the IFC export alike.
// x along the arms (0 at the landward end of each arm), y across them, z up from Chart Datum (m).
// Layouts: one arm; an arm with a landward walkway (L); an arm with a T-head; several arms off a
// spine walkway at x < 0 (comb). Every item is an axis-aligned box or a line, so the same list
// draws in three.js and exports to IFC.

export function layoutGeometry(r, levelKey = "HAT") {
  const lay = r.layout, v = r.vessel, lv = r.levels[levelKey];
  const walk = r.floats.walkway, fin = r.floats.finger;
  const Tw = walk.ini.T, Tf = fin.ini.T;
  const items = [];
  const zw0 = lv - Tw, zw1 = zw0 + walk.sec.deck;
  const chains = r.piles.type === "chains";
  const landing = r.gangwayDesign?.landing;
  // arm offsets across y
  const armY = Array.from({ length: lay.arms }, (_, k) => (k - (lay.arms - 1) / 2) * lay.armSpacing);
  let mn = 0, fn = 0, bn = 0, pn = 0, cn = 0;
  const addModules = (prefix, x0, y0, along, count, width, landingIndex = -1) => {
    for (let i = 0; i < count; i++) {
      const W = i === landingIndex && landing ? landing.B : width;
      const a0 = i * lay.moduleL, a1 = (i + 1) * lay.moduleL - 0.05;
      const box = along === "x"
        ? { x0: x0 + a0, x1: x0 + a1, y0: y0 - W / 2, y1: y0 + W / 2 }
        : { x0: x0 - W / 2, x1: x0 + W / 2, y0: y0 + a0, y1: y0 + a1 };
      items.push({ kind: "walkway", name: `${prefix}${++mn}`, along, ...box, z0: zw0, z1: zw1, draft: Tw, landing: i === landingIndex && landing && landing.B > width, landingKind: i === landingIndex && landing ? landing.kind : null });
    }
  };
  const addMoorings = (x0, y0, along, len) => {
    const n = Math.max(2, Math.ceil(len / Math.max(2, +(chains ? r.project.mooring.spacing : r.project.piles.spacing))) + 1);
    for (let i = 0; i < n; i++) {
      const a = n === 1 ? len / 2 : 0.5 + (i * (len - 1)) / (n - 1);
      const s = i % 2 ? -1 : 1;
      const x = along === "x" ? x0 + a : x0, y = along === "x" ? y0 : y0 + a;
      if (chains) {
        const M = r.piles, ang = M.angle, R = M.radius, zf = lv - Tw, bed = +r.project.site.seabed;
        for (const k of [1, -1]) {
          const dx = (along === "x" ? Math.cos(ang) : Math.sin(ang)) * k * R, dy = (along === "x" ? Math.sin(ang) : Math.cos(ang)) * R;
          for (const side of [1, -1]) {
            if (side !== k) continue; // two chains per point, crossed
            items.push({ kind: "chain", name: `Chain C${++cn}`, pts: chainPoints(x, y, zf, x + dx, y + dy * side, bed, M), d: M.d });
            items.push({ kind: "anchor", name: `Anchor A${cn}`, x: x + dx, y: y + dy * side, z: bed, side: M.block.side });
          }
        }
      } else {
        const P = r.piles, D = P.ps.D, gap = r.guides ? r.guides.gap : 0.05;
        const off = (along === "x" ? lay.walkW : lay.walkW) / 2 + D / 2 + gap + 0.05;
        const px = along === "x" ? x : x + s * off, py = along === "x" ? y + s * off : y;
        items.push({ kind: "pile", name: `Pile P${++pn}`, x: px, y: py, D, top: P.pileTop, toe: P.toe, bed: r.project.site.seabed, section: P.ps });
        if (r.guides) {
          const a = r.guides.a, w = D + 2 * gap + 0.2;
          const g = along === "x"
            ? { x0: px - w / 2, x1: px + w / 2, y0: s > 0 ? py - a + D / 2 + gap : py - D / 2 - gap - 0.1, y1: s > 0 ? py + D / 2 + gap + 0.1 : py + a - D / 2 - gap }
            : { x0: s > 0 ? px - a + D / 2 + gap : px - D / 2 - gap - 0.1, x1: s > 0 ? px + D / 2 + gap + 0.1 : px + a - D / 2 - gap, y0: py - w / 2, y1: py + w / 2 };
          items.push({ kind: "guide", name: `Guide G${pn}`, ...g, z0: zw1 - 0.35, z1: zw1 - 0.15, pile: `Pile P${pn}`, shs: r.guides.shs });
        }
      }
    }
  };
  const pitch = lay.berthW + lay.fingerW;
  const fingers = lay.perSide + 1;
  const sides = lay.sides === 1 ? [1] : [1, -1];
  // arms
  for (let k = 0; k < lay.arms; k++) {
    const y0 = armY[k];
    const landHere = lay.shape === "single" || lay.shape === "T" ? 0 : -1;
    addModules(lay.arms > 1 ? `Arm ${k + 1} W` : "Walkway W", 0, y0, "x", lay.modules, lay.walkW, k === 0 ? landHere : -1);
    let made = 0;
    for (const s of sides) {
      for (let i = 0; i < fingers; i++) {
        const xc = 0.5 * lay.fingerW + i * pitch + (lay.walkLen - (fingers - 1) * pitch - lay.fingerW) / 2;
        const ya = y0 + s * lay.walkW / 2, yb = y0 + s * (lay.walkW / 2 + lay.fingerL);
        items.push({ kind: "finger", name: `Finger F${++fn}`, x0: xc - lay.fingerW / 2, x1: xc + lay.fingerW / 2, y0: Math.min(ya, yb), y1: Math.max(ya, yb), z0: lv - Tf, z1: lv - Tf + fin.sec.deck, draft: Tf, arm: k });
        if (i < fingers - 1 && made < lay.perArm && bn < lay.berths) {
          made++;
          items.push({ kind: "boat", name: `Berth B${++bn}`, xc: xc + pitch / 2, yc: y0 + s * (lay.walkW / 2 + 0.6 + v.L / 2), L: v.L, B: v.beam, z: lv, dir: s, motor: v.motor, draught: v.hullDraft });
        }
      }
    }
    addMoorings(0, y0, "x", lay.walkLen);
  }
  // spine (comb, L) along y at the landward end, or the T-head at the seaward end
  let gy = 0, gx = 0;
  if (lay.spine) {
    const yStart = lay.shape === "comb" ? -lay.spine.len / 2 : -lay.walkW / 2;
    const xs = -lay.walkW / 2 - 0.05;
    const landIdx = lay.shape === "comb" ? Math.floor(lay.spine.modules / 2) : lay.spine.modules - 1;
    addModules("Spine S", xs, yStart, "y", lay.spine.modules, lay.walkW, landIdx);
    addMoorings(xs, yStart, "y", lay.spine.len);
    gy = yStart + (landIdx + 0.5) * lay.moduleL; gx = xs - (landing ? landing.B : lay.walkW) / 2;
  } else if (lay.head) {
    const xs = lay.walkLen + lay.walkW / 2 + 0.05;
    addModules("Head H", xs, -lay.head.len / 2, "y", lay.head.modules, lay.walkW);
    addMoorings(xs, -lay.head.len / 2, "y", lay.head.len);
  }
  // gangway from the landing towards −x
  const g = r.gangway, gl = +r.project.layout.gangwayLanding;
  const run = Math.sqrt(Math.max(0, g.length ** 2 - (gl - zw1) ** 2));
  items.push({ kind: "gangway", name: "Gangway G1", x0: gx - run, x1: gx, y: gy, z0: gl, z1: zw1, w: lay.gangwayW, length: g.length });
  // extents
  const xs = items.flatMap((it) => (it.x0 !== undefined ? [it.x0, it.x1] : it.x !== undefined ? [it.x] : it.xc !== undefined ? [it.xc - it.L / 2, it.xc + it.L / 2] : []));
  const ys = items.flatMap((it) => (it.y0 !== undefined ? [it.y0, it.y1] : it.y !== undefined ? [it.y] : it.yc !== undefined ? [it.yc - it.L / 2, it.yc + it.L / 2] : []));
  const ext = { x0: Math.min(...xs) - 2, x1: Math.max(...xs) + 2, y0: Math.min(...ys) - 2, y1: Math.max(...ys) + 2 };
  ext.y = Math.max(-ext.y0, ext.y1);
  return { items, level: lv, seabed: +r.project.site.seabed, extent: ext };
}

/** Points along a chain from the fairlead (x0, y0, z0) to an anchor on the bed, hanging as a catenary at a quarter of the design pull. */
function chainPoints(x0, y0, z0, x1, y1, bed, M) {
  const h = z0 - bed, H = Math.max(0.5, M.gov.H / 4), w = M.w, a = H / w;
  const s = Math.sqrt(h * h + (2 * h * H) / w), xs = a * Math.asinh(s / a);
  const R = Math.hypot(x1 - x0, y1 - y0), ux = (x1 - x0) / R, uy = (y1 - y0) / R;
  const pts = [];
  // u: horizontal distance from the touch-down point; the fairlead is at u = xs
  for (let i = 16; i >= 0; i--) {
    const u = (i / 16) * xs, z = bed + a * (Math.cosh(u / a) - 1), d = xs - u;
    pts.push([x0 + ux * d, y0 + uy * d, Math.min(z0, z)]);
  }
  pts.push([x1, y1, bed]);
  return pts;
}
