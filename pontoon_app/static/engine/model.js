// The physical pontoon: its cross-section, weight, centre of gravity and stiffness,
// built from the few numbers the page asks for. Four kinds:
//
//   concrete    reinforced concrete shell with a polystyrene (EPS) core
//   framed      aluminium, steel or timber frame and deck on HDPE float modules
//   modular     interlocking HDPE cubes (the cube is both float and deck)
//   attenuator  deep, heavy concrete pontoon that also breaks waves
//
// Everything is per metre of pontoon unless stated. kN, m, kPa, t.

import { CONCRETE } from "./codes.js";

export const KIND_NAMES = {
  concrete: "Concrete (EPS-cored)",
  framed: "Framed on HDPE floats",
  modular: "Modular HDPE cubes",
  attenuator: "Concrete wave attenuator",
};

/** Typical self-weights (kPa) of framed systems; replace with the supplier's figures. */
export const FRAME_KPA = { aluminium: 0.25, steel: 0.45, timber: 0.35 };
export const DECK_KPA = { timber: 0.35, composite: 0.25, aluminium: 0.15, concrete: 1.20 };
export const FRAME_E = { aluminium: 70000, steel: 200000, timber: 12000 }; // MPa
export const EPS_DENSITY = 0.20;   // kN/m³ (≈ 20 kg/m³ EPS)
export const HDPE_FLOAT_KPA = 0.12; // rotomoulded shell + EPS fill, per m² of float plan

/**
 * Section for a pontoon of deck width B. Returns:
 *   rects   buoyant rectangles (y0,y1,z0,z1) in the section frame (z up from the float underside)
 *   cover   fraction of the length that the rectangles are present (1 for a continuous hull)
 *   top     z of the top of the flotation (for the 50 mm reserve), deck z
 *   w       self weight per metre (kN/m) and zg its centre of gravity
 *   EI      longitudinal flexural rigidity (kN·m²)
 *   mass    t/m
 *   parts   for the drawing and the IFC export
 */
