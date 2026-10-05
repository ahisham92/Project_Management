// MarineTwin: the flag a ship flies at her stern.
//
// The ship's own flag state when the line-up gives it (`flag`, an ISO 3166 two-letter code);
// otherwise one of the common flags picked from her name, the same every time. Each flag is
// drawn once on a small canvas in its country's colours and layout (stripes, a canton, a cross,
// the main emblem in outline): recognisable from the quay, not a herald's drawing.

import * as THREE from 'three';

export const FLAG_NAMES = {
  PA: 'Panama', LR: 'Liberia', MH: 'Marshall Islands', MT: 'Malta', SG: 'Singapore', HK: 'Hong Kong', BS: 'Bahamas',
  GR: 'Greece', CN: 'China', DK: 'Denmark', DE: 'Germany', FR: 'France', NG: 'Nigeria', SA: 'Saudi Arabia',
  AE: 'United Arab Emirates', EG: 'Egypt',
};
const CODES = Object.keys(FLAG_NAMES);
// The open registries carry most of the world's fleet, so a ship without a known flag most
// likely flies one of theirs: they come up more often.
const LIKELY = ['PA', 'PA', 'LR', 'LR', 'MH', 'MH', 'MT', 'SG', 'HK', 'BS', ...CODES];

// The flag for a ship: her own if known and drawable, else one picked from her name.
export function flagCode(name, given) {
  const code = String(given || '').toUpperCase();
  if (FLAG_NAMES[code]) return code;
  let h = 2166136261;
  for (const ch of String(name || 'ship')) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  return LIKELY[h % LIKELY.length];
}

const W = 96;
const H = 64;
function star(c, x, y, r, colour) {
  c.fillStyle = colour;
  c.beginPath();
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 ? r * 0.42 : r;
    c.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
  }
  c.closePath();
  c.fill();
}
const bands = (c, colours, vertical = false) => colours.forEach((col, i) => {
  c.fillStyle = col;
  if (vertical) c.fillRect((i * W) / colours.length, 0, W / colours.length + 1, H);
  else c.fillRect(0, (i * H) / colours.length, W, H / colours.length + 1);
});

