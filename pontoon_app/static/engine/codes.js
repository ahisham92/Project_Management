// Every design value Pontoon takes from a standard lives here, with where it came
// from, so a checker can find and challenge each number in one place.
//
// `src` names the document and clause. `check` is set where the value was taken
// from a secondary source or an earlier edition and should be confirmed against
// the licensed current edition before a design is issued; the Report prints
// these flags.

export const REF = {
  AS3962: "AS 3962-2001 Guidelines for design of marinas (values to be confirmed against AS 3962:2020)",
  AS1170_0: "AS/NZS 1170.0:2002 Structural design actions — General principles",
  AS1170_2: "AS/NZS 1170.2:2021 Structural design actions — Wind actions",
  AS4997: "AS 4997-2005 Guidelines for the design of maritime structures",
  AS2159: "AS 2159-2009 Piling — Design and installation",
  AS3600: "AS 3600:2018 Concrete structures",
  AS4100: "AS 4100:2020 Steel structures",
  AS1720: "AS 1720.1:2010 Timber structures — Design methods",
  TMR: "Qld TMR Design Criteria for Floating Walkways and Pontoons (Oct 2015)",
  EN1993_5: "EN 1993-5:2007 Piling (corrosion loss tables)",
};

// ---------------------------------------------------------------- AS 3962 loads

/** Table 4.1 flotation and stability loads (kPa), by access (Cl 4.3). */
export const FLOTATION = {
  unrestricted: { flotation: 3.0, stability: 2.0 },
  restricted: { flotation: 2.0, stability: 1.5 },
  src: "AS 3962 Table 4.1, Cl 4.7.3",
};
/** Cl 4.7.2 structural live load on floating walkways and fingers. */
export const DECK_LIVE = { udl: 3.0, point: 4.5, src: "AS 3962 Cl 4.7.2 (a)–(c)" };
/** Cl 4.5 gangway live loads. */
export const GANGWAY_LIVE = {
  unrestricted: { udl: 4.0, point: 4.5 }, restricted: { udl: 3.0, point: 4.5 },
  src: "AS 3962 Cl 4.5.1, 4.5.2",
};
/** Freeboard criteria. */
export const FREEBOARD = {
  reserve: 0.050,          // Cl 4.7.1(b): 50 mm reserve buoyancy under the flotation load
  stabilityMin: 0.050,     // Cl 4.12.2: 50 mm to top of flotation, opposite chine submerged
  responseCheck: { freeboard: 0.500, draft: 0.150 }, // Cl 4.7.1: check response if F > 500 and T < 150 mm
  waterAccess: 0.500,      // Cl 5.1.2: access from the water needed when freeboard > 500 mm
  tmr: { min: 0.375, max: 0.500, src: "TMR Table 4.2.1 / 4.2.2" },
  src: "AS 3962 Cl 4.7.1, 4.12.2, 5.1.2",
};

/** Cl 4.2 strength load combinations (environmental factors). */
export const COMBOS = [
  { key: "env", name: "Wind + 1.5 current + 1.5 wave (HAT)", wind: 1.0, current: 1.5, wave: 1.5, level: "HAT", src: "AS 3962 Cl 4.2(a)(i),(ii)" },
  { key: "envLAT", name: "Wind + 1.5 current + 1.5 wave (LAT)", wind: 1.0, current: 1.5, wave: 1.5, level: "LAT", src: "AS 3962 Cl 4.2 Note 2" },
  { key: "flood", name: "0.8 wind + 1.25 current + 1.25 wave (max level)", wind: 0.8, current: 1.25, wave: 1.25, level: "MAX", src: "AS 3962 Cl 4.2(a)(iii)", when: "surge" },
  { key: "berthHAT", name: "1.25 × berthing impact (HAT)", berthing: 1.25, level: "HAT", src: "AS 3962 Cl 4.2(c), 4.9" },
  { key: "berthLAT", name: "1.25 × berthing impact (LAT)", berthing: 1.25, level: "LAT", src: "AS 3962 Cl 4.2(c), 4.9" },
];

