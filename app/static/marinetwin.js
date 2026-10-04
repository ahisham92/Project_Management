// MarineTwin's 3D view: the asset's Revit model (IFC or glTF), or a schematic drawn
// from its elements when there is no model yet, coloured by condition and set in its
// real surroundings: the sky and sun for the site's position and time of day, the sea at
// the tide's level, the weather, and the terminal at work around it (ships, cranes,
// trucks, cargo) for the kind of terminal it is.
//
// three.js is vendored under static/vendor/three. web-ifc, which reads IFC in the
// browser, is about 6 MB with its WebAssembly, so it is fetched only when an IFC model
// is opened, from the address in data-web-ifc. The live weather comes from Open-Meteo
// when the browser can reach it; otherwise the simulated conditions from the server.
//
// Frame: three's y is up and in metres above chart datum (model levels are mCD).
// The berth runs along x, and the sea is towards -z.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';
import { Sky } from 'three/addons/Sky.js';
import { Water } from 'three/addons/Water.js';

const view = document.querySelector('.marine-view');
// The live port (step 4) plays the next two days through the same scene: marinetwin-live.js drives it.
const LIVE = view && view.dataset.mode === 'live';
// The lifecycle (step 5) plays the whole design life through it: marinetwin-life.js drives that.
const LIFE = view && view.dataset.mode === 'life';
const pick = document.querySelector('.marine-pick');

function css(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

const STATE_COLOUR = {
  good: () => css('--good', '#0ca30c'),
  warning: () => css('--warning', '#fab219'),
  critical: () => css('--critical', '#d03b3b'),
  neutral: () => css('--axis', '#c3c2b7'),
};
const STATE_WORD = { good: 'Good', warning: 'Watch', critical: 'Act', neutral: 'No data' };
const FURNITURE = new Set(['fender', 'bollard', 'crane_rail', 'crane_stopper', 'storm_pin', 'ladder', 'ramp']);

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function note(text) {
  let el = view.querySelector('.marine-view-note');
  if (!el) {
    el = document.createElement('p');
    el.className = 'marine-view-note small muted';
    view.appendChild(el);
  }
  el.textContent = text;
  el.hidden = !text;
}

// --- materials ----------------------------------------------------------------------

function material(state, opacity = 1) {
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(STATE_COLOUR[state || 'neutral']()),
    roughness: 0.6, metalness: 0.1, transparent: opacity < 1, opacity,
  });
}

const REAL = {
  concrete: new THREE.MeshStandardMaterial({ color: 0xb9b5ab, roughness: 0.92 }),
  steel: new THREE.MeshStandardMaterial({ color: 0x4b5560, roughness: 0.55, metalness: 0.6 }),
  rubber: new THREE.MeshStandardMaterial({ color: 0x1d1d1f, roughness: 0.9 }),
  asphalt: new THREE.MeshStandardMaterial({ color: 0x3d3f42, roughness: 0.95 }),
  land: new THREE.MeshStandardMaterial({ color: 0x8c8a6c, roughness: 1 }),
  yellow: new THREE.MeshStandardMaterial({ color: 0xe8b21a, roughness: 0.5, metalness: 0.3 }),
  crane: new THREE.MeshStandardMaterial({ color: 0xd84a1b, roughness: 0.5, metalness: 0.3 }),
  white: new THREE.MeshStandardMaterial({ color: 0xeeeeea, roughness: 0.6 }),
  hull: new THREE.MeshStandardMaterial({ color: 0x1f2c44, roughness: 0.6 }),
  antifouling: new THREE.MeshStandardMaterial({ color: 0x8e2420, roughness: 0.7 }),
  glass: new THREE.MeshStandardMaterial({ color: 0x223344, roughness: 0.2, metalness: 0.5, emissive: 0x000000 }),
  lamp: new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffe2a8, emissiveIntensity: 0 }),
  shed: new THREE.MeshStandardMaterial({ color: 0x9aa3a8, roughness: 0.7, metalness: 0.3 }),
  coal: new THREE.MeshStandardMaterial({ color: 0x2b2722, roughness: 1 }),
  grain: new THREE.MeshStandardMaterial({ color: 0xc9a85a, roughness: 1 }),
};
const REAL_FOR_KIND = {
  pile: 'steel', combi_wall: 'steel', sheet_pile: 'steel', beam: 'concrete', slab: 'concrete', fender: 'rubber',
  bollard: 'steel', crane_rail: 'steel', crane_stopper: 'yellow', storm_pin: 'yellow', ladder: 'yellow', tie_rod: 'steel',
  ramp: 'steel', other: 'concrete',
};
const BOX_COLOURS = [0x1f4e8c, 0xe2b007, 0x2a7ab0, 0xb3261e, 0x2e7d32, 0xe0e0e0, 0xef6c00, 0x5d4037, 0x00838f, 0x8e24aa];

function showElement(element) {
  if (!pick) return;                    // the live port has no side panel
  if (!element) {
    pick.innerHTML = '<p class="small muted">Click an element to see its sensors.</p>';
    return;
  }
  const ur = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(2));
  const sensors = element.sensors.length
    ? '<ul>' + element.sensors.map((s) => `<li><span class="state-${s.state}" aria-hidden="true">●</span> <strong>${escapeHtml(s.label)}</strong><br><span class="small">${escapeHtml(s.headline)}</span></li>`).join('') + '</ul>'
    : '<p class="small muted">No sensors on it.</p>';
  pick.innerHTML = `
    <h3>${escapeHtml(element.name)}</h3>
    <p><span class="badge ${element.state}">${STATE_WORD[element.state]}</span>
       <span class="small muted">health ${element.health ?? '—'}</span></p>
    <p class="small">Design UR ${ur(element.design_ur)} · at end of life ${ur(element.ur_at_life)}</p>
    ${sensors}
    <p><a href="${element.href}">Open ${escapeHtml(element.name)} →</a></p>`;
}

// --- the schematic, when there is no model ---------------------------------------
// Positions are the elements' own x (along the berth), y (towards the sea) and z (up, mCD).

