// Where everything is, in one place, for the 3D view and the IFC export alike.
// x along the main walkway (0 at the gangway end), y across it, z up from Chart Datum (m).

export function layoutGeometry(r, levelKey = "HAT") {
  const lay = r.layout, v = r.vessel, lv = r.levels[levelKey];
  const walk = r.floats.walkway, fin = r.floats.finger;
  const Tw = walk.ini.T, Tf = fin.ini.T;
  const items = [];
  // walkway modules
  for (let i = 0; i < lay.modules; i++) {
    items.push({
      kind: "walkway", name: `Walkway W${i + 1}`, x0: i * lay.moduleL, x1: (i + 1) * lay.moduleL - 0.05,
      y0: -lay.walkW / 2, y1: lay.walkW / 2, z0: lv - Tw, z1: lv - Tw + walk.sec.deck, draft: Tw,
    });
  }
  // fingers and berths along each side
  const pitch = lay.berthW + lay.fingerW;
  const fingers = lay.perSide + 1;
  const sides = lay.sides === 1 ? [1] : [1, -1];
  let fn = 0, bn = 0;
  for (const s of sides) {
    for (let i = 0; i < fingers; i++) {
      const xc = 0.5 * lay.fingerW + i * pitch + (lay.walkLen - (fingers - 1) * pitch - lay.fingerW) / 2;
      const ya = s * lay.walkW / 2, yb = s * (lay.walkW / 2 + lay.fingerL);
      items.push({ kind: "finger", name: `Finger F${++fn}`, x0: xc - lay.fingerW / 2, x1: xc + lay.fingerW / 2, y0: Math.min(ya, yb), y1: Math.max(ya, yb), z0: lv - Tf, z1: lv - Tf + fin.sec.deck, draft: Tf });
      if (i < fingers - 1 && bn < lay.berths) {
        const bx = xc + pitch / 2;
        items.push({ kind: "boat", name: `Berth B${++bn}`, xc: bx, yc: s * (lay.walkW / 2 + 0.6 + v.L / 2), L: v.L, B: v.beam, z: lv, dir: s, motor: v.motor, draught: v.hullDraft });
      }
    }
  }
  // guide piles, alternating sides of the walkway
  const P = r.piles, n = P.n, D = P.ps.D;
  for (let i = 0; i < n; i++) {
    const x = n === 1 ? lay.walkLen / 2 : 0.5 + (i * (lay.walkLen - 1)) / (n - 1);
    const s = i % 2 ? -1 : 1;
    items.push({ kind: "pile", name: `Pile P${i + 1}`, x, y: s * (lay.walkW / 2 + D / 2 + 0.15), D, top: P.pileTop, toe: P.toe, bed: r.project.site.seabed, section: P.ps });
  }
  // gangway from the landing to the walkway end
  const g = r.gangway, landing = +r.project.layout.gangwayLanding;
  const deck = lv - Tw + walk.sec.deck;
  const run = Math.sqrt(Math.max(0, g.length ** 2 - (landing - deck) ** 2));
  items.push({ kind: "gangway", name: "Gangway G1", x0: -run, x1: 0, z0: landing, z1: deck, w: lay.gangwayW, length: g.length });
  return { items, level: lv, seabed: +r.project.site.seabed, extent: { x0: -run - 2, x1: lay.walkLen + 2, y: lay.walkW / 2 + lay.fingerL + v.L * 0.3 + 2 } };
}