/** Table 4.3 wind drag coefficients, Table 4.5 stream drag coefficients. */
export const CD_WIND = { vesselBow: 0.9, vesselBeam: 1.1, tubularPile: 1.2, rectangular: 2.0, src: "AS 3962 Table 4.3 (upper values)" };
export const CD_CURRENT = {
  pileSmooth: 0.70, pileRough: 1.40, squareSharp: 2.2, squareRounded: 1.0, debris: 1.0,
  vesselBow: 0.3, vesselBeamHull: 0.6, vesselBeamKeel: 1.2, src: "AS 3962 Table 4.5",
};
export const CURRENT_MIN = { v: 1.0, src: "AS 3962 Cl 4.8.4.2 (minimum 1.0 m/s)" };
export const DEBRIS = { depthFactor: 2.0, minForce: 10.0, src: "AS 3962 Cl 4.8.4.4 (mat ≥ 2 × draft; ≥ 10 kN/m)" };
export const WAVE_MIN = { force: 2.0, src: "AS 3962 Cl 4.8.2.3 (minimum 2 kN/m horizontal)" };
export const WAVE_DESIGN = { H1overHs: 1.67, src: "AS 3962 Cl 4.8.2.2 (H1, mean of highest 1 %; Rayleigh H1/Hs = 1.67)" };
/** Cl 4.8.3.3 wind: qz = 0.0006 V² kPa (½·1.2·V² Pa), F = CD A qz. Vessel group: 20 % on leeward boats. */
export const WIND = { rho: 1.2, leeward: 0.2, src: "AS 3962 Cl 4.8.3; AS/NZS 1170.2 Cl 2.4.1 (ρair = 1.2 kg/m³)" };
export const BERTHING = { v: 0.3, vLarge: 0.2, src: "AS 3962 Cl 4.9 (≥ 0.3 m/s; 0.2 m/s for vessels over 25 m)" };
export const WATER = { sea: 1026, fresh: 1000, src: "AS 3962 Cl 4.8.4.3" };

/** Table 4.2 good wave climate (Hs, m), 1 in 50 y and 1 y events. */
export const WAVE_CLIMATE = {
  rows: [
    { dir: "Head seas, T < 2 s", y50: null, y1: 0.3 },
    { dir: "Head seas, T > 2 s", y50: 0.6, y1: 0.3 },
    { dir: "Oblique seas, T > 2 s", y50: 0.4, y1: 0.3 },
    { dir: "Beam seas, T < 2 s", y50: null, y1: 0.3 },
    { dir: "Beam seas, T > 2 s", y50: 0.25, y1: 0.15 },
  ],
  factors: { excellent: 0.75, good: 1.0, moderate: 1.25 },
  src: "AS 3962 Table 4.2",
};

/** Table 4.4 vessel windage (m²): [length, motor head, motor beam, yacht head, yacht beam]. */
export const WINDAGE = [
  [8, 5, 16, 4, 11], [10, 7, 22, 5, 15], [12, 11, 29, 6, 20], [15, 18, 45, 9, 28], [18, 22, 64, 11, 40],
  [20, 24, 76, 12, 44], [25, 30, 95, 15, 60], [30, 45, 120, 35, 92], [35, 54, 167, 36, 122],
  [40, 78, 213, 40, 182], [45, 85, 264, 50, 210], [50, 90, 285, 60, 249],
];
/** Table 3.1 typical draughts (m): [length, power, yacht]. */
export const DRAUGHT = [
  [8, 0.9, 1.5], [10, 1.0, 1.8], [12, 1.0, 2.0], [15, 1.2, 2.5], [20, 1.5, 2.9], [25, 1.8, 3.0],
  [30, 1.9, 3.4], [35, 2.1, 3.8], [40, 2.3, 4.2], [45, 2.6, 4.2], [50, 2.9, 4.2],
];
/** Table 3.2 beam (m) of mono-hull boats by length. */
export const BEAM = [
  [6, 2.8], [7, 3.1], [8, 3.4], [9, 3.7], [10, 4.0], [11, 4.3], [12, 4.4], [13, 4.6], [14, 4.8], [15, 5.0],
  [16, 5.2], [17, 5.3], [18, 5.4], [19, 5.5], [20, 5.7], [21, 5.8], [22, 5.9], [23, 6.0], [24, 6.3], [25, 6.5],
  [27.5, 7.0], [30, 7.5], [35, 8.7], [40, 10.0], [45, 10.0], [50, 10.0],
];
/** Table 3.3 clear gangway width by number of berths. */
export const GANGWAY_WIDTH = [[2, 0.7], [10, 0.9], [60, 1.2], [120, 1.5], [Infinity, 1.8]];
/** Cl 3.6.2 gangway slopes (1 in n) at CD. */
export const GANGWAY_SLOPE = { marina: 3.5, private: 3.0, disabled: 8.0, src: "AS 3962 Cl 3.6.2" };
/** Cl 3.5 walkway and finger dimensions. */
export const WALKWAY = { min: 1.5, over100: 1.8, over200: 2.4, fingerLength: 0.8, fingerWidth: 0.9, fingerTip: 0.6, src: "AS 3962 Cl 3.5" };