function schematic(elements) {
  const group = new THREE.Group();
  const xs = elements.map((e) => e.x);
  const ys = elements.map((e) => e.y);
  const minX = Math.min(...xs, 0) - 4;
  const maxX = Math.max(...xs, 0) + 4;
  const structural = elements.filter((e) => ['pile', 'beam', 'slab', 'combi_wall', 'sheet_pile'].includes(e.kind));
  const front = Math.max(...structural.map((e) => e.y), 0) + 0.6;
  const back = Math.min(...ys, 0) - 4;
  const slab = elements.find((e) => e.kind === 'slab');
  const top = slab ? slab.z + 0.4 : Math.max(...elements.map((e) => e.z), 3);
  for (const e of elements) {
    let geometry;
    let at = new THREE.Vector3(e.x, e.z, -e.y);
    switch (e.kind) {
      case 'pile':
        geometry = new THREE.CylinderGeometry(0.6, 0.6, top - 0.8 + 21, 24);
        at = new THREE.Vector3(e.x, (top - 0.8 - 21) / 2, -e.y);
        break;
      case 'combi_wall':
      case 'sheet_pile':
        geometry = new THREE.BoxGeometry(12, top + 23, 0.9);
        at = new THREE.Vector3(e.x, (top - 23) / 2, -e.y);
        break;
      case 'slab':
        geometry = new THREE.BoxGeometry(maxX - minX, 0.8, front - back);
        at = new THREE.Vector3((maxX + minX) / 2, top - 0.4, -(front + back) / 2);
        break;
      case 'beam':
        geometry = new THREE.BoxGeometry(maxX - minX, 1.6, 1.4);
        at = new THREE.Vector3((maxX + minX) / 2, top - 1.0, -front + 0.7);
        break;
      case 'bollard':
        geometry = new THREE.CylinderGeometry(0.35, 0.45, 0.9, 16);
        at = new THREE.Vector3(e.x, top + 0.45, -e.y);
        break;
      case 'fender':
        geometry = new THREE.BoxGeometry(2.2, 2.6, 1.2);
        at = new THREE.Vector3(e.x, Math.min(e.z, top - 1.4), -front - 0.6);
        break;
      case 'crane_rail':
        geometry = new THREE.BoxGeometry(maxX - minX, 0.25, 0.35);
        at = new THREE.Vector3((maxX + minX) / 2, top + 0.12, -e.y);
        break;
      case 'ladder':
        geometry = new THREE.BoxGeometry(0.6, top + 2, 0.15);
        at = new THREE.Vector3(e.x, (top - 2) / 2, -front - 0.1);
        break;
      case 'ramp':
        geometry = new THREE.BoxGeometry(12, 0.6, 22);
        geometry.rotateX(-0.12);
        at = new THREE.Vector3(e.x, top - 1.2, -front - 10);
        break;
      case 'crane_stopper':
      case 'storm_pin':
        geometry = new THREE.BoxGeometry(0.8, 0.6, 0.8);
        at = new THREE.Vector3(e.x, top + 0.3, -e.y);
        break;
      case 'tie_rod':
        geometry = new THREE.CylinderGeometry(0.08, 0.08, 20, 8);
        geometry.rotateX(Math.PI / 2);
        at = new THREE.Vector3(e.x, top - 2, -e.y + 10);
        break;
      default:
        geometry = new THREE.BoxGeometry(1.5, 1.5, 1.5);
    }
    const mesh = new THREE.Mesh(geometry, material(e.state, e.kind === 'slab' ? 0.85 : 1));
    mesh.position.copy(at);
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.userData.element = e;
    group.add(mesh);
  }
  return group;
}

// --- the Revit model -----------------------------------------------------------------

// A model reference matches exactly, case aside; a glTF node may add a suffix after a
// separator ("P01.001", "P01:shaft"), but P1 never matches P10.
function sameId(name, want) {
  const n = String(name).trim().toLowerCase();
  return n === want || (n.startsWith(want) && /^[^0-9a-z]/.test(n.slice(want.length)));
}

// The model's shapes, read by marinetwin-ifc-worker.js (or kept from an earlier visit), as meshes:
// one per tracked element, so it can be coloured and clicked, and a few big ones for the rest.
function meshesFrom(parts, origin) {
  const group = new THREE.Group();
  const byKey = new Map();
  for (const part of parts) {
    const buffer = new THREE.BufferGeometry();
    buffer.setAttribute('position', new THREE.BufferAttribute(part.positions, 3));
    buffer.setAttribute('normal', new THREE.BufferAttribute(part.normals, 3, true));
    buffer.setIndex(new THREE.BufferAttribute(part.index, 1));
    const mesh = new THREE.Mesh(buffer, REAL.concrete);
    mesh.castShadow = mesh.receiveShadow = true;
    group.add(mesh);
    for (const key of [part.global, part.name, part.tag]) {
      if (!key) continue;
      const k = String(key).trim().toLowerCase();
      if (!byKey.has(k)) byKey.set(k, []);
      byKey.get(k).push(mesh);
    }
  }
  return {
    group,
    origin,
    meshesFor(ref) { return byKey.get(String(ref).trim().toLowerCase()) || []; },
  };
}

// The kept shapes, as marinetwin-ifc-worker.js packs them: "MTM1", the header's length, a JSON
// header (origin, and each part's ids and sizes), then each part's positions (float32), indices
// (uint32) and normals (int8, padded to 4), all gzipped.
function unpackShapes(buffer) {
  const bytes = new Uint8Array(buffer);
  if (new TextDecoder().decode(bytes.subarray(0, 4)) !== 'MTM1') throw new Error('not a MarineTwin shape file');
  const length = new DataView(buffer).getUint32(4, true);
  const header = JSON.parse(new TextDecoder().decode(bytes.subarray(8, 8 + length)));
  let at = 8 + length + ((4 - (length % 4)) % 4);
  const parts = header.parts.map((p) => {
    const positions = new Float32Array(buffer, at, p.nv * 3); at += p.nv * 12;
    const index = new Uint32Array(buffer, at, p.ni); at += p.ni * 4;
    const normals = new Int8Array(buffer, at, p.nv * 3); at += p.nv * 3 + ((4 - ((p.nv * 3) % 4)) % 4);
    return { ...p, positions, normals, index };
  });
  return { parts, origin: header.origin };
}

async function fetchWithProgress(url, onProgress) {
  const answer = await fetch(url, { credentials: 'same-origin' });
  if (!answer.ok) throw new Error(`error ${answer.status}`);
  const total = Number(answer.headers.get('Content-Length')) || 0;
  if (!answer.body || !total) return answer.arrayBuffer();
  const reader = answer.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    onProgress(Math.min(got / total, 1), got, total);
  }
  return new Blob(chunks).arrayBuffer();
}

const MB = (n) => (n / 1048576).toFixed(n < 10485760 ? 1 : 0);

async function loadKept(url) {
  const zipped = await fetchWithProgress(url, (f, got, total) =>
    progress(0.15 + 0.35 * f, `Opening the Revit model: ${MB(got)} of ${MB(total)} MB`));
  const raw = await new Response(new Blob([zipped]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
  const { parts, origin } = unpackShapes(raw);
  return meshesFrom(parts, origin);
}

function readIfc(url, base, refs, keepAt) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('marinetwin-ifc-worker.js', import.meta.url), { type: 'module' });
    const parts = [];
    let reading = null;
    const slow = () => progress(0.36, 'Reading the model. A big Revit model can take a minute or two the first time', 0.08);
    worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === 'progress' && m.stage === 'download') {
        progress(0.15 + 0.2 * (m.loaded / m.total), `Downloading the Revit model: ${MB(m.loaded)} of ${MB(m.total)} MB`);
      } else if (m.type === 'progress' && m.stage === 'open') {
        slow();
        reading = setTimeout(() => note('Still reading the model: big Revit exports take a while the first time. It is kept after that.'), 45000);
      } else if (m.type === 'progress' && m.stage === 'shapes') {
        clearTimeout(reading);
        note('Loading the IFC model…');
        const f = m.total ? m.done / m.total : 0;
        progress(0.45 + 0.1 * f, m.total ? `Building the model: ${m.done.toLocaleString()} of ${m.total.toLocaleString()} objects` : 'Building the model');
      } else if (m.type === 'part') {
        parts.push(m);
      } else if (m.type === 'kept') {
        if (!m.ok) console.warn('The shapes could not be kept on the server', m.why || '');
      } else if (m.type === 'done') {
        clearTimeout(reading);
        resolve({ parts, origin: m.origin });   // the reader closes itself once it has kept the shapes
      } else if (m.type === 'error') {
        clearTimeout(reading);
        worker.terminate();
        reject(new Error(m.message));
      }
    };
    worker.onerror = (ev) => { clearTimeout(reading); worker.terminate(); reject(new Error(ev.message || 'the model reader stopped')); };
    worker.postMessage({ url: new URL(url, location.href).href, base, refs, keepAt: keepAt ? new URL(keepAt, location.href).href : null });
  });
}