export function section(kind, s, B) {
  const sdl = +s.sdl || 0; // superimposed dead load: walers, fenders, services, cleats (kPa)
  if (kind === "concrete" || kind === "attenuator") {
    const D = +s.D, tw = +s.wall, td = +s.deck, tb = +s.base, gc = +s.density || 24.5;
    const ballast = kind === "attenuator" ? +s.ballast || 0 : 0; // concrete ballast in the base (m)
    const area = B * D, voidB = B - 2 * tw, voidD = D - td - tb - ballast;
    const concA = area - Math.max(0, voidB) * Math.max(0, voidD);
    // centroid of the concrete (deck slab, base slab + ballast, two walls)
    const parts = [
      { a: B * td, z: D - td / 2 }, { a: B * (tb + ballast), z: (tb + ballast) / 2 },
      { a: 2 * tw * voidD, z: tb + ballast + voidD / 2 },
    ];
    const zc = parts.reduce((t, p) => t + p.a * p.z, 0) / concA;
    const wc = concA * gc, we = voidB * voidD * EPS_DENSITY, ws = sdl * B;
    const w = wc + we + ws;
    const zg = (wc * zc + we * (tb + ballast + voidD / 2) + ws * (D + 0.05)) / w;
    // longitudinal stiffness: the thin-walled box, uncracked, Ec from AS 3600 Cl 3.1.2
    const fc = +s.fc || 40, Ec = CONCRETE.Ec(fc); // MPa, AS 3600 Table 3.1.2
    const I = boxI(B, D, tw, td, tb + ballast);
    return {
      rects: [{ y0: -B / 2, y1: B / 2, z0: 0, z1: D }], cover: 1, top: D, deck: D, w, zg,
      EI: Ec * 1000 * I, Ec, I, mass: w / 9.80665, D, B,
      parts: { kind, B, D, tw, td, tb: tb + ballast, concA, voidB, voidD, zc },
      breakdown: [["Concrete shell", wc], ["EPS core", we], ["Fittings and services", ws]],
    };
  }
  if (kind === "modular") {
    const h = +s.cube || 0.4, kg = +s.cubeMass || 7, side = 0.5;
    const wcube = (kg * 9.80665) / 1000 / (side * side); // kPa
    const w = (wcube + sdl) * B;
    const zg = (wcube * B * h / 2 + sdl * B * (h + 0.05)) / w;
    // interlocked cubes act as a flexible mat; the connecting lugs carry little bending
    const EI = +s.matEI || 200 * B; // kN·m² per pontoon (cube-mat estimate; supplier figure preferred)
    return {
      rects: [{ y0: -B / 2, y1: B / 2, z0: 0, z1: h }], cover: 1, top: h, deck: h, w, zg, EI, mass: w / 9.80665, D: h, B,
      parts: { kind, B, D: h, side },
      breakdown: [["HDPE cubes", wcube * B], ["Fittings and services", sdl * B]],
    };
  }
  // framed: floats under a frame and deck
  const fh = +s.floatH || 0.5, nf = Math.max(1, Math.round(+s.floats || 2));
  // floats share the width less 50 mm at each edge unless a module width is given; they cannot overlap
  const fw = Math.min(+s.floatW > 0 ? +s.floatW : (B - 0.1) / nf, B / nf);
  const cover = Math.min(1, Math.max(0.1, +s.cover || 0.85));
  const frameH = +s.frameH || 0.3, deckT = 0.04;
  // floats spread evenly across the width, outer floats flush with the frame edge
  const gap = nf > 1 ? (B - nf * fw) / (nf - 1) : 0;
  const rects = Array.from({ length: nf }, (_, i) => {
    const y0 = nf === 1 ? -fw / 2 : -B / 2 + i * (fw + gap);
    return { y0, y1: y0 + fw, z0: 0, z1: fh };
  });
  const wf = HDPE_FLOAT_KPA * nf * fw * cover, wfr = (FRAME_KPA[s.frame] ?? 0.25) * B, wd = (DECK_KPA[s.deck] ?? 0.35) * B, ws = sdl * B;
  const w = wf + wfr + wd + ws;
  const deck = fh + frameH + deckT;
  const zg = (wf * fh / 2 + wfr * (fh + frameH / 2) + wd * (deck - deckT / 2) + ws * (deck + 0.05)) / w;
  const Ef = FRAME_E[s.frame] || 70000;
  // two longitudinal edge members (stringers/walers) of the frame govern the stiffness
  const Iframe = +s.frameI || 2 * 2.0e-5; // m⁴, two 200 mm deep aluminium stringers ≈ 20e6 mm⁴ each
  return {
    rects, cover, top: fh, deck, w, zg, EI: Ef * 1000 * Iframe, mass: w / 9.80665, D: deck, B,
    parts: { kind, B, fh, fw, nf, frameH, deckT, gap, frame: s.frame, deckType: s.deck },
    breakdown: [["HDPE floats", wf], [`${cap(s.frame || "aluminium")} frame`, wfr], [`${cap(s.deck || "timber")} deck`, wd], ["Fittings and services", ws]],
  };
}

const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);

/** Second moment of area of a closed rectangular box about its own centroid (m⁴). */
export function boxI(B, D, tw, tt, tb) {
  const parts = [
    { b: B, h: tt, z: D - tt / 2 }, { b: B, h: tb, z: tb / 2 }, { b: 2 * tw, h: D - tt - tb, z: tb + (D - tt - tb) / 2 },
  ];
  const A = parts.reduce((t, p) => t + p.b * p.h, 0);
  const zc = parts.reduce((t, p) => t + p.b * p.h * p.z, 0) / A;
  return parts.reduce((t, p) => t + (p.b * p.h ** 3) / 12 + p.b * p.h * (p.z - zc) ** 2, 0);
}