// -------------------------------------------------- AS/NZS 1170.0 and 1170.2

/** AS/NZS 1170.0 Table F2: annual probability of exceedance (1/R) for wind, by design life and importance level. */
export const RETURN_PERIOD = {
  5: { 1: 25, 2: 50, 3: 100, 4: 250 },
  25: { 1: 50, 2: 200, 3: 500, 4: 1000 },
  50: { 1: 100, 2: 500, 3: 1000, 4: 2500 },
  100: { 1: 500, 2: 1000, 3: 2500, 4: 2500 },
  src: "AS/NZS 1170.0 Table F2 (wind)",
};

/** AS/NZS 1170.2 Table 3.1(A) regional wind speed VR (m/s) for return period R (years). */
export const REGIONS = {
  A0: { name: "A0", f: (R) => 67 - 41 * R ** -0.1 },
  A1: { name: "A1", f: (R) => 67 - 41 * R ** -0.1 },
  A2: { name: "A2", f: (R) => 67 - 41 * R ** -0.1 },
  A3: { name: "A3", f: (R) => 67 - 41 * R ** -0.1 },
  A4: { name: "A4", f: (R) => 67 - 41 * R ** -0.1 },
  A5: { name: "A5", f: (R) => 67 - 41 * R ** -0.1 },
  W: { name: "W (Wellington region, NZ)", f: (R) => 104 - 70 * R ** -0.045 },
  B1: { name: "B1", f: (R) => 106 - 92 * R ** -0.1 },
  B2: { name: "B2", f: (R) => 106 - 92 * R ** -0.1 },
  C: { name: "C (tropical cyclone)", f: (R) => 1.05 * (122 - 104 * R ** -0.1) },
  D: { name: "D (severe tropical cyclone)", f: (R) => 1.1 * (156 - 142 * R ** -0.1) },
  src: "AS/NZS 1170.2:2021 Table 3.1(A) (C and D with FC = 1.05, FD = 1.1 for R ≥ 50)",
};
export const regionalSpeed = (region, R) => +(REGIONS[region] || REGIONS.A2).f(R);

/** AS/NZS 1170.2 Table 4.1 Mz,cat for TC2 (water surfaces, ultimate). AS 3962 Cl 4.8.3.1: TC1 inappropriate. */
export const MZCAT_TC2 = [[0, 0.91], [5, 0.91], [10, 1.00], [15, 1.05], [20, 1.08], [30, 1.12]];
export const MZCAT_SRC = "AS/NZS 1170.2 Table 4.1, terrain category 2 (water surfaces)";

// ---------------------------------------------------------------- AS 4100 steel

export const STEEL = {
  E: 200000, G: 80000, phi: 0.9,
  grades: {
    C250: { name: "C250L0 (AS/NZS 1163)", fy: () => 250, fu: 320, formed: "cold" },
    C350: { name: "C350L0 (AS/NZS 1163)", fy: () => 350, fu: 430, formed: "cold" },
    C450: { name: "C450L0 (AS/NZS 1163)", fy: () => 450, fu: 500, formed: "cold" },
    G350: { name: "Grade 350 plate, spiral/ERW (AS/NZS 3678, 3679.1)", fy: (t) => (t <= 12 ? 360 : t <= 20 ? 350 : 340), fu: 450, formed: "fabricated", check: true },
  },
  chs: { flexure: { lp: 50, ly: 120 }, axial: { ly: 82 }, src: "AS 4100 Table 5.2, Table 6.2.4 (CHS)" },
  src: "AS 4100 Cl 5.2, 5.11.4, 6.2, 6.3.3, 8.3, 8.4",
};
/** EN 1993-5 Table 4-2 loss of thickness (mm, one face) in sea water. Used where no site data exist. */
export const CORROSION = {
  splash: { 5: 0.55, 25: 1.9, 50: 3.75, 75: 5.6, 100: 7.5 },
  immersed: { 5: 0.25, 25: 0.9, 50: 1.75, 75: 2.6, 100: 3.5 },
  soil: { 5: 0, 25: 0.30, 50: 0.60, 75: 0.90, 100: 1.20 },
  src: "EN 1993-5 Table 4-2 / 4-1 (sea water, temperate; AS 2159 Cl 6.5 requires an allowance for the exposure)",
  check: true,
};