async function loadIfc(twin, base) {
  if (twin.model_shapes) {
    try { return await loadKept(twin.model_shapes); } catch (err) { console.warn('Kept shapes unusable, reading the IFC again', err); }
  }
  const refs = twin.elements.flatMap((e) => [e.ref, e.name]);
  // The reader also keeps the shapes on the server, so the next visit opens in seconds.
  const { parts, origin } = await readIfc(twin.model, base, refs, twin.model_shapes_save);
  return meshesFrom(parts, origin);
}

async function loadGltf(url) {
  const gltf = await new GLTFLoader().loadAsync(url);
  const group = gltf.scene;
  const nodes = [];
  group.traverse((node) => {
    if (node.isMesh) { node.material = REAL.concrete; node.castShadow = node.receiveShadow = true; }
    nodes.push(node);
  });
  const meshesOf = (node) => {
    const out = [];
    node.traverse((n) => { if (n.isMesh) out.push(n); });
    return out;
  };
  return {
    group,
    meshesFor(ref) {
      const want = String(ref).trim().toLowerCase();
      const exact = nodes.find((n) => n.name && n.name.trim().toLowerCase() === want);
      const near = exact || nodes.find((n) => n.name && sameId(n.name, want));
      return near ? meshesOf(near) : [];
    },
  };
}

// --- the sun, the tide and the weather ----------------------------------------------

// The sun's altitude and azimuth (from north, clockwise), in radians, for a moment and a place.
export function sunPosition(date, lat, lon) {
  const rad = Math.PI / 180;
  const d = (date.getTime() - Date.UTC(2000, 0, 1, 12)) / 86400000;
  const g = (357.529 + 0.98560028 * d) * rad;
  const q = 280.459 + 0.98564736 * d;
  const L = (q + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad;
  const e = (23.439 - 0.00000036 * d) * rad;
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const gmst = ((18.697374558 + 24.06570982441908 * d) % 24 + 24) % 24;
  const h = (gmst * 15 + lon) * rad - ra;
  const phi = lat * rad;
  const alt = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(h));
  const az = Math.atan2(-Math.sin(h), Math.tan(dec) * Math.cos(phi) - Math.sin(phi) * Math.cos(h));
  return { alt, az: (az + 2 * Math.PI) % (2 * Math.PI) };
}

const WEATHER_WORDS = {
  0: 'clear', 1: 'mainly clear', 2: 'partly cloudy', 3: 'overcast', 45: 'fog', 48: 'fog', 51: 'drizzle', 53: 'drizzle',
  55: 'drizzle', 61: 'rain', 63: 'rain', 65: 'heavy rain', 80: 'showers', 81: 'showers', 82: 'heavy showers',
  95: 'thunderstorm', 96: 'thunderstorm', 99: 'thunderstorm',
};
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

async function liveWeather(lat, lon) {
  const signal = AbortSignal.timeout ? AbortSignal.timeout(6000) : undefined;
  const q = `latitude=${lat}&longitude=${lon}&timezone=auto`;
  const [met, sea] = await Promise.allSettled([
    fetch(`https://api.open-meteo.com/v1/forecast?${q}&wind_speed_unit=ms&current=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code,cloud_cover,is_day&daily=sunrise,sunset&forecast_days=1`, { signal }).then((r) => r.ok ? r.json() : null),
    fetch(`https://marine-api.open-meteo.com/v1/marine?${q}&current=wave_height,sea_level_height_msl&hourly=sea_level_height_msl&forecast_days=2`, { signal }).then((r) => r.ok ? r.json() : null),
  ]);
  const m = met.status === 'fulfilled' ? met.value : null;
  const s = sea.status === 'fulfilled' ? sea.value : null;
  if (!m || !m.current) return null;
  return { met: m, sea: s && s.current ? s : null };
}

// Typical air temperature for the latitude, season and hour, when nothing live is to hand.
function typicalTemperature(lat, date, solarHour) {
  const tropic = 27.5 - 0.42 * Math.max(0, Math.abs(lat) - 10);
  const season = (lat >= 0 ? 1 : -1) * Math.cos(2 * Math.PI * (date.getUTCMonth() - 6.5) / 12) * Math.min(Math.abs(lat), 45) / 4;
  return tropic + season + 3.5 * Math.sin(2 * Math.PI * (solarHour - 9) / 24);
}

function waterNormals() {
  // A tileable ripple texture: sums of sines whose wavelengths divide the tile.
  const size = 256;
  const data = new Uint8Array(size * size * 4);
  const waves = [[3, 1, 0.9], [1, 4, 0.7], [7, 3, 0.35], [5, -6, 0.3], [11, 9, 0.18], [-13, 7, 0.15], [17, -19, 0.08]];
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let dx = 0;
      let dy = 0;
      for (const [kx, ky, a] of waves) {
        const p = 2 * Math.PI * (kx * x + ky * y) / size;
        dx += a * kx * Math.cos(p);
        dy += a * ky * Math.cos(p);
      }
      const n = new THREE.Vector3(-dx * 0.04, -dy * 0.04, 1).normalize();
      const i = (y * size + x) * 4;
      data[i] = (n.x * 0.5 + 0.5) * 255;
      data[i + 1] = (n.y * 0.5 + 0.5) * 255;
      data[i + 2] = (n.z * 0.5 + 0.5) * 255;
      data[i + 3] = 255;
    }
  }
  const texture = new THREE.DataTexture(data, size, size);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.needsUpdate = true;
  return texture;
}

// --- the terminal around the berth ----------------------------------------------------

function box(w, h, d, mat, x, y, z) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  return m;
}

function cylinder(r, h, mat, x, y, z, segments = 16) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, segments), mat);
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  return m;
}

// Containers, many at once: one instanced mesh with a colour per box.
function containerStacks(blocks, rng) {
  const count = blocks.reduce((n, b) => n + b.rows * b.bays * b.tiers, 0);
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(12.0, 2.55, 2.4), new THREE.MeshStandardMaterial({ roughness: 0.7, metalness: 0.2 }), count);
  const m = new THREE.Matrix4();
  const colour = new THREE.Color();
  let i = 0;
  for (const b of blocks) {
    for (let bay = 0; bay < b.bays; bay++) {
      for (let row = 0; row < b.rows; row++) {
        const height = Math.floor(rng() * (b.tiers + 1));
        for (let tier = 0; tier < b.tiers; tier++) {
          if (tier >= height) { m.makeScale(0, 0, 0); } else {
            m.makeTranslation(b.x + bay * 12.6, b.y + 1.3 + tier * 2.6, b.z + row * 2.6);
          }
          mesh.setMatrixAt(i, m);
          mesh.setColorAt(i, colour.setHex(BOX_COLOURS[Math.floor(rng() * BOX_COLOURS.length)]));
          i++;
        }
      }
    }
  }
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

function makeRng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function stsCrane(state) {
  const g = new THREE.Group();
  const gauge = 30;
  for (const x of [-9, 9]) {
    for (const z of [0, gauge]) g.add(box(1.4, 44, 1.4, REAL.crane, x, 22, z));
    g.add(box(1.2, 1.2, gauge, REAL.crane, x, 30, gauge / 2));
  }
  g.add(box(20, 1.6, 1.6, REAL.crane, 0, 44, 0));
  g.add(box(20, 1.6, 1.6, REAL.crane, 0, 44, gauge));
  const boom = new THREE.Group();
  boom.add(box(3, 3, 95, REAL.crane, 0, 0, -95 / 2 + gauge));
  boom.position.set(0, 45.5, 0);
  if (state === 'stowed') { boom.rotation.x = -1.25; boom.position.z = gauge - 4; }
  g.add(boom);
  g.add(box(6, 4, 8, REAL.white, 0, 40, gauge + 4));                   // machinery house
  const trolley = new THREE.Group();
  trolley.add(box(5, 3, 6, REAL.white, 0, 0, 0));
  const spreader = box(12, 0.6, 2.4, REAL.yellow, 0, -12, 0);
  trolley.add(spreader);
  trolley.position.set(0, 43, -20);
  if (state !== 'stowed') g.add(trolley);
  g.userData = { trolley, spreader, boom, working: state === 'working', gauge };
  return g;
}