const DRAW = {
  PA(c) {
    bands(c, ['#fff']);
    c.fillStyle = '#d21034'; c.fillRect(W / 2, 0, W / 2, H / 2);
    c.fillStyle = '#005293'; c.fillRect(0, H / 2, W / 2, H / 2);
    star(c, W / 4, H / 4, 9, '#005293');
    star(c, (3 * W) / 4, (3 * H) / 4, 9, '#d21034');
  },
  LR(c) {
    bands(c, Array.from({ length: 11 }, (_, i) => (i % 2 ? '#fff' : '#bf0a30')));
    c.fillStyle = '#002868'; c.fillRect(0, 0, 30, (5 * H) / 11);
    star(c, 15, (2.5 * H) / 11, 9, '#fff');
  },
  MH(c) {
    bands(c, ['#003893']);
    c.fillStyle = '#dd7500';
    c.beginPath(); c.moveTo(0, H); c.lineTo(W, 2); c.lineTo(W, 12); c.closePath(); c.fill();
    c.fillStyle = '#fff';
    c.beginPath(); c.moveTo(0, H); c.lineTo(W, 12); c.lineTo(W, 20); c.closePath(); c.fill();
    star(c, 18, 18, 11, '#fff');
  },
  MT(c) {
    bands(c, ['#fff', '#cf142b'], true);
    c.fillStyle = '#9aa0a6'; c.fillRect(8, 9, 12, 4); c.fillRect(12, 5, 4, 12);
  },
  SG(c) {
    bands(c, ['#ef3340', '#fff']);
    c.fillStyle = '#fff'; c.beginPath(); c.arc(20, 16, 10, 0, 2 * Math.PI); c.fill();
    c.fillStyle = '#ef3340'; c.beginPath(); c.arc(24, 16, 9, 0, 2 * Math.PI); c.fill();
    for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + (i * 2 * Math.PI) / 5; star(c, 33 + Math.cos(a) * 6, 16 + Math.sin(a) * 6, 2.4, '#fff'); }
  },
  HK(c) {
    bands(c, ['#de2910']);
    c.fillStyle = '#fff';
    for (let i = 0; i < 5; i++) {
      const a = (i * 2 * Math.PI) / 5;
      c.beginPath(); c.ellipse(W / 2 + Math.cos(a) * 9, H / 2 + Math.sin(a) * 9, 9, 5, a, 0, 2 * Math.PI); c.fill();
    }
  },
  BS(c) {
    bands(c, ['#00778b', '#ffc72c', '#00778b']);
    c.fillStyle = '#000'; c.beginPath(); c.moveTo(0, 0); c.lineTo(W * 0.42, H / 2); c.lineTo(0, H); c.closePath(); c.fill();
  },
  GR(c) {
    bands(c, Array.from({ length: 9 }, (_, i) => (i % 2 ? '#fff' : '#0d5eaf')));
    const s = (5 * H) / 9;
    c.fillStyle = '#0d5eaf'; c.fillRect(0, 0, s, s);
    c.fillStyle = '#fff'; c.fillRect(0, (2 * H) / 9, s, H / 9); c.fillRect((2 * H) / 9, 0, H / 9, s);
  },
  CN(c) {
    bands(c, ['#de2910']);
    star(c, 16, 16, 9, '#ffde00');
    for (const [x, y] of [[32, 6], [38, 12], [38, 21], [32, 27]]) star(c, x, y, 3, '#ffde00');
  },
  DK(c) {
    bands(c, ['#c8102e']);
    c.fillStyle = '#fff'; c.fillRect(0, H / 2 - 5, W, 10); c.fillRect(30, 0, 10, H);
  },
  DE(c) { bands(c, ['#000', '#dd0000', '#ffce00']); },
  FR(c) { bands(c, ['#0055a4', '#fff', '#ef4135'], true); },
  NG(c) { bands(c, ['#008751', '#fff', '#008751'], true); },
  SA(c) {
    bands(c, ['#006c35']);
    c.strokeStyle = '#fff'; c.lineWidth = 3;
    c.beginPath(); for (let x = 22; x < 76; x += 7) { c.moveTo(x, 22); c.lineTo(x + 3, 32); } c.stroke();
    c.fillStyle = '#fff'; c.fillRect(24, 42, 48, 3);
  },
  AE(c) {
    bands(c, ['#00732f', '#fff', '#000']);
    c.fillStyle = '#ff0000'; c.fillRect(0, 0, W / 4, H);
  },
  EG(c) {
    bands(c, ['#ce1126', '#fff', '#000']);
    c.fillStyle = '#c09300'; c.beginPath(); c.ellipse(W / 2, H / 2, 6, 8, 0, 0, 2 * Math.PI); c.fill();
  },
};

// One material per flag, drawn the first time it is asked for.
const materials = new Map();
export function flagMaterial(code) {
  if (materials.has(code)) return materials.get(code);
  let map = null;
  if (typeof document !== 'undefined') {
    const canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    const c = canvas.getContext('2d');
    (DRAW[code] || DRAW.PA)(c);
    map = new THREE.CanvasTexture(canvas);
    map.colorSpace = THREE.SRGBColorSpace;
  }
  const mat = new THREE.MeshStandardMaterial({ map, side: THREE.DoubleSide, roughness: 0.8 });
  materials.set(code, mat);
  return mat;
}

// The ensign staff at the stern (x from the ship's middle, y its deck) with the flag on it; the
// ship's userData gets flag and setFlag(code), for a ship model reused for another call.
const STAFF = new THREE.CylinderGeometry(0.14, 0.18, 11, 6).translate(0, 5.5, 0);
// The flag, 6 by 4 m (big enough to make out from the quay), its hoist at the staff and flying aft (towards -x).
const CLOTH = new THREE.PlaneGeometry(6, 4, 6, 1).translate(3, 0, 0).rotateY(Math.PI);
export function addFlag(ship, x, y, code, staffMat) {
  const staff = new THREE.Mesh(STAFF, staffMat);
  staff.position.set(x, y, 0);
  const cloth = new THREE.Mesh(CLOTH, flagMaterial(code));
  cloth.position.set(x, y + 8.8, 0);
  cloth.rotation.y = 0.15;
  ship.add(staff, cloth);
  ship.userData.flag = code;
  ship.userData.flagCloth = cloth;
  ship.userData.setFlag = (next) => {
    if (next === ship.userData.flag) return;
    ship.userData.flag = next;
    cloth.material = flagMaterial(next);
  };
}