// ------------------------------------------------------------- AS 3600 concrete

export const CONCRETE = {
  Es: 200000, ecu: 0.003, fsy: 500,
  alpha2: (fc) => Math.max(0.67, 0.85 - 0.0015 * fc),
  gamma: (fc) => Math.max(0.67, 0.97 - 0.0025 * fc),
  /** Table 3.1.2 mean modulus Ecj (MPa) for ρ = 2400 kg/m³. */
  EcTable: [[20, 24000], [25, 26700], [32, 30100], [40, 32800], [50, 34800], [65, 37400], [80, 39600], [100, 42200]],
  Ec: (fc) => interp(CONCRETE.EcTable, fc),
  phiBending: (kuo) => Math.min(0.85, Math.max(0.65, 1.24 - (13 * kuo) / 12)),
  phiShear: 0.7, phiCompression: 0.65,
  cover: { B1: { 32: 30, 40: 25, 50: 20 }, B2: { 40: 35, 50: 25 }, C1: { 40: 50, 50: 40 }, C2: { 50: 65 } },
  exposure: { submerged: "B2", tidal: "C2", spray: "C1", src: "AS 3600 Table 4.3" },
  src: "AS 3600 Cl 3.1.2, 3.2.2, 8.1.3, 8.2.4, Table 2.2.2, Table 4.10.3.2",
};

// ---------------------------------------------------------------- AS 1720.1 timber

export const TIMBER = {
  grades: {
    F14: { fb: 36, fs: 3.3, fc: 27, E: 12000 },
    F17: { fb: 42, fs: 3.6, fc: 34, E: 14000 },
    F22: { fb: 52, fs: 4.2, fc: 41, E: 16000 },
    F27: { fb: 67, fs: 5.1, fc: 49, E: 18500 },
  },
  phi: 0.75, k1: 1.0,
  src: "AS 1720.1 Table H2.1 (F-grade characteristic values), Cl 3.2.1; φ per Table 2.1 for the grade and category",
  check: true,
};

// ---------------------------------------------------------------- AS 2159 piles

/** Basic geotechnical strength reduction factor φgb vs average risk rating. */
export const PHI_GB = {
  bands: [[1.5, 0.67, 0.76], [2.0, 0.61, 0.70], [2.5, 0.56, 0.64], [3.0, 0.52, 0.60], [3.5, 0.48, 0.56], [4.0, 0.45, 0.53], [4.5, 0.42, 0.50], [Infinity, 0.40, 0.47]],
  src: "AS 2159 Table 4.3.2(C) (low / high redundancy)",
  check: true,
};
export function phiGb(arr, highRedundancy = false) {
  const b = PHI_GB.bands.find(([lim]) => arr <= lim);
  return highRedundancy ? b[2] : b[1];
}

// ---------------------------------------------------------------- helpers

/** Linear interpolation in a table of [x, ...ys], clamped at the ends. */
export function interp(table, x, col = 1) {
  if (x <= table[0][0]) return table[0][col];
  for (let i = 1; i < table.length; i++) {
    const [x1] = table[i], [x0] = table[i - 1];
    if (x <= x1) return table[i - 1][col] + ((x - x0) / (x1 - x0)) * (table[i][col] - table[i - 1][col]);
  }
  return table[table.length - 1][col];
}
export const gangwayWidth = (berths) => GANGWAY_WIDTH.find(([n]) => berths <= n)[1];
export const walkwayWidth = (length) => (length > 200 ? WALKWAY.over200 : length > 100 ? WALKWAY.over100 : WALKWAY.min);