function harbourCrane(state) {
  const g = new THREE.Group();
  g.add(box(12, 3, 12, REAL.white, 0, 1.5, 0));
  g.add(cylinder(1.8, 22, REAL.white, 0, 14, 0));
  const top = new THREE.Group();
  top.add(box(6, 4, 7, REAL.white, 0, 0, 3));
  const boom = box(1.6, 1.6, 48, REAL.white, 0, 0, -22);
  boom.rotation.x = state === 'stowed' ? 1.2 : 0.35;
  top.add(boom);
  top.position.set(0, 26, 0);
  g.add(top);
  g.userData = { top, working: state === 'working' };
  return g;
}

function unloader(state) {
  const g = stsCrane(state);
  g.add(box(10, 8, 10, REAL.shed, 0, 18, 6));                         // hopper
  return g;
}

function vehicle(kind, colour) {
  const g = new THREE.Group();
  const paint = new THREE.MeshStandardMaterial({ color: colour, roughness: 0.45, metalness: 0.4 });
  if (kind === 'car') {
    g.add(box(4.4, 1.0, 1.8, paint, 0, 0.7, 0));
    g.add(box(2.4, 0.7, 1.6, REAL.glass, -0.2, 1.5, 0));
  } else if (kind === 'tractor') {
    g.add(box(3, 2.4, 2.4, paint, 6, 1.6, 0));
    g.add(box(12, 0.6, 2.4, REAL.steel, 0, 1.1, 0));
    g.add(box(11.6, 2.55, 2.35, new THREE.MeshStandardMaterial({ color: BOX_COLOURS[(colour >> 3) % BOX_COLOURS.length], roughness: 0.7 }), 0, 2.7, 0));
  } else {
    g.add(box(3, 2.8, 2.4, paint, 6.5, 1.8, 0));
    g.add(box(12, 3.0, 2.5, REAL.shed, -0.5, 2.1, 0));
  }
  g.traverse((m) => { if (m.isMesh) m.castShadow = true; });
  return g;
}

function ship(type, loa, beam, draught, rng) {
  const g = new THREE.Group();
  const kind = /bulk/i.test(type) ? 'bulk' : /ro-?ro|car carrier|vehicle/i.test(type) ? 'roro' : /container/i.test(type) ? 'container' : 'general';
  const depth = kind === 'roro' ? 30 : draught + 10;
  const freeboard = depth - draught;
  // The hull: a box with a pointed bow, red below the waterline.
  const shape = new THREE.Shape();
  shape.moveTo(-loa / 2, -beam / 2);
  shape.lineTo(loa / 2 - beam * 1.2, -beam / 2);
  shape.quadraticCurveTo(loa / 2, -beam / 4, loa / 2, 0);
  shape.quadraticCurveTo(loa / 2, beam / 4, loa / 2 - beam * 1.2, beam / 2);
  shape.lineTo(-loa / 2, beam / 2);
  shape.closePath();
  const hullGeo = new THREE.ExtrudeGeometry(shape, { depth: freeboard, bevelEnabled: false });
  hullGeo.rotateX(-Math.PI / 2);
  const hull = new THREE.Mesh(hullGeo, kind === 'roro' ? REAL.white : REAL.hull);
  hull.castShadow = hull.receiveShadow = true;
  g.add(hull);
  const belowGeo = new THREE.ExtrudeGeometry(shape, { depth: draught, bevelEnabled: false });
  belowGeo.rotateX(-Math.PI / 2);
  const below = new THREE.Mesh(belowGeo, REAL.antifouling);
  below.position.y = -draught;
  g.add(below);
  const deck = freeboard;
  // The accommodation and bridge, aft (forward on a car carrier).
  const houseX = kind === 'roro' ? loa / 2 - beam * 1.4 : -loa / 2 + 18;
  g.add(box(14, 16, beam * 0.9, REAL.white, houseX, deck + 8, 0));
  g.add(box(4, 1.4, beam * 0.92, REAL.glass, houseX + 7.2, deck + 14, 0));
  g.add(cylinder(2.2, 8, REAL.crane, houseX - 4, deck + 20, 0));
  const lights = [];
  if (kind === 'container') {
    const blocks = [];
    for (let x = houseX + 14; x < loa / 2 - beam; x += 13.2 * 3 + 2) {
      blocks.push({ x, y: deck, z: -beam / 2 + 1.5, bays: 3, rows: Math.floor((beam - 2) / 2.6), tiers: 6 });
    }
    g.add(containerStacks(blocks, rng));
  } else if (kind === 'bulk' || kind === 'general') {
    for (let x = houseX + 20; x < loa / 2 - beam; x += 26) {
      g.add(box(16, 1.6, beam * 0.6, kind === 'bulk' ? REAL.hull : REAL.shed, x, deck + 0.8, 0));
      if (kind === 'general') {
        const post = cylinder(0.8, 18, REAL.yellow, x + 11, deck + 9, beam * 0.3);
        g.add(post);
        const jib = box(0.6, 0.6, 22, REAL.yellow, x + 11, deck + 16, beam * 0.3 - 10);
        jib.rotation.x = 0.5;
        g.add(jib);
      }
    }
  } else {
    // A car carrier: tall slab sides, and the stern ramp let down to the quay.
    g.add(box(loa * 0.86, 4, beam, REAL.white, -loa * 0.04, deck + 2, 0));
    const ramp = box(8, 0.6, 32, REAL.steel, -loa / 2 + 18, 2.5, beam / 2 + 14);
    ramp.rotation.x = -0.14;
    g.add(ramp);
    g.userData.rampFoot = new THREE.Vector3(-loa / 2 + 18, 0, beam / 2 + 28);
  }
  g.userData.lights = lights;
  g.userData.kind = kind;
  g.userData.draught = draught;
  return g;
}

function mastLight(height) {
  const g = new THREE.Group();
  g.add(cylinder(0.35, height, REAL.steel, 0, height / 2, 0, 8));
  const head = box(3.5, 0.8, 3.5, REAL.lamp, 0, height, 0);
  g.add(head);
  g.userData.head = head;
  return g;
}

// A loop for a vehicle to drive: a closed curve through the given points.
function loop(points, y) {
  return new THREE.CatmullRomCurve3(points.map(([x, z]) => new THREE.Vector3(x, y, z)), true, 'catmullrom', 0.1);
}

function terminal(scene, frame, twin, rng) {
  const { minX, maxX, front, top } = frame;
  const kind = twin.asset.terminal || 'container';
  const centre = (minX + maxX) / 2;
  const length = Math.max(maxX - minX, 120);
  const g = new THREE.Group();
  const movers = [];
  const cranes = [];
  const lights = [];

  // Apron and yard: paved land behind the berth, and plain land beyond.
  const yardDepth = 320;
  const yard = new THREE.Mesh(new THREE.PlaneGeometry(length + 600, yardDepth), REAL.asphalt);
  yard.rotation.x = -Math.PI / 2;
  yard.position.set(centre, top - 0.05, front + yardDepth / 2);
  yard.receiveShadow = true;
  g.add(yard);
  const land = new THREE.Mesh(new THREE.PlaneGeometry(8000, 4000), REAL.land);
  land.rotation.x = -Math.PI / 2;
  land.position.set(centre, top - 0.3, front + yardDepth + 2000);
  land.receiveShadow = true;
  g.add(land);
  // The quay wall either side of the modelled berth, so the berth sits in a longer quay.
  for (const [a, b] of [[minX - 300, minX - 1], [maxX + 1, maxX + 300]]) {
    const wall = box(b - a, top + 6, 3, REAL.concrete, (a + b) / 2, (top - 6) / 2, front + 1.5);
    g.add(wall);
  }
  // Lane markings along the apron.
  const paint = new THREE.MeshBasicMaterial({ color: 0xe9e4c9 });
  for (const z of [front + 6, front + 42]) {
    const line = new THREE.Mesh(new THREE.PlaneGeometry(length + 600, 0.25), paint);
    line.rotation.x = -Math.PI / 2;
    line.position.set(centre, top + 0.02, z);
    g.add(line);
  }

  // High-mast lighting across the yard.
  for (let i = 0; i < 6; i++) {
    const mast = mastLight(30);
    mast.position.set(centre - length / 2 + (i % 3 + 0.5) * length / 3, top, front + 60 + Math.floor(i / 3) * 110);
    g.add(mast);
    lights.push(mast);
  }

  const equipment = twin.equipment || [];
  const stateOf = (i) => (equipment[i] ? equipment[i].state : 'working');
  const ships = twin.alongside;
  const shipLength = ships ? ships.loa : 0;

  if (kind === 'container' || kind === 'multipurpose') {
    const count = kind === 'container' ? Math.max(3, equipment.length) : 1;
    for (let i = 0; i < count; i++) {
      const c = stsCrane(kind === 'container' ? stateOf(i) : 'working');
      c.position.set(centre + (i - (count - 1) / 2) * 42, top, front + 4);
      g.add(c);
      cranes.push(c);
    }
    const blocks = [];
    for (let b = 0; b < (kind === 'container' ? 6 : 2); b++) {
      blocks.push({ x: centre - length / 2 + 10 + (b % 3) * (length / 3), y: top, z: front + 60 + Math.floor(b / 3) * 70, bays: Math.max(4, Math.floor(length / 3 / 12.6) - 1), rows: 6, tiers: 4 });
    }
    g.add(containerStacks(blocks, rng));
    for (const b of blocks) {
      const rtg = new THREE.Group();
      for (const z of [-2, 18]) for (const x of [0, 6]) rtg.add(box(1, 18, 1, REAL.yellow, x, 9, z));
      rtg.add(box(7, 1.4, 22, REAL.yellow, 3, 18, 8));
      rtg.position.set(b.x + 12.6 * 2, top, b.z - 1);
      g.add(rtg);
      movers.push({ object: rtg, swing: { axis: 'x', from: b.x, to: b.x + 12.6 * (b.bays - 1), period: 90 + rng() * 60, phase: rng() * 100 } });
    }
  }
  if (kind === 'general_cargo' || kind === 'multipurpose') {
    for (let i = 0; i < 2; i++) {
      const c = harbourCrane(stateOf(i));
      c.position.set(centre + (i - 0.5) * 50 + (kind === 'multipurpose' ? 60 : 0), top, front + 14);
      g.add(c);
      cranes.push(c);
    }
    g.add(box(90, 14, 36, REAL.shed, centre - 40, top + 7, front + 90));
    g.add(box(90, 14, 36, REAL.shed, centre + 70, top + 7, front + 90));
    // Steel coils and timber on the apron.
    for (let i = 0; i < 24; i++) {
      const coil = new THREE.Mesh(new THREE.TorusGeometry(0.8, 0.45, 8, 16), REAL.steel);
      coil.position.set(centre - 70 + (i % 8) * 2.6, top + 1.2, front + 50 + Math.floor(i / 8) * 2.8);
      coil.castShadow = true;
      g.add(coil);
    }
  }
  if (kind === 'bulk') {
    for (let i = 0; i < 2; i++) {
      const c = unloader(stateOf(i));
      c.position.set(centre + (i - 0.5) * 60, top, front + 4);
      g.add(c);
      cranes.push(c);
    }
    const belt = box(2.4, 1.2, 180, REAL.steel, centre + 40, top + 6, front + 100);
    g.add(belt);
    for (let i = 0; i < 3; i++) {
      const pile = new THREE.Mesh(new THREE.ConeGeometry(28, 18, 24), i % 2 ? REAL.coal : REAL.grain);
      pile.scale.set(1.6, 1, 1);
      pile.position.set(centre - 80 + i * 80, top + 9, front + 200);
      pile.castShadow = pile.receiveShadow = true;
      g.add(pile);
    }
  }
  if (kind === 'roro') {
    // Rows of new cars in the park, and the ones driving off the ship.
    const cars = new THREE.InstancedMesh(new THREE.BoxGeometry(4.4, 1.5, 1.9), new THREE.MeshStandardMaterial({ roughness: 0.35, metalness: 0.5 }), 900);
    const m = new THREE.Matrix4();
    const c = new THREE.Color();
    const carColours = [0xffffff, 0x111111, 0x8a8f94, 0xb71c1c, 0x1a3c8c, 0xc0c4c8, 0x2e4b2e];
    let i = 0;
    for (let row = 0; row < 30; row++) {
      for (let k = 0; k < 30; k++) {
        const filled = rng() < 0.82;
        m.makeTranslation(centre - 90 + k * 5.2 + (row % 2) * 2, filled ? top + 0.75 : -100, front + 50 + row * 4.4 + Math.floor(row / 2) * 3);
        cars.setMatrixAt(i, m);
        cars.setColorAt(i, c.setHex(carColours[Math.floor(rng() * carColours.length)]));
        i++;
      }
    }
    cars.castShadow = cars.receiveShadow = true;
    g.add(cars);
    g.add(box(60, 18, 30, REAL.shed, centre + 120, top + 9, front + 70));      // vehicle processing centre
  }

  // Vehicles on the move: tractors, trucks or cars, each on its own loop.
  const loops = [];
  const shipFootX = centre - (shipLength || 200) / 2 + 18;
  if (kind === 'roro') {
    for (let k = 0; k < 4; k++) {
      loops.push({ curve: loop([[shipFootX, front + 2], [shipFootX + 20, front + 20], [centre - 60 + k * 30, front + 40], [centre - 60 + k * 30, front + 130], [centre + 80, front + 140], [centre + 90, front + 30], [shipFootX + 30, front + 8]], top + 0.1), kind: 'car', n: 7 });
    }
  } else {
    for (let k = 0; k < 3; k++) {
      loops.push({ curve: loop([[centre - 120 + k * 10, front + 12 + k * 3], [centre + 120 - k * 10, front + 12 + k * 3], [centre + 140, front + 56 + k * 20], [centre - 140, front + 56 + k * 20]], top + 0.1), kind: kind === 'container' || kind === 'multipurpose' ? 'tractor' : 'truck', n: 5 });
    }
  }
  // Road trucks on the access road at the back.
  loops.push({ curve: loop([[centre - 400, front + yardDepth - 10], [centre + 400, front + yardDepth - 10], [centre + 400, front + yardDepth - 2], [centre - 400, front + yardDepth - 2]], top + 0.1), kind: 'truck', n: 6, road: true });
  for (const l of loops) {
    for (let k = 0; k < l.n; k++) {
      const v = vehicle(l.kind, [0xeeeeee, 0x1565c0, 0xc62828, 0xf9a825, 0x2e7d32, 0x37474f][Math.floor(rng() * 6)]);
      g.add(v);
      movers.push({ object: v, curve: l.curve, offset: k / l.n + rng() * 0.05, speed: (l.kind === 'car' ? 7 : 6) / l.curve.getLength(), apron: !l.road });
    }
  }
  scene.add(g);
  return { group: g, movers, cranes, lights, kind, yardDepth };
}

// --- the scene -----------------------------------------------------------------------

// The ship loader (marinetwin-ui.js) over the view while it builds, as in Triton.
let voyage = null;
function progress(f, words, ahead = 0) {
  if (!voyage && window.MarineVoyage) voyage = window.MarineVoyage(view, words);
  if (voyage) voyage.set(f, words, ahead);
}

async function main() {
  progress(0.04, 'Loading the twin', 0.1);
  const twin = await (await fetch(view.dataset.twin, { credentials: 'same-origin' })).json();
  progress(0.15, twin.model ? 'Opening the Revit model' : 'Drawing the berth', twin.model ? 0.05 : 0.2);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, (view.clientWidth || 800) / (view.clientHeight || 460), 0.5, 30000);
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(view.clientWidth || 800, view.clientHeight || 460);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.55;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  view.prepend(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI * 0.495;

  // The berth itself.
  let content;
  const unmatched = [];
  const clickable = [];
  if (twin.model) {
    note('Loading ' + (twin.model_kind === 'ifc' ? 'the IFC model' : 'the model') + '…');
    try {
      const model = twin.model_kind === 'ifc' ? await loadIfc(twin, view.dataset.webIfc) : await loadGltf(twin.model);
      for (const e of twin.elements) {
        const meshes = model.meshesFor(e.ref);
        if (!meshes.length && e.ref !== e.name) meshes.push(...model.meshesFor(e.name));
        if (!meshes.length) { unmatched.push(e.name); continue; }
        for (const mesh of meshes) {
          mesh.userData.element = e;
          clickable.push(mesh);
        }
      }
      content = model.group;
      note(unmatched.length ? `${unmatched.length} element${unmatched.length > 1 ? 's' : ''} not found in the model: ${unmatched.slice(0, 6).join(', ')}${unmatched.length > 6 ? '…' : ''}` : '');
    } catch (err) {
      console.error(err);
      content = null;
      note('The model could not be opened here (' + (err.message || err) + '). Showing the schematic instead.');
    }
  }
  if (!content) {
    content = schematic(twin.elements);
    content.traverse((n) => { if (n.isMesh) clickable.push(n); });
    if (!twin.model) note(twin.elements.length ? 'Schematic: no Revit model uploaded yet.' : 'No elements yet.');
  }
  scene.add(content);
  progress(0.55, 'Building the terminal around it', 0.15);

  // Turn the model so its fenders face the sea (-z) and the berth runs along x.
  const centreOf = (kind) => {
    const pts = clickable.filter((m) => m.userData.element.kind === kind).map((m) => new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3()));
    if (!pts.length) return null;
    return pts.reduce((a, b) => a.add(b), new THREE.Vector3()).divideScalar(pts.length);
  };
  const fenders = centreOf('fender');
  const bollards = centreOf('bollard') || centreOf('crane_rail') || centreOf('slab');
  if (twin.model && fenders && bollards) {
    const v = fenders.clone().sub(bollards);
    if (Math.hypot(v.x, v.z) > 0.3) content.rotation.y = Math.atan2(v.x, -v.z) * -1;
    content.updateMatrixWorld(true);
  }
  const bbox = new THREE.Box3().setFromObject(content);
  if (bbox.isEmpty()) bbox.set(new THREE.Vector3(-10, -10, -10), new THREE.Vector3(10, 5, 10));
  const fenderBoxes = clickable.filter((m) => m.userData.element.kind === 'fender').map((m) => new THREE.Box3().setFromObject(m));
  const slabTops = clickable.filter((m) => ['slab', 'beam'].includes(m.userData.element.kind)).map((m) => new THREE.Box3().setFromObject(m).max.y);
  const frame = {
    minX: bbox.min.x, maxX: bbox.max.x,
    front: fenderBoxes.length ? Math.max(...fenderBoxes.map((b) => b.max.z)) : bbox.min.z,
    fenderFace: fenderBoxes.length ? Math.min(...fenderBoxes.map((b) => b.min.z)) : bbox.min.z - 1.5,
    top: slabTops.length ? Math.max(...slabTops) : bbox.max.y,
  };

  // Sky, sun and sea.
  const lat = twin.asset.latitude ?? 0;
  const lon = twin.asset.longitude ?? -new Date().getTimezoneOffset() / 4;
  const theta = THREE.MathUtils.degToRad(twin.asset.rotation || 0);
  const sky = new Sky();
  sky.scale.setScalar(20000);
  scene.add(sky);
  const sunLight = new THREE.DirectionalLight(0xffffff, 3);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(2048, 2048);
  const span = Math.max(frame.maxX - frame.minX, 200);
  Object.assign(sunLight.shadow.camera, { left: -span, right: span, top: span, bottom: -span, near: 1, far: 3000 });
  scene.add(sunLight, sunLight.target);
  const hemi = new THREE.HemisphereLight(0xcfe3ff, 0x5a5040, 0.6);
  scene.add(hemi);
  const water = new Water(new THREE.PlaneGeometry(12000, 12000), {
    textureWidth: 512, textureHeight: 512, waterNormals: waterNormals(), sunDirection: new THREE.Vector3(),
    sunColor: 0xffffff, waterColor: 0x0f3b4f, distortionScale: 2.2, fog: false,
  });
  water.rotation.x = -Math.PI / 2;
  water.material.uniforms.size.value = 6;
  scene.add(water);
  const stars = new THREE.Points(
    new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(
      Array.from({ length: 1500 * 3 }, (_, i) => {
        const k = Math.floor(i / 3);
        const u = Math.sin(k * 12.9898) * 43758.5453 % 1;
        const w = Math.sin(k * 78.233) * 12345.678 % 1;
        const a = Math.abs(u) * 2 * Math.PI;
        const b = Math.acos(Math.abs(w));
        return [Math.cos(a) * Math.sin(b), Math.cos(b), Math.sin(a) * Math.sin(b)][i % 3] * 9000;
      }), 3)),
    new THREE.PointsMaterial({ color: 0xffffff, size: 2, sizeAttenuation: false, transparent: true, opacity: 0 }));
  scene.add(stars);
  const pmrem = new THREE.PMREMGenerator(renderer);
  let envTarget = null;

  // The terminal around it.
  const rng = makeRng(twin.asset.id * 7919);
  const site = terminal(scene, frame, twin, rng);
  let vessel = null;
  if (LIVE || LIFE) {
    // The live and lifecycle players bring the ships in and out themselves.
  } else if (twin.alongside) {
    const a = twin.alongside;
    vessel = ship(a.type, a.loa, a.beam, a.draught, rng);
    vessel.position.set((frame.minX + frame.maxX) / 2, 0, frame.fenderFace - a.beam / 2 - 0.4);
    vessel.traverse((m) => { if (m.isMesh) m.castShadow = true; });
    scene.add(vessel);
  } else if (twin.next_ship) {
    // The berth is empty: the next ship waits off the quay, lined up to come alongside.
    const a = twin.next_ship;
    vessel = ship(a.type, a.loa, a.beam, a.draught, rng);
    vessel.position.set(frame.minX - a.loa / 2 - 60, 0, frame.fenderFace - a.beam / 2 - 45);
    vessel.rotation.y = 0.12;
    vessel.traverse((m) => { if (m.isMesh) m.castShadow = true; });
    scene.add(vessel);
  }
  const lamps = [];
  for (const mast of site.lights.slice(0, 4)) {
    const light = new THREE.PointLight(0xffd9a0, 0, 160, 1.6);
    light.position.copy(mast.position).add(new THREE.Vector3(0, 29, 0));
    scene.add(light);
    lamps.push(light);
  }

  // Colours: by condition (the twin's job), or as built.
  const conditionMats = new Map();
  let byCondition = true;
  function paint() {
    content.traverse((m) => {
      if (!m.isMesh) return;
      const e = m.userData.element;
      if (byCondition) {
        if (e) {
          if (!conditionMats.has(e.state)) conditionMats.set(e.state, material(e.state));
          m.material = conditionMats.get(e.state);
        } else {
          m.material = REAL.concrete;
        }
      } else {
        m.material = REAL[REAL_FOR_KIND[e?.kind] || 'concrete'];
      }
    });
  }
  paint();

  // The hud: where and when, and the conditions there now.
  const hud = document.createElement('div');
  hud.className = 'marine-hud small';
  hud.innerHTML = `
    <div class="marine-hud-read" aria-live="polite"></div>
    <div class="marine-hud-controls">
      <label title="Move the clock to see the sun, night and tide at other times">Time <input type="range" min="-12" max="24" step="0.25" value="0" class="marine-hud-time"></label>
      <label><input type="checkbox" class="marine-hud-condition" checked> Colour by condition</label>
      <label><input type="checkbox" class="marine-hud-xray"> See under the water</label>
      <label><input type="checkbox" class="marine-hud-move" checked> Operations moving</label>
    </div>`;
  view.appendChild(hud);
  if (LIVE || LIFE) hud.hidden = true;   // the players have their own
  const read = hud.querySelector('.marine-hud-read');

  // What the weather is: live from Open-Meteo where the browser can reach it.
  const sim = twin.now;
  let live = null;
  if (twin.asset.latitude !== null && twin.asset.longitude !== null) {
    progress(0.72, 'Reading the weather and tide there', 0.18);
    try { live = await liveWeather(lat, lon); } catch (err) { live = null; }
  }
  const utcOffset = live ? live.met.utc_offset_seconds : Math.round(lon / 15) * 3600;
  const zoneWord = live ? (live.met.timezone_abbreviation || live.met.timezone) : 'solar time';
  const seaLevels = live && live.sea && live.sea.hourly && live.sea.hourly.sea_level_height_msl
    ? live.sea.hourly.time.map((t, i) => [Date.parse(t + 'Z') - utcOffset * 1000, live.sea.hourly.sea_level_height_msl[i]]).filter(([, v]) => v !== null)
    : null;
  const simTides = (sim.tides || []).map((t) => [Date.parse(t.at), t.tide]);

  let tideSource = null;                 // the live player's tide, when it plays its own timeline
  function tideAt(when) {
    if (tideSource) return tideSource(when);
    // Sea level above chart datum: the live sea level on the site's MSL, or the simulated tide.
    const series = seaLevels && seaLevels.length ? seaLevels.map(([t, v]) => [t, v + (twin.asset.msl_cd || 0)]) : simTides;
    if (!series.length) return 1.0;
    const t = when.getTime();
    for (let i = 1; i < series.length; i++) {
      if (series[i][0] >= t) {
        const [t0, v0] = series[i - 1];
        const [t1, v1] = series[i];
        return v0 + (v1 - v0) * Math.max(0, Math.min(1, (t - t0) / (t1 - t0)));
      }
    }
    return series[series.length - 1][1];
  }

  let offsetHours = 0;
  let wind = { speed: sim.wind, gust: sim.gust, dir: 225 };
  let temperature = null;
  let words = '';
  let hs = sim.hs;
  if (live) {
    const c = live.met.current;
    wind = { speed: c.wind_speed_10m, gust: c.wind_gusts_10m, dir: c.wind_direction_10m };
    temperature = c.temperature_2m;
    words = WEATHER_WORDS[c.weather_code] || '';
    if (live.sea && live.sea.current && live.sea.current.wave_height !== null) hs = live.sea.current.wave_height;
    sky.material.uniforms.turbidity.value = 2 + (c.cloud_cover || 0) / 12;
  } else {
    sky.material.uniforms.turbidity.value = 4;
  }
  sky.material.uniforms.rayleigh.value = 1.6;
  sky.material.uniforms.mieCoefficient.value = 0.004;
  sky.material.uniforms.mieDirectionalG.value = 0.8;

  let lastEnv = -99;
  let clock = null;                      // the live player's clock, when it runs one
  function setTime() {
    const when = clock ? new Date(clock) : new Date(Date.now() + offsetHours * 3600000);
    const { alt, az } = sunPosition(when, lat, lon);
    // Sun direction, geographic to the model's frame (x along the berth, -z to the sea side).
    const east = Math.cos(alt) * Math.sin(az);
    const north = Math.cos(alt) * Math.cos(az);
    const mx = east * Math.cos(theta) + north * Math.sin(theta);
    const my = -east * Math.sin(theta) + north * Math.cos(theta);
    const dir = new THREE.Vector3(mx, Math.sin(alt), -my).normalize();
    sky.material.uniforms.sunPosition.value.copy(dir);
    water.material.uniforms.sunDirection.value.copy(dir).normalize();
    const day = THREE.MathUtils.clamp((Math.sin(alt) + 0.1) / 0.35, 0, 1);
    const centre = new THREE.Vector3((frame.minX + frame.maxX) / 2, frame.top, frame.front + 60);
    sunLight.position.copy(centre).addScaledVector(dir.y > 0 ? dir : new THREE.Vector3(0.3, 1, 0.2).normalize(), 1200);
    sunLight.target.position.copy(centre);
    sunLight.intensity = 3.2 * day + 0.08;
    sunLight.color.setHSL(0.09 + 0.05 * day, 0.6 * (1 - day) + 0.1, 0.75 + 0.2 * day);
    hemi.intensity = 0.15 + 0.75 * day;
    hemi.color.setHSL(0.6, 0.4, 0.35 + 0.5 * day);
    renderer.toneMappingExposure = 0.25 + 0.3 * day;
    stars.material.opacity = THREE.MathUtils.clamp(1 - day * 3, 0, 1);
    const night = day < 0.35;
    for (const l of lamps) l.intensity = night ? 900 : 0;
    REAL.lamp.emissiveIntensity = night ? 3 : 0;
    REAL.glass.emissive.setHex(night ? 0x665533 : 0x000000);
    water.material.uniforms.waterColor.value.setHex(day > 0.3 ? 0x0f3b4f : 0x041018);
    const tide = tideAt(when);
    water.position.y = tide;
    if (vessel) vessel.position.y = tide;
    if (Math.abs(day - lastEnv) > 0.08) {
      // Reflections from the sky as it is now.
      if (envTarget) envTarget.dispose();
      const envScene = new THREE.Scene();
      envScene.add(sky.clone());
      envTarget = pmrem.fromScene(envScene);
      scene.environment = envTarget.texture;
      scene.environmentIntensity = 0.04 + 0.12 * day;   // the sky is HDR: a little goes a long way
      lastEnv = day;
    }
    // The reading.
    const local = new Date(when.getTime() + utcOffset * 1000);
    const hh = String(local.getUTCHours()).padStart(2, '0');
    const mm = String(local.getUTCMinutes()).padStart(2, '0');
    const solarHour = (when.getUTCHours() + when.getUTCMinutes() / 60 + lon / 15 + 24) % 24;
    const temp = temperature !== null && offsetHours === 0 ? temperature : typicalTemperature(lat, when, solarHour);
    const rising = tideAt(new Date(when.getTime() + 1800000)) > tide;
    const sunWord = alt > 0 ? `sun ${Math.round(THREE.MathUtils.radToDeg(alt))}° up` : alt > -0.1 ? 'twilight' : 'night';
    const place = twin.asset.location || (twin.asset.latitude !== null ? `${lat.toFixed(3)}, ${lon.toFixed(3)}` : 'location not set');
    read.innerHTML = `<strong>${escapeHtml(place)}</strong> · ${hh}:${mm} ${escapeHtml(zoneWord)}${offsetHours ? ` <span class="muted">(${offsetHours > 0 ? '+' : ''}${offsetHours} h)</span>` : ''}<br>` +
      `${sunWord} · ${temp.toFixed(0)} °C${words && !offsetHours ? ', ' + escapeHtml(words) : ''} · wind ${wind.speed.toFixed(0)} m/s ${COMPASS[Math.round(wind.dir / 45) % 8]}, gusts ${wind.gust.toFixed(0)}<br>` +
      `tide ${tide >= 0 ? '+' : ''}${tide.toFixed(2)} mCD ${rising ? 'rising' : 'falling'} · waves ${hs.toFixed(1)} m` +
      (twin.alongside ? ` · alongside: ${escapeHtml(twin.alongside.name)}` : twin.next_ship ? ` · next: ${escapeHtml(twin.next_ship.name)}` : '') +
      `<br><span class="muted">${live ? 'Weather live from Open-Meteo' + (seaLevels ? '; tide from its sea level on MSL +' + (twin.asset.msl_cd || 0).toFixed(2) + ' mCD' : '; tide simulated') : 'Weather and tide simulated'}${twin.asset.latitude === null ? '; set the location for the real sun' : ''}</span>`;
  }

  hud.querySelector('.marine-hud-time').addEventListener('input', (ev) => { offsetHours = Number(ev.target.value); setTime(); });
  hud.querySelector('.marine-hud-condition').addEventListener('change', (ev) => { byCondition = ev.target.checked; paint(); });
  hud.querySelector('.marine-hud-xray').addEventListener('change', (ev) => {
    water.material.transparent = ev.target.checked;
    water.material.uniforms.alpha.value = ev.target.checked ? 0.35 : 1.0;
    water.material.depthWrite = !ev.target.checked;
    water.material.needsUpdate = true;
  });
  let moving = true;
  hud.querySelector('.marine-hud-move').addEventListener('change', (ev) => { moving = ev.target.checked; });
  setTime();

  // The camera: from over the water, looking at the berth.
  const focus = new THREE.Vector3((frame.minX + frame.maxX) / 2, frame.top, (frame.front + bbox.max.z) / 2);
  // Far enough back to take in the berth, the cranes and the ship, whatever the model's size.
  const radius = Math.max(bbox.getSize(new THREE.Vector3()).length() / 2, ((twin.alongside || {}).loa || 0) * 0.8, 120);
  camera.position.copy(focus).add(new THREE.Vector3(radius * 0.8, radius * 0.95, -radius * 1.25));
  controls.target.copy(focus);
  controls.maxDistance = 4000;
  camera.updateProjectionMatrix();

  // Picking: a click (not a drag) on an element shows it beside the view.
  const ray = new THREE.Raycaster();
  let downAt = null;
  let picked = null;
  renderer.domElement.addEventListener('pointerdown', (ev) => { downAt = [ev.clientX, ev.clientY]; });
  renderer.domElement.addEventListener('pointerup', (ev) => {
    if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 4) return;
    const rect = renderer.domElement.getBoundingClientRect();
    const at = new THREE.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
    ray.setFromCamera(at, camera);
    const hit = ray.intersectObjects(clickable, false)[0];
    if (picked) for (const m of clickable) if (m.userData.element === picked) m.material.emissive?.setHex(0x000000);
    picked = hit ? hit.object.userData.element : null;
    if (picked) {
      for (const m of clickable) {
        if (m.userData.element === picked) {
          m.material = m.material.clone();
          m.material.emissive?.setHex(0x333333);
        }
      }
    } else {
      paint();
    }
    showElement(picked);
  });

  window.addEventListener('resize', () => {
    if (!view.clientWidth || !view.clientHeight) return;   // on a section tab not showing
    camera.aspect = view.clientWidth / view.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(view.clientWidth, view.clientHeight);
  });

  // The live port: the player takes over the clock, the ships, the cranes and the weather.
  let player = null;
  if (LIVE) {
    progress(0.8, 'Loading the next two days at the berth', 0.1);
    const { startLive } = await import('./marinetwin-live.js');
    player = await startLive({
      THREE, view, scene, camera, controls, renderer, twin, frame, site, rng, focus, radius, water, sky, sunLight, hemi,
      ship, vehicle, box, REAL, BOX_COLOURS,
      setClock(ms) { clock = ms; setTime(); },
      setTide(fn) { tideSource = fn; },
      setMoving(on) { moving = on; },
    });
  }

  // The lifecycle: the design life month by month, the parts wearing and being mended on the model.
  if (LIFE) {
    progress(0.9, 'Running the design life', 0.08);
    const { startLife } = await import('./marinetwin-life.js');
    player = await startLife({
      THREE, view, scene, camera, controls, renderer, twin, frame, site, rng, focus, radius, water, sky, sunLight, hemi,
      ship, box, REAL, clickable, content,
      setClock(ms) { clock = ms; setTime(); },
      setTide(fn) { tideSource = fn; },
      setMoving(on) { moving = on; },
    });
  }

  // The terminal at work.
  const timer = new THREE.Clock();
  let t = 0;
  const point = new THREE.Vector3();
  const ahead = new THREE.Vector3();
  function animate() {
    const dt = Math.min(timer.getDelta(), 0.1);
    water.material.uniforms.time.value += dt * 0.6 * (1 + (player ? player.hs : hs));
    if (player) player.tick(dt);
    if (moving) {
      const pace = player ? player.pace : 1;
      t += dt * pace;
      for (const m of site.movers) {
        if (m.curve) {
          if (player && m.apron && !player.working) continue;      // nothing to carry: the apron waits
          m.u = ((m.u ?? m.offset) + dt * pace * m.speed) % 1;
          const u = m.u;
          m.curve.getPointAt(u, point);
          m.curve.getPointAt((u + 0.002) % 1, ahead);
          m.object.position.copy(point);
          m.object.lookAt(ahead.x, point.y, ahead.z);
          m.object.rotateY(-Math.PI / 2);
        } else if (m.swing) {
          const s = (Math.sin(2 * Math.PI * (t + m.swing.phase) / m.swing.period) + 1) / 2;
          m.object.position[m.swing.axis] = m.swing.from + (m.swing.to - m.swing.from) * s;
        }
      }
      for (const c of player ? [] : site.cranes) {     // the live player works the cranes itself
        const u = c.userData;
        if (u.trolley && u.working) {
          const s = (Math.sin(t * 0.35 + c.position.x) + 1) / 2;
          u.trolley.position.z = -28 + 40 * s;
          u.spreader.position.y = -10 - 22 * Math.abs(Math.sin(t * 0.7 + c.position.x));
        }
        if (u.top && u.working) u.top.rotation.y = 0.9 * Math.sin(t * 0.18 + c.position.x);
      }
      if (vessel) vessel.rotation.x = 0.004 * Math.sin(t * 0.6) * (1 + hs);
    }
    controls.update();
    renderer.render(scene, camera);
  }
  renderer.setAnimationLoop(animate);
  if (voyage) await voyage.done('Ready');
  if (voyage) voyage.remove();
  view.dataset.ready = String(clickable.length);
}

if (view) {
  main().catch((err) => {
    console.error(err);
    if (voyage) voyage.remove();
    note('The 3D view could not start: ' + (err.message || err));
  });
}
