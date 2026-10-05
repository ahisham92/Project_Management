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
import { mergeGeometries } from 'three/addons/BufferGeometryUtils.js';
import { yardStacks, yardCrane, boxesIn, BAY } from './marinetwin-yard.js';
import { addFlag, flagCode, FLAG_NAMES } from './marinetwin-flags.js';

const view = document.querySelector('.marine-view');
// The live port (step 4) plays the next two days through the same scene: marinetwin-live.js drives it.
const LIVE = view && view.dataset.mode === 'live';
// The lifecycle (step 5) plays the whole design life through it: marinetwin-life.js drives that.
const LIFE = view && view.dataset.mode === 'life';
// The risks page (step 6) shows one extreme event at a time on the model: damage and the area closed.
const RISK = view && view.dataset.mode === 'risk';
// The sensors plan (step 7) marks every planned sensor on the model, coloured by its check in a year.
const PLAN = view && view.dataset.mode === 'plan';
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
// The pool of light under each high mast at night: drawn, not lit, so a quay kilometres long can
// have hundreds of them. Off by day and when the power is cut.
const GLOW = new THREE.MeshBasicMaterial({ color: 0xffc98a, transparent: true, opacity: 0.2, blending: THREE.AdditiveBlending, depthWrite: false });
GLOW.visible = false;
// A ship's own lights: lit at night whatever the shore's power is doing.
const SHIP_LAMP = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff0d0, emissiveIntensity: 0 });
const SHIP_GLOW = new THREE.MeshBasicMaterial({ color: 0xfff1d6, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending, depthWrite: false });
SHIP_GLOW.visible = false;
const SHIP_HOUSE = new THREE.MeshStandardMaterial({ color: 0xeeeeea, roughness: 0.6, emissive: 0x4a3c26, emissiveIntensity: 0 });
const NAV = {
  red: new THREE.MeshBasicMaterial({ color: 0xff2a2a }), green: new THREE.MeshBasicMaterial({ color: 0x22ff66 }),
  white: new THREE.MeshBasicMaterial({ color: 0xffffff }),
};
const REAL_FOR_KIND = {
  pile: 'steel', combi_wall: 'steel', sheet_pile: 'steel', beam: 'concrete', slab: 'concrete', fender: 'rubber',
  bollard: 'steel', crane_rail: 'steel', crane_stopper: 'yellow', storm_pin: 'yellow', ladder: 'yellow', tie_rod: 'steel',
  ramp: 'steel', other: 'concrete',
};
// The yard cranes' paint: yellow steel, a white trolley and cab, black ropes.
const RTG_MATS = {
  frame: REAL.yellow, trolley: REAL.white, cab: REAL.glass, spreader: REAL.yellow,
  rope: new THREE.MeshBasicMaterial({ color: 0x222222 }),
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

// The browser keeps the model it downloaded (the IFC, or the shapes kept from it) in its own
// cache, so going to another step and back opens it from the computer, not the network. One
// entry per asset: a newer model or newer shapes replace the older ones. `version` changes with
// the model file (it is the kept shapes' key), so a re-uploaded model is fetched again.
const CACHE = 'marinetwin-models-v1';
async function cachedBytes(url, version, onProgress) {
  const as = new URL(url, location.href);
  as.searchParams.set('v', version);
  let cache = null;
  try {
    cache = await caches.open(CACHE);
    const hit = await cache.match(as.href);
    if (hit) {
      const bytes = await hit.arrayBuffer();
      onProgress(1, bytes.byteLength, bytes.byteLength);
      return bytes;
    }
  } catch (err) { cache = null; }       // no cache here (a private window, an http address): just download
  const bytes = await fetchWithProgress(url, onProgress);
  if (cache) {
    const asset = as.pathname.replace(/\/model.*$/, '/model');
    (async () => {
      for (const old of await cache.keys()) if (new URL(old.url).pathname.startsWith(asset) && old.url !== as.href) await cache.delete(old);
      await cache.put(as.href, new Response(bytes));
    })().catch((err) => console.warn('The model could not be kept in this browser', err));
  }
  return bytes;
}
const keyOf = (url) => (url ? url.split('/').pop() : 'none');

async function loadKept(url) {
  const zipped = await cachedBytes(url, keyOf(url), (f, got, total) =>
    progress(0.8 * f, `Opening the Revit model: ${MB(got)} of ${MB(total)} MB`, 0, true));
  const raw = await new Response(new Blob([zipped]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
  const { parts, origin } = unpackShapes(raw);
  return meshesFrom(parts, origin);
}

// A product web-ifc has been on this long is taken as one it will never finish (a broken void or
// sweep in the export): the reader starts again without it, up to SKIP_MOST of them.
const STUCK_MS = 25000;
const SKIP_MOST = 12;

// Reads the IFC in a worker, starting it again past any product it gets stuck on.
async function readIfc(url, base, refs, keepAt) {
  const bytes = await cachedBytes(url, keyOf(keepAt), (f, got, total) =>
    progress(0.6 * f, `Downloading the Revit model: ${MB(got)} of ${MB(total)} MB`, 0, true));
  const skipped = [];
  for (;;) {
    const got = await readOnce(bytes, base, refs, keepAt, skipped.map((s) => s.id));
    if (got.stuck) {
      skipped.push(got.stuck);
      if (skipped.length > SKIP_MOST) throw new Error(`the reader got stuck on ${skipped.length} objects (the last: ${got.stuck.name})`);
      continue;
    }
    if (skipped.length) {
      note(`Left out ${skipped.length} object${skipped.length > 1 ? 's' : ''} the reader could not build: ${skipped.map((s) => s.name).join(', ')}. ` +
        'Check their geometry in Revit (often a void or sweep) and export again.');
    }
    return got;
  }
}

// One go: resolves with the parts, or with {stuck} when a product takes longer than STUCK_MS.
function readOnce(bytes, base, refs, keepAt, skip) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('marinetwin-ifc-worker.js', import.meta.url), { type: 'module' });
    const parts = [];
    let reading = null;
    let at = null;
    let since = 0;
    let shown = 0;
    let watch = null;
    const stop = () => { clearTimeout(reading); clearInterval(watch); worker.terminate(); };
    progress(0.6, skip.length ? `Reading the model again, without ${skip.length} object${skip.length > 1 ? 's' : ''} it got stuck on` :
      'Reading the model. A big Revit model can take a minute or two the first time', 0.1);
    worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === 'progress' && m.stage === 'open') {
        reading = setTimeout(() => note('Still reading the model: big Revit exports take a while the first time. It is kept after that.'), 45000);
      } else if (m.type === 'progress' && m.stage === 'shapes') {
        clearTimeout(reading);
        progress(0.7, `Building the model: 0 of ${m.total.toLocaleString()} objects`);
      } else if (m.type === 'at') {
        at = m;
        since = performance.now();
        if (!watch) {
          watch = setInterval(() => {
            const waited = performance.now() - since;
            if (waited > 5000) progress(0.7 + 0.15 * (at.done / at.total), `Building the model: ${at.done.toLocaleString()} of ${at.total.toLocaleString()} objects, on ${at.name} for ${Math.round(waited / 1000)} s`);
            if (waited > STUCK_MS) { stop(); resolve({ stuck: { id: at.id, name: at.name } }); }
          }, 1000);
        }
        if (since - shown > 200) {
          shown = since;
          progress(0.7 + 0.15 * (m.done / m.total), `Building the model: ${m.done.toLocaleString()} of ${m.total.toLocaleString()} objects`);
        }
      } else if (m.type === 'part') {
        parts.push(m);
      } else if (m.type === 'kept') {
        if (!m.ok) console.warn('The shapes could not be kept on the server', m.why || '');
      } else if (m.type === 'done') {
        clearTimeout(reading);
        clearInterval(watch);
        resolve({ parts, origin: m.origin });   // the reader closes itself once it has kept the shapes
      } else if (m.type === 'error') {
        stop();
        reject(new Error(m.message));
      }
    };
    worker.onerror = (ev) => { stop(); reject(new Error(ev.message || 'the model reader stopped')); };
    // A copy, so the page still has the bytes if the reader has to start again.
    worker.postMessage({ bytes, base, refs, skip, keepAt: keepAt ? new URL(keepAt, location.href).href : null });
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

// --- the quay line ---------------------------------------------------------------------
// A long quay is seldom one straight berth: it runs in legs, bending with the shore, with the
// land behind it and the sea in front. Its fenders line its front, so their positions in plan,
// put in order along the quay and straightened, give the legs; the deck behind them says which
// side is land. Points are [x, z] in the model's plan.

// The points in order along the quay: from one end, always to the nearest not yet taken.
function alongQuay(points) {
  const centre = points.reduce((a, p) => [a[0] + p[0] / points.length, a[1] + p[1] / points.length], [0, 0]);
  let at = points.reduce((best, p) => (Math.hypot(p[0] - centre[0], p[1] - centre[1]) > Math.hypot(best[0] - centre[0], best[1] - centre[1]) ? p : best));
  const left = new Set(points);
  left.delete(at);
  const out = [at];
  while (left.size) {
    let next = null;
    let d = Infinity;
    for (const p of left) {
      const e = (p[0] - at[0]) ** 2 + (p[1] - at[1]) ** 2;
      if (e < d) { d = e; next = p; }
    }
    left.delete(next);
    out.push(next);
    at = next;
  }
  return out;
}

// Douglas–Peucker: the fewest corners that stay within `tol` metres of every point.
function straighten(points, tol) {
  if (points.length < 3) return points;
  const [a, b] = [points[0], points[points.length - 1]];
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  let worst = 0;
  let k = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const d = Math.abs((b[0] - a[0]) * (a[1] - points[i][1]) - (a[0] - points[i][0]) * (b[1] - a[1])) / len;
    if (d > worst) { worst = d; k = i; }
  }
  if (worst <= tol) return [a, b];
  return [...straighten(points.slice(0, k + 1), tol).slice(0, -1), ...straighten(points.slice(k), tol)];
}

// The quay's legs, each {a, b, dir, len, from} (from: its distance along the quay), with `land`,
// the unit vector across the legs towards the land (+1 or -1 times each leg's left normal).
function quayLine(front, deck) {
  if (front.length < 4) return null;
  const sample = front.length > 4000 ? front.filter((_, i) => i % Math.ceil(front.length / 4000) === 0) : front;
  const corners = straighten(alongQuay(sample), 4);
  const legs = [];
  let from = 0;
  for (let i = 0; i + 1 < corners.length; i++) {
    const [a, b] = [corners[i], corners[i + 1]];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (len < 1) continue;
    legs.push({ a, b, dir: [(b[0] - a[0]) / len, (b[1] - a[1]) / len], len, from });
    from += len;
  }
  if (!legs.length) return null;
  // The deck lies on the land side: count its parts left and right of the leg each is beside.
  let side = 0;
  for (const p of deck) {
    for (const l of legs) {
      const t = (p[0] - l.a[0]) * l.dir[0] + (p[1] - l.a[1]) * l.dir[1];
      const d = (p[1] - l.a[1]) * l.dir[0] - (p[0] - l.a[0]) * l.dir[1];
      if (t >= 0 && t <= l.len && Math.abs(d) < 80) { side += Math.sign(d); break; }
    }
  }
  const land = side >= 0 ? 1 : -1;       // +1: land to the left of the direction of travel
  for (const l of legs) {
    l.land = [-l.dir[1] * land, l.dir[0] * land];
    l.sea = [-l.land[0], -l.land[1]];
  }
  return { legs, length: from };
}

// A point's distance along the quay, the leg it is by, and how far off the line.
function onQuay(quay, p) {
  let best = null;
  for (const l of quay.legs) {
    const t = Math.max(0, Math.min(l.len, (p[0] - l.a[0]) * l.dir[0] + (p[1] - l.a[1]) * l.dir[1]));
    const off = Math.hypot(l.a[0] + l.dir[0] * t - p[0], l.a[1] + l.dir[1] * t - p[1]);
    if (!best || off < best.off) best = { leg: l, s: l.from + t, t, off };
  }
  return best;
}

// The point `along` metres along the quay, `inland` metres towards the land.
function quayPoint(quay, along, inland = 0) {
  const leg = quay.legs.find((l) => along <= l.from + l.len) || quay.legs[quay.legs.length - 1];
  const t = Math.max(0, Math.min(leg.len, along - leg.from));
  return { x: leg.a[0] + leg.dir[0] * t + leg.land[0] * inland, z: leg.a[1] + leg.dir[1] * t + leg.land[1] * inland, leg };
}

// Turned in plan by three's rotation.y = angle: [x, z] goes to [x cos + z sin, -x sin + z cos].
function turned(p, angle) {
  const [c, s] = [Math.cos(angle), Math.sin(angle)];
  return [p[0] * c + p[1] * s, -p[0] * s + p[1] * c];
}
function turnQuay(quay, angle) {
  let from = 0;
  for (const l of quay.legs) {
    l.a = turned(l.a, angle); l.b = turned(l.b, angle);
    l.dir = turned(l.dir, angle); l.land = turned(l.land, angle); l.sea = turned(l.sea, angle);
    l.from = from; from += l.len;
  }
  return quay;
}

// The rotation.y that turns a thing facing the sea along -z to face along `sea`.
const facing = (sea) => Math.atan2(-sea[0], -sea[1]);

// The crane bays: between two crane stoppers (both rails' stoppers at one end counted once) one
// rail-mounted crane runs, over a straight stretch of 60 to 700 m.
function craneBays(quay, stoppers) {
  const ends = [];
  for (const s of stoppers.map((p) => onQuay(quay, p)).filter((q) => q.off < 60).sort((a, b) => a.s - b.s)) {
    const last = ends[ends.length - 1];
    if (last && s.s - last.s < 30) continue;
    ends.push(s);
  }
  const bays = [];
  for (let i = 0; i + 1 < ends.length; i++) {
    const gap = ends[i + 1].s - ends[i].s;
    if (gap >= 60 && gap <= 700) bays.push({ from: ends[i].s, to: ends[i + 1].s });
  }
  return bays;
}

// The land behind the quay and the paved apron and yard on it, following the legs: the land
// carries on past both ends of the modelled quay, and its edge is the quay wall down to the sea.
function shore(quay, top, yardDepth) {
  const g = new THREE.Group();
  const set = 2;      // the line runs through the fenders: the land starts at the wall just behind
  const first = quay.legs[0];
  const last = quay.legs[quay.legs.length - 1];
  const pt = (p, v, k) => [p[0] + v[0] * k, p[1] + v[1] * k];
  const line = [pt(pt(first.a, first.land, set), first.dir, -3000)];
  for (const l of quay.legs) line.push(pt(l.a, l.land, set));
  line.push(pt(last.b, last.land, set));
  line.push(pt(pt(last.b, last.land, set), last.dir, 3000));
  const outline = [...line, pt(line[line.length - 1], last.land, 6000), pt(line[0], first.land, 6000)];
  quay.landOutline = outline;           // for keeping the ships on the water (seaChecker)
  const shape = new THREE.Shape(outline.map(([x, z]) => new THREE.Vector2(x, -z)));
  const below = 8;
  const land = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: top - 0.3 + below, bevelEnabled: false }), REAL.land);
  land.rotation.x = -Math.PI / 2;
  land.position.y = -below;
  land.receiveShadow = true;
  land.userData.ground = true;            // cut where the map has water, where the site is located
  g.add(land);
  // The apron and yard: a band along each leg, and a wedge at each bend to close it.
  const v = [];
  const tri = (p, q, r) => { for (const [x, z] of [p, q, r]) v.push(x, top - 0.05, z); };
  const legs = quay.legs;
  legs.forEach((l, i) => {
    const [a, b] = [pt(l.a, l.land, set), pt(l.b, l.land, set)];
    const [a2, b2] = [pt(a, l.land, yardDepth), pt(b, l.land, yardDepth)];
    tri(a, a2, b); tri(b, a2, b2);
    if (i + 1 < legs.length) {
      const n = legs[i + 1];
      tri(b, pt(b, l.land, yardDepth), pt(b, n.land, yardDepth));
    }
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
  geo.computeVertexNormals();
  const yard = new THREE.Mesh(geo, REAL.asphalt.clone());
  yard.material.side = THREE.DoubleSide;
  yard.receiveShadow = true;
  g.add(yard);
  return g;
}

// The berths along a traced quay, in order along it and numbered from 1. Crane bays next to each
// other on a leg make one berth with rail-mounted cranes (up to about 420 m); every stretch of 150 m
// or more without crane stoppers is cut into berths of about 300 m. The berth where the model's
// middle lies is the main one, whose ship line-up the live port plays from the server.
function quayBerths(quay, bays, mainAt) {
  const berths = [];
  for (const leg of quay.legs) {
    const end = leg.from + leg.len;
    const spans = [];
    let cur = null;
    for (const b of bays.filter((x) => x.from >= leg.from - 5 && x.to <= end + 5)) {
      if (cur && b.from - cur.to < 30 && b.to - cur.from <= 420) cur.to = b.to;
      else { cur = { from: b.from, to: b.to, sts: true }; spans.push(cur); }
    }
    const free = [];
    let at = leg.from;
    for (const sp of [...spans]) { if (sp.from - at >= 150) free.push([at, sp.from]); at = Math.max(at, sp.to); }
    if (end - at >= 150) free.push([at, end]);
    for (const [a, z] of free) {
      const n = Math.max(1, Math.floor((z - a) / 300));
      for (let k = 0; k < n; k++) spans.push({ from: a + (k * (z - a)) / n, to: a + ((k + 1) * (z - a)) / n, sts: false });
    }
    for (const sp of spans) berths.push({ leg, from: sp.from, to: sp.to, mid: (sp.from + sp.to) / 2, length: sp.to - sp.from, sts: sp.sts });
  }
  berths.sort((a, b) => a.from - b.from);
  berths.forEach((b, i) => { b.n = i + 1; b.main = false; });
  const main = berths.find((b) => mainAt >= b.from && mainAt <= b.to)
    || berths.reduce((best, b) => (!best || Math.abs(b.mid - mainAt) < Math.abs(best.mid - mainAt) ? b : best), null);
  if (main) main.main = true;
  return berths;
}

// How a ship lies at a berth along a leg: rotation, and which way its bow points along the leg
// (+1 towards the leg's end). Its port side, where a car carrier's stern ramp comes down, is
// towards the land.
function shipPose(b) {
  const { dir, land } = b.leg;
  const bow = Math.sign(land[0] * -dir[1] + land[1] * dir[0]) || 1;
  return { bow, rot: Math.atan2(-dir[1], dir[0]) + (bow < 0 ? Math.PI : 0) };
}

// Where the main berth's ship lies: at the middle of the main berth along a traced quay (or of the
// model), how she is turned, how long she may be to stay inside her berth, and which way is sea.
function berthSpot(site, frame, beam) {
  const b = site.mainBerth;
  if (site.quay && b && b.leg) {
    const p = quayPoint(site.quay, b.mid, -(beam / 2 + 2));
    return { x: p.x, z: p.z, rot: shipPose(b).rot, room: b.length - 20, sea: [-b.leg.land[0], -b.leg.land[1]] };
  }
  return { x: (frame.minX + frame.maxX) / 2, z: frame.fenderFace - beam / 2 - 0.4, rot: 0, room: Infinity, sea: [0, -1] };
}

// Whether a point in plan is on the water, `margin` metres clear of the land behind the quay (and
// of the land past its ends), so no ship is drawn or steered across the deck or the yard.
function seaChecker(quay, frame) {
  const poly = quay && quay.landOutline;
  const inside = (x, z) => {
    if (!poly) return z > frame.fenderFace;
    let inn = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, zi] = poly[i];
      const [xj, zj] = poly[j];
      if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inn = !inn;
    }
    return inn;
  };
  const at = (x, z, margin = 0) => {
    if (inside(x, z)) return false;
    for (let k = 0; k < 8 && margin; k++) {
      const a = (k * Math.PI) / 4;
      if (inside(x + Math.cos(a) * margin, z + Math.sin(a) * margin)) return false;
    }
    return true;
  };
  // Every point along a run of points (or a curve) on the water.
  at.clear = (pts, margin = 0, steps = 60) => {
    if (pts.getPointAt) {
      for (let i = 0; i <= steps; i++) { const p = pts.getPointAt(i / steps); if (!at(p.x, p.z, margin)) return false; }
      return true;
    }
    for (let i = 1; i < pts.length; i++) {
      const [a, b] = [pts[i - 1], pts[i]];
      const n = Math.max(2, Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / 20));
      for (let k = 0; k <= n; k++) if (!at(a.x + (b.x - a.x) * k / n, a.z + (b.z - a.z) * k / n, margin)) return false;
    }
    return true;
  };
  return at;
}

// Where the next ship waits at anchor off the berth: seaward, on open water, with a clear run in.
function anchorSpot(spot, atSea) {
  const along = [-spot.sea[1], spot.sea[0]];
  for (const d of [700, 900, 500, 1200, 1600, 2200, 3000]) {
    for (const s of [0, 300, -300, 600, -600, 1000, -1000, 1600, -1600]) {
      const p = { x: spot.x + spot.sea[0] * d + along[0] * s, z: spot.z + spot.sea[1] * d + along[1] * s };
      if (atSea(p.x, p.z, 250) && atSea.clear([{ x: spot.x + spot.sea[0] * 80, z: spot.z + spot.sea[1] * 80 }, p], 40)) return p;
    }
  }
  return null;
}

// The ship type a berth takes for the use it is set to; a berth used for both alternates.
function berthShipType(use, k = 0) {
  return { container: 'container ship', general_cargo: 'general cargo', roro: 'ro-ro', bulk: 'bulk carrier' }[use]
    || (use === 'mixed' ? (k % 2 ? 'ro-ro' : 'general cargo') : 'container ship');
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

// Containers, many at once: one instanced mesh with a colour per box. The boxes are ordered tier
// by tier, bottom first, so showing fewer of them (setFill) takes the top tiers off everywhere, as
// a ship being discharged or a yard being emptied looks; `full` stacks every row to the top.
function containerStacks(blocks, rng, full = false) {
  const boxes = [];
  for (const b of blocks) {
    for (let bay = 0; bay < b.bays; bay++) {
      for (let row = 0; row < b.rows; row++) {
        const height = full ? b.tiers : Math.floor(rng() * (b.tiers + 1));
        for (let tier = 0; tier < height; tier++) {
          boxes.push({ x: b.x + bay * 12.6, y: b.y + 1.3 + tier * 2.6, z: b.z + row * 2.6, tier, key: tier + rng() * 0.9,
            colour: BOX_COLOURS[Math.floor(rng() * BOX_COLOURS.length)] });
        }
      }
    }
  }
  boxes.sort((a, b) => a.key - b.key);
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(12.0, 2.55, 2.4), new THREE.MeshStandardMaterial({ roughness: 0.7, metalness: 0.2 }), Math.max(1, boxes.length));
  const m = new THREE.Matrix4();
  const colour = new THREE.Color();
  boxes.forEach((x, i) => {
    mesh.setMatrixAt(i, m.makeTranslation(x.x, x.y, x.z));
    mesh.setColorAt(i, colour.setHex(x.colour));
  });
  mesh.count = boxes.length;
  mesh.userData.total = boxes.length;
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

// A berth's yard holds more while its ship is discharged into it and less as the ship is loaded
// from it: the share of the yard's boxes shown for how full the ship lying there is.
function yardFill(berth) {
  const f = berth && berth.fill !== undefined ? berth.fill : 0.6;
  return 0.55 + 0.4 * (1 - f);
}

// Show a share (0 to 1) of a stack's boxes, top tiers going first.
function setFill(mesh, f) {
  if (!mesh) return;
  if (mesh.userData.yard) { mesh.userData.yard.setTarget(f); return; }     // a yard follows, box by box
  mesh.count = Math.round(mesh.userData.total * Math.max(0, Math.min(1, f)));
}

// --- the cards ---------------------------------------------------------------------------
// What a click on a crane, a vehicle, a stack or a ship shows on the right of the view: each
// gets a userData.pick that says what it is and, asked again as the clock runs, what it is doing.
const CRANE_STATE = { working: 'good', idle: 'neutral', stopped: 'warning', stowed: 'warning', down: 'critical' };
const capital = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const pct = (f) => `${Math.round(Math.max(0, Math.min(1, f)) * 100)}%`;
const berthName = (b) => (!b ? '' : b.n !== undefined ? `Berth ${b.n}${b.main ? ' (main)' : ''}` : 'Main berth');
function fillOf(mesh, b) {
  const s = mesh.userData.stacks;
  if (s && s.userData.total) return s.count / s.userData.total;
  return b && b.fill !== undefined ? b.fill : null;
}
function shipKindWord(type) { return String(type || 'ship').replace('ro-ro', 'car carrier (RoRo)'); }

function shipCardStill(a, now, mesh, b) {
  return {
    kind: shipKindWord(a.type), title: a.name,
    rows: [['Berth', berthName(b)], ['Now', now], ['Flag', a.flag_name || FLAG_NAMES[mesh.userData.flag]], ['Length overall', `${a.loa} m`], ['Beam', `${a.beam} m`], ['Draught', `${a.draught} m`],
      ['Cargo aboard', fillOf(mesh, b) === null ? '' : pct(fillOf(mesh, b))],
      ['Arrives', a.eta ? new Date(a.eta).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : '']],
  };
}

function tagSite(site, twin) {
  const equipment = twin.equipment || [];
  const perBerth = new Map();
  site.cranes.forEach((c, i) => {
    const u = c.userData;
    const what = u.mobile ? 'Mobile harbour crane' : u.trolley ? (site.kind === 'bulk' ? 'Ship unloader' : 'Ship-to-shore crane') : 'Crane';
    let name;
    if (u.berth) {
      const k = (perBerth.get(u.berth) || 0) + 1;
      perBerth.set(u.berth, k);
      name = `${berthName(u.berth)} · ${u.mobile ? 'MHC' : 'STS'} ${k}`;
    } else {
      name = (equipment[i] && equipment[i].name) || `Crane ${i + 1}`;
    }
    u.pick = () => {
      // The live port sets state, why, doing and shipName each frame; the still view has the day's.
      const state = u.state || (u.idle ? 'idle' : !u.berth && equipment[i] ? equipment[i].state : u.working ? 'working' : 'idle');
      const why = u.why !== undefined ? u.why : !u.berth && equipment[i] ? equipment[i].why : '';
      const b = u.berth || site.mainBerth;
      const doing = u.doing || (state !== 'working' ? '' : b && b.state === 'loading' ? 'Loading, quay to ship' : b && b.state ? 'Discharging, ship to quay' : 'No ship to work');
      return {
        kind: what, title: name, state: CRANE_STATE[state] || 'neutral', stateWord: capital(state),
        rows: [['Berth', berthName(b)], ['Doing', doing], ['Why', why], ['Ship', u.shipName || ''],
          ['Power', u.mobile ? 'Diesel, on its own' : 'Electric, from the grid'],
          ['Next service', !u.berth && equipment[i] && equipment[i].service_in_h ? `in ${equipment[i].service_in_h} h` : '']],
      };
    };
  });
  for (const m of site.movers) {
    const o = m.object;
    if (o.userData.pick) continue;
    const what = m.gate ? 'Road truck' : m.needs === 'roro' || (!o.userData.load && m.curve && !m.load && site.kind === 'roro') ? 'Car'
      : o.userData.load ? 'Terminal tractor' : 'Truck';
    o.userData.pick = () => ({
      kind: what, title: `${what}${m.berth ? ' at ' + berthName(m.berth).toLowerCase() : ''}`,
      rows: [['Berth', berthName(m.berth)],
        ['Doing', m.status || (m.curve && !m.apron ? 'On the access road, to and from the gate' : 'Driving its round')],
        ['Carrying', m.load ? (m.load.visible ? 'A box' : 'Nothing') : '']],
    });
  }
  (site.yardCranes || []).forEach((r) => {
    r.object.userData.pick = () => ({
      kind: 'Rubber-tyred gantry crane (RTG)', title: `Yard crane at ${(berthName(r.berth || site.mainBerth) || 'the yard').toLowerCase()}`,
      state: r.phase === 'park' ? 'neutral' : 'good', stateWord: r.phase === 'park' ? 'Parked' : 'Working',
      rows: [['Berth', berthName(r.berth || site.mainBerth)], ['Block', r.block.back ? 'Back row, for the gate' : 'Front row, for the ship'],
        ['Doing', r.status], ['Carrying', r.carrying ? 'A box' : 'Nothing'],
        ['Waiting for it', r.queue.length ? `${r.queue.length} tractor${r.queue.length > 1 ? 's or trucks' : ' or truck'}` : ''],
        ['Stacks', '6 rows, 1 over 4 high'], ['Power', 'Diesel-electric, on its own']],
    });
  });
  for (const y of site.yards) {
    y.mesh.userData.pick = () => ({
      kind: 'Container yard', title: `${berthName(y.berth) || 'Yard'} stacks`,
      rows: [['Boxes in the stacks', `${boxesIn(y.mesh).toLocaleString()} of ${y.mesh.userData.total.toLocaleString()} slots`],
        ['Full', pct(boxesIn(y.mesh) / y.mesh.userData.total)],
        ['Why', y.berth && y.berth.state ? `${capital(y.berth.state)} the ship alongside: the stacks ${y.berth.state === 'loading' ? 'empty' : 'fill'} as she is worked` : 'No ship being worked']],
    });
  }
}

function makeRng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

// A ship-to-shore crane's portal (legs, ties, the beams across the top, the A-frame and its
// back-stays) as one geometry shared by every crane: a quay kilometres long has dozens.
let stsFrame = null;
function stsFrameGeometry(gauge) {
  if (stsFrame) return stsFrame;
  const parts = [];
  const add = (w, h, d, x, y, z) => { const geo = new THREE.BoxGeometry(w, h, d); geo.translate(x, y, z); parts.push(geo); };
  for (const x of [-9, 9]) {
    for (const z of [0, gauge]) { add(1.4, 44, 1.4, x, 22, z); add(3.2, 1.6, 4, x, 0.8, z); }   // legs on their bogies
    add(1.2, 1.2, gauge, x, 30, gauge / 2);
    add(1.0, 1.0, gauge, x, 12, gauge / 2);
    add(1.0, 16, 1.0, x, 54, gauge - 2);                                  // the A-frame over the land legs
  }
  add(20, 1.6, 1.6, 0, 44, 0);
  add(20, 1.6, 1.6, 0, 44, gauge);
  add(20, 1.2, 1.2, 0, 62, gauge - 2);
  stsFrame = mergeGeometries(parts);
  return stsFrame;
}

function stsCrane(state) {
  const g = new THREE.Group();
  const gauge = 30;
  const portal = new THREE.Mesh(stsFrameGeometry(gauge), REAL.crane);
  portal.castShadow = portal.receiveShadow = true;
  g.add(portal);
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
  // The hook and its load at the boom's tip: a sling of cargo or a box, carried ship to quay or back.
  const hook = new THREE.Group();
  hook.add(box(0.15, 28, 0.15, REAL.steel, 0, 14, 0));
  const load = box(6, 2.4, 2.4, REAL.shed, 0, -1.2, 0);
  hook.add(load);
  hook.position.set(0, -12, -43);
  top.add(hook);
  top.position.set(0, 26, 0);
  g.add(top);
  g.userData = { top, load, working: state === 'working', mobile: true };
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
    g.userData.load = box(11.6, 2.55, 2.35, new THREE.MeshStandardMaterial({ color: BOX_COLOURS[(colour >> 3) % BOX_COLOURS.length], roughness: 0.7 }), 0, 2.7, 0);
    g.add(g.userData.load);
  } else {
    g.add(box(3, 2.8, 2.4, paint, 6.5, 1.8, 0));
    g.add(box(12, 3.0, 2.5, REAL.shed, -0.5, 2.1, 0));
  }
  g.traverse((m) => { if (m.isMesh) m.castShadow = true; });
  return g;
}

// A ship of a type, her length, beam and draught; `flag` is the code of the flag she flies.
function ship(type, loa, beam, draught, rng, flag = 'PA') {
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
  // The accommodation and bridge, aft (forward on a car carrier); on a container ship tall
  // enough for the bridge to see over the boxes on deck, with bridge wings out to her sides.
  const houseX = kind === 'roro' ? loa / 2 - beam * 1.4 : -loa / 2 + 18;
  const houseH = kind === 'container' ? 24 : 16;
  g.add(box(14, houseH, beam * 0.9, SHIP_HOUSE, houseX, deck + houseH / 2, 0));
  g.add(box(4, 1.4, beam * 0.92, REAL.glass, houseX + 7.2, deck + houseH - 2, 0));
  g.add(box(5, 0.6, beam, SHIP_HOUSE, houseX + 4.5, deck + houseH - 2.9, 0));
  g.add(cylinder(2.2, 8, REAL.crane, houseX - 4, deck + houseH + 4, 0));
  // Where the officer of the watch stands, looking forward through the windows (the Bridge camera).
  g.userData.bridge = new THREE.Vector3(houseX + 7.8, deck + houseH - 1.6, 0);
  // Her flag on the ensign staff at the stern.
  addFlag(g, -loa / 2 + 1.2, freeboard, flag, REAL.steel);
  const lights = [];
  if (kind === 'container') {
    const blocks = [];
    for (let x = houseX + 14; x < loa / 2 - beam; x += 13.2 * 3 + 2) {
      blocks.push({ x, y: deck, z: -beam / 2 + 1.5, bays: 3, rows: Math.floor((beam - 2) / 2.6), tiers: 6 });
    }
    g.userData.stacks = containerStacks(blocks, rng, true);
    g.add(g.userData.stacks);
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
  // Her own lights, on her own generators: deck floodlights along both sides with the pools they
  // throw on deck and on the water, and the navigation lights. All on at night, power cut or not.
  const lampHeight = kind === 'container' ? deck + 19 : kind === 'roro' ? deck + 6 : deck + 12;
  const spots = [];
  for (let x = -loa / 2 + 24; x < loa / 2 - beam; x += 36) for (const z of [-beam / 2 + 0.6, beam / 2 - 0.6]) spots.push([x, z]);
  const many = (geo, mat, n, place) => {
    const im = new THREE.InstancedMesh(geo, mat, n);
    const m4 = new THREE.Matrix4();
    for (let i = 0; i < n; i++) im.setMatrixAt(i, place(m4, i));
    g.add(im);
    return im;
  };
  const flat = new THREE.Matrix4().makeRotationX(-Math.PI / 2);
  const post = lampHeight - deck;
  many(new THREE.BoxGeometry(0.3, post, 0.3), REAL.steel, spots.length, (m, i) => m.makeTranslation(spots[i][0], deck + post / 2, spots[i][1]));
  many(new THREE.BoxGeometry(1.4, 0.6, 1.4), SHIP_LAMP, spots.length, (m, i) => m.makeTranslation(spots[i][0], lampHeight, spots[i][1]));
  // Pools on the water beside her, and on her deck where there are no boxes to hide it.
  many(new THREE.CircleGeometry(18, 20), SHIP_GLOW, spots.length,
    (m, i) => m.makeTranslation(spots[i][0], 0.35, spots[i][1] + Math.sign(spots[i][1]) * 14).multiply(flat));
  if (kind !== 'container') {
    const xs = spots.filter((_, i) => i % 2 === 0).map(([x]) => x);
    many(new THREE.CircleGeometry(beam * 0.45, 20), SHIP_GLOW, xs.length,
      (m, i) => m.makeTranslation(xs[i], deck + (kind === 'roro' ? 4.1 : 1.7), 0).multiply(flat));
  }
  const nav = (mat, x, y, z) => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.9, 8, 6), mat); m.position.set(x, y, z); g.add(m); };
  nav(NAV.red, houseX + 6, deck + houseH - 1, -beam * 0.47);
  nav(NAV.green, houseX + 6, deck + houseH - 1, beam * 0.47);
  nav(NAV.white, houseX - 4, deck + houseH + 9, 0);
  nav(NAV.white, loa / 2 - 6, deck + 6, 0);
  g.userData.lights = lights;
  g.userData.kind = kind;
  g.userData.draught = draught;
  Object.assign(g.userData, { loa, beam, deck });
  return g;
}

function mastLight(height) {
  const g = new THREE.Group();
  g.add(cylinder(0.35, height, REAL.steel, 0, height / 2, 0, 8));
  const head = box(3.5, 0.8, 3.5, REAL.lamp, 0, height, 0);
  g.add(head);
  const pool = new THREE.Mesh(new THREE.CircleGeometry(height * 1.6, 32), GLOW);
  pool.rotation.x = -Math.PI / 2;
  pool.position.y = 0.12;
  g.add(pool);
  g.userData.head = head;
  return g;
}

// Many high masts at once, as one group of instanced poles, lamps and light pools: [x, z] points
// in the parent's frame, on the ground (y = 0).
function mastRow(points, height = 30) {
  const g = new THREE.Group();
  const n = points.length;
  if (!n) return g;
  const parts = [
    [new THREE.CylinderGeometry(0.35, 0.35, height, 8), REAL.steel, height / 2, false],
    [new THREE.BoxGeometry(3.5, 0.8, 3.5), REAL.lamp, height, false],
    [new THREE.CircleGeometry(height * 1.6, 32), GLOW, 0.12, true],
  ];
  const m = new THREE.Matrix4();
  const flat = new THREE.Matrix4().makeRotationX(-Math.PI / 2);
  for (const [geo, mat, y, lie] of parts) {
    const im = new THREE.InstancedMesh(geo, mat, n);
    points.forEach(([x, z], i) => { m.makeTranslation(x, y, z); if (lie) m.multiply(flat); im.setMatrixAt(i, m); });
    im.castShadow = !lie;
    g.add(im);
  }
  return g;
}

// A loop for a vehicle to drive: a closed curve through the given points.
function loop(points, y) {
  return new THREE.CatmullRomCurve3(points.map(([x, z]) => new THREE.Vector3(x, y, z)), true, 'catmullrom', 0.1);
}

function terminal(scene, frame, twin, rng, quay) {
  const { minX, maxX, front, top } = frame;
  const kind = twin.asset.terminal || 'container';
  const centre = (minX + maxX) / 2;
  const length = Math.max(maxX - minX, 120);
  const g = new THREE.Group();
  const movers = [];
  const cranes = [];
  const lights = [];
  const yards = [];            // container stacks that fill as ships are discharged and empty as they load
  const yardCranes = [];       // the RTGs working them (marinetwin-yard.js)
  const mainBlocks = [];
  // A vehicle's errand: along the points (x, z on the deck) and back, waiting at each end
  // ('shuttle'), or one way and gone ('oneway', a car off or onto a ship).
  const trip = (points, mode = 'shuttle') => {
    const curve = new THREE.CatmullRomCurve3(points.map(([x, z]) => new THREE.Vector3(x, top + 0.1, z)), false, 'catmullrom', 0.2);
    return { curve, len: curve.getLength(), mode };
  };

  // A tractor's errand from its quay crane to a yard block: from the crane (a, b) out to the
  // roadway at `approach`, then into the block's truck lane (`lane`) from one side and along it
  // to a bay, stopping under the yard crane square to the stack. P turns (along, across) into the
  // scene's plan, so the same errand works on any leg of the quay.
  function toBlock(bl, P, a, b, approach, lane) {
    const bx = bl.x + Math.floor(rng() * bl.bays) * BAY;
    const s = Math.sign(bx - a[0]) || 1;
    return { trip: trip([P(...a), P(...b), P(bx - s * 30, approach), P(bx - s * 12, lane), P(bx, lane)]), rtg: bl.crane, stopX: bx };
  }
  // A road truck from the gate for a back block: it waits at the back of the yard, drives into the
  // block's lane from the land side, has a box put on (an import collected) or taken off (an export
  // delivered), and goes back. These come whether a ship is in or not.
  function gateTruck(bl, P, lane, road, sign, extra) {
    const bx = bl.x + Math.floor(rng() * bl.bays) * BAY;
    const s = rng() < 0.5 ? 1 : -1;
    const v = vehicle('tractor', [0x37474f, 0x6d4c41, 0x1565c0, 0xeeeeee, 0x2e7d32][Math.floor(rng() * 5)]);
    g.add(v);
    const mv = { object: v, trip: trip([P(bx + s * 70, road), P(bx + s * 50, lane + sign * 20), P(bx + s * 14, lane), P(bx, lane)]), offset: rng(),
      wait: 15 + rng() * 45, far: 3, speed: 6, gate: true, needs: 'gate', load: v.userData.load, rtg: bl.crane, stopX: bx, deliver: rng() < 0.5, ...extra };
    movers.push(mv);
    return mv;
  }

  // Apron and yard: paved land behind the berth, and plain land beyond. Along a traced quay
  // they follow its legs; otherwise they are laid square behind the berth.
  const yardDepth = 320;
  if (quay) g.add(shore(quay, top, yardDepth));
  else {
  const yard = new THREE.Mesh(new THREE.PlaneGeometry(length + 600, yardDepth), REAL.asphalt);
  yard.rotation.x = -Math.PI / 2;
  yard.position.set(centre, top - 0.05, front + yardDepth / 2);
  yard.receiveShadow = true;
  g.add(yard);
  const land = new THREE.Mesh(new THREE.PlaneGeometry(8000, 4000), REAL.land);
  land.rotation.x = -Math.PI / 2;
  land.position.set(centre, top - 0.3, front + yardDepth + 2000);
  land.receiveShadow = true;
  land.userData.ground = true;            // cut where the map has water, where the site is located
  g.add(land);
  // The quay wall either side of the modelled berth, so the berth sits in a longer quay.
  for (const [a, b] of [[minX - 300, minX - 1], [maxX + 1, maxX + 300]]) {
    const wall = box(b - a, top + 6, 3, REAL.concrete, (a + b) / 2, (top - 6) / 2, front + 1.5);
    g.add(wall);
  }
  }
  // Lane markings along the apron.
  const paint = new THREE.MeshBasicMaterial({ color: 0xe9e4c9 });
  for (const z of [front + 6, front + 42]) {
    const line = new THREE.Mesh(new THREE.PlaneGeometry(quay ? length : length + 600, 0.25), paint);
    line.rotation.x = -Math.PI / 2;
    line.position.set(centre, top + 0.02, z);
    g.add(line);
  }

  const bays = quay && quay.stoppers ? craneBays(quay, quay.stoppers) : [];
  const berths = quay ? quayBerths(quay, bays, onQuay(quay, [centre, front]).s) : [];
  // The main berth's own yard behind it: along a traced quay just its stretch, the other berths
  // having theirs; otherwise the length of the model.
  let yardFrom = centre - length / 2;
  let yardLength = length;
  const main = berths.find((b) => b.main);
  if (main && main.length >= 120) {
    const [p, q] = [quayPoint(quay, main.from), quayPoint(quay, main.to)];
    yardFrom = Math.min(p.x, q.x);
    yardLength = Math.abs(q.x - p.x);
  }
  // High-mast lighting across the yard.
  // Four carry real lamps (the ones the scene lights from); the rest stand every 70 m in three rows,
  // in front of the stacks, between them and behind them.
  for (let i = 0; i < 4; i++) {
    const mast = mastLight(30);
    mast.position.set(yardFrom + (i % 2 + 0.5) * yardLength / 2, top, front + 45 + Math.floor(i / 2) * 60);
    g.add(mast);
    lights.push(mast);
  }
  const rows = [];
  for (let x = yardFrom + 35; x < yardFrom + yardLength; x += 70) for (const z of [45, 105, 165]) rows.push([x, front + z]);
  const yardMasts = mastRow(rows.filter(([x, z]) => !lights.some((l) => Math.hypot(l.position.x - x, l.position.z - z) < 30)));
  yardMasts.position.y = top;
  g.add(yardMasts);

  const equipment = twin.equipment || [];
  const stateOf = (i) => (equipment[i] ? equipment[i].state : 'working');
  const ships = twin.alongside;
  const shipLength = ships ? ships.loa : 0;

  // Rail-mounted cranes: one in each bay between crane stoppers, on the deck of whichever leg it
  // is; the rest of the quay is worked by mobile harbour cranes. Only the cranes by the berth
  // where the ship lies work; the others wait.
  const freeBerth = (x) => berths.some((b) => !b.main && !b.sts && x >= b.from && x <= b.to);
  if (bays.length) {
    const berthAt = [centre, front];
    const reach = (shipLength || 200) / 2 + 40;
    const place = (crane, along, inland) => {
      const p = quayPoint(quay, along, inland);
      crane.position.set(p.x, top, p.z);
      crane.rotation.y = facing(p.leg.sea);
      crane.userData.along = along;
      if (Math.hypot(p.x - berthAt[0], p.z - berthAt[1]) > reach) { crane.userData.working = false; crane.userData.idle = true; }
      g.add(crane);
      return crane;
    };
    const order = [];
    // A bay as long as a berth takes several cranes on its rails, about one for every 80 m of it
    // (a ship is worked by three or four at once); the main berth's as many as its register lists.
    const mainAt = onQuay(quay, berthAt).s;
    bays.forEach((b) => {
      const len = b.to - b.from;
      const isMain = mainAt >= b.from && mainAt <= b.to;
      const n = Math.max(1, Math.min(isMain && equipment.length ? equipment.length : 4, Math.floor(len / (isMain ? 55 : 80))));
      for (let k = 0; k < n; k++) {
        const along = b.from + ((k + 0.5) * len) / n;
        // (the main berth's come first once sorted, so the i-th takes the register's i-th state)
        const st = (i) => (isMain ? stateOf(i) : 'working');
        order.push({ along, make: (i) => (kind === 'bulk' ? unloader(st(i)) : stsCrane(st(i))), inland: 6 });
      }
    });
    // Mobile cranes along the stretches no bay covers, one every 300 m or so.
    let mobile = 0;
    const gaps = [];
    let at = 0;
    for (const b of bays) { gaps.push([at, b.from]); at = b.to; }
    gaps.push([at, quay.length]);
    for (const [a, b] of gaps) {
      // (a berth without stoppers away from the main one gets its own, for what it is used for)
      for (let x = a + 150; x <= b - 60 && mobile < 12; x += 300) { if (freeBerth(x)) continue; order.push({ along: x, make: () => harbourCrane('working'), inland: 16 }); mobile++; }
    }
    // Those by the berth first, so the cameras and the live port take a working one.
    const dist = (o) => { const p = quayPoint(quay, o.along); return Math.hypot(p.x - berthAt[0], p.z - berthAt[1]); };
    order.sort((x, y) => dist(x) - dist(y));
    order.slice(0, 40).forEach((o, i) => cranes.push(place(o.make(i), o.along, o.inland)));
  }

  if (kind === 'container' || kind === 'multipurpose') {
    const count = bays.length ? 0 : kind === 'container' ? Math.max(3, equipment.length) : 1;
    for (let i = 0; i < count; i++) {
      const c = stsCrane(kind === 'container' ? stateOf(i) : 'working');
      c.position.set(centre + (i - (count - 1) / 2) * 42, top, front + 4);
      g.add(c);
      cranes.push(c);
    }
    // Two rows of blocks behind the berth: the front ones worked for the ship by tractors from
    // the quay cranes, the back ones for the gate by road trucks. Each block's truck lane is on
    // the side its traffic comes from.
    const blocks = [];
    for (let b = 0; b < (kind === 'container' ? 6 : 2); b++) {
      const back = Math.floor(b / 3) > 0;
      blocks.push({ x: yardFrom + 10 + (b % 3) * (yardLength / 3), y: top, z: front + 60 + Math.floor(b / 3) * 70, bays: Math.max(4, Math.floor(yardLength / 3 / 12.6) - 1), rows: 6, tiers: 4,
        lane: back ? 5 * 2.6 + 6 : -6, back });
    }
    const stacks = yardStacks(blocks, rng, BOX_COLOURS);
    g.add(stacks);
    yards.push({ mesh: stacks, main: true });
    mainBlocks.push(...blocks);
    for (const b of blocks) {
      b.crane = yardCrane(b, stacks.userData.yard, RTG_MATS, g);
      b.crane.main = true;
      yardCranes.push(b.crane);
    }
    for (const b of blocks.filter((x) => x.back)) gateTruck(b, (x, z) => [x, z], b.z + b.lane, front + yardDepth - 20, 1, { main: true });
  }
  if (kind === 'general_cargo' || kind === 'multipurpose') {
    for (let i = 0; i < (bays.length ? 0 : 2); i++) {
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
    for (let i = 0; i < (bays.length ? 0 : 2); i++) {
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
    // Each crane working the main berth has two tractors (trucks at a cargo berth) of its own,
    // each running between the crane and a stack (or a shed) and back.
    const mainCranes = cranes.filter((c) => !c.userData.idle);
    const kindOf = kind === 'container' || kind === 'multipurpose' ? 'tractor' : 'truck';
    const front3 = mainBlocks.filter((b) => !b.back);
    for (const c of mainCranes.length ? mainCranes : [{ position: new THREE.Vector3(centre, top, front) }]) {
      for (let k = 0; k < 2; k++) {
        const cx = c.position.x + (k ? 4 : -4);
        const v = vehicle(kindOf, [0xeeeeee, 0x1565c0, 0xc62828, 0xf9a825, 0x2e7d32, 0x37474f][Math.floor(rng() * 6)]);
        g.add(v);
        const mv = { object: v, offset: rng(), wait: 20 + rng() * 15, speed: 6, main: true, needs: 'cargo', load: v.userData.load };
        if (front3.length) {
          // Into the truck lane under a yard crane, along it to a bay, so the box lines up with the stack.
          const bl = front3[Math.floor(rng() * front3.length)];
          Object.assign(mv, toBlock(bl, (x, z) => [x, z], [cx, front + 20], [cx, front + 34], front + 44, bl.z + bl.lane));
        } else {
          const sx = centre - 80 + rng() * 220;                         // a shed's door
          mv.trip = trip([[cx, front + 20], [cx, front + 34], [sx, front + 44], [sx, front + 66]]);
        }
        movers.push(mv);
      }
    }
  }
  // Road trucks on the access road at the back.
  loops.push({ curve: loop([[centre - 400, front + yardDepth - 10], [centre + 400, front + yardDepth - 10], [centre + 400, front + yardDepth - 2], [centre - 400, front + yardDepth - 2]], top + 0.1), kind: 'truck', n: 6, road: true });
  for (const l of loops) {
    for (let k = 0; k < l.n; k++) {
      const v = vehicle(l.kind, [0xeeeeee, 0x1565c0, 0xc62828, 0xf9a825, 0x2e7d32, 0x37474f][Math.floor(rng() * 6)]);
      g.add(v);
      movers.push({ object: v, curve: l.curve, offset: k / l.n + rng() * 0.05, speed: (l.kind === 'car' ? 7 : 6) / l.curve.getLength(), apron: !l.road, load: l.road ? null : v.userData.load });
    }
  }
  scene.add(g);
  // Along a traced quay every berth is a working one, with its own ships (the live port brings them
  // in and out), its cranes and what it stores behind it. A berth between crane stoppers has its
  // rail-mounted cranes; one without is used as the person sets it (containers or general cargo
  // with mobile cranes, RoRo, or both), and is dressed for that.
  const uses = (twin.asset.berth_uses) || {};
  const freeUse = bays.length ? 'general_cargo' : ({ roro: 'roro', general_cargo: 'general_cargo', multipurpose: 'mixed' }[kind] || 'container');
  const mainBerth = berths.find((b) => b.main) || { main: true };
  for (const b of berths) {
    b.loa = Math.round(Math.min(b.length - 30, 180 + rng() * 170));
    b.beam = Math.round(b.loa * 0.14);
    b.assignable = !b.sts && !b.main;
    b.use = b.sts ? (kind === 'bulk' ? 'bulk' : 'container') : b.main ? kind : (uses[b.n] || freeUse);
  }
  for (const c of cranes) {
    const b = berths.find((x) => !x.main && c.userData.along >= x.from && c.userData.along <= x.to);
    if (b) c.userData.berth = b;
  }
  for (const mv of movers) if (mv.apron || mv.main) mv.berth = mainBerth;
  for (const y of yards) if (y.main) y.berth = mainBerth;
  for (const b of berths) if (!b.main && b.length >= 120) dress(b, b.use);
  // Lay out one berth for its use; called again when the use changes.
  function dress(b, use) {
    if (b.dress) {
      g.remove(b.dress);
      for (let i = movers.length - 1; i >= 0; i--) {
        if (movers[i].berth !== b || !movers[i].dressed) continue;
        if (movers[i].object.parent === g) g.remove(movers[i].object);
        movers.splice(i, 1);
      }
      for (let i = cranes.length - 1; i >= 0; i--) if (cranes[i].userData.berth === b && cranes[i].userData.dressed) { g.remove(cranes[i]); cranes.splice(i, 1); }
      for (let i = yards.length - 1; i >= 0; i--) if (yards[i].berth === b) yards.splice(i, 1);
      for (let i = yardCranes.length - 1; i >= 0; i--) if (yardCranes[i].berth === b) yardCranes.splice(i, 1);     // in b.dress, gone with it
    }
    const blocksHere = [];
    b.use = use;
    const leg = b.leg;
    const d = new THREE.Group();
    // Local x along the leg from its start, local z inland (signed: the group's z may point to sea).
    const inland = Math.sign(leg.land[0] * -leg.dir[1] + leg.land[1] * leg.dir[0]) || 1;
    d.position.set(leg.a[0], top, leg.a[1]);
    d.rotation.y = Math.atan2(-leg.dir[1], leg.dir[0]);
    const x0 = b.from - leg.from;
    const x1 = b.to - leg.from;
    const w = x1 - x0;
    const at = (x, z) => [x, inland * z];
    const P = (x, z) => [leg.a[0] + leg.dir[0] * x + leg.land[0] * z, leg.a[1] + leg.dir[1] * x + leg.land[1] * z];
    const cars = use === 'roro' ? [x0 + 10, x1 - 10] : use === 'mixed' ? [x0 + w / 2 + 5, x1 - 10] : null;
    const cargo = use === 'general_cargo' ? [x0 + 10, x1 - 10] : use === 'mixed' ? [x0 + 10, x0 + w / 2 - 5] : null;
    if (use === 'container') {
      // As behind the main berth: front blocks for the ship's tractors, back blocks for the gate's
      // trucks, each lane on the side its traffic comes from (the rows run inland or seaward in
      // the group's frame, depending on which way the leg runs).
      const blocks = [];
      const per = w > 260 ? 2 : 1;
      const bays = Math.max(4, Math.floor((w / per - 30) / 12.6));
      const far = 5 * 2.6 + 6;
      for (let k = 0; k < per * 2; k++) {
        const back = Math.floor(k / per) > 0;
        const [, z] = at(0, 60 + Math.floor(k / per) * 70);
        const towardsLand = inland > 0 ? back : !back;
        blocks.push({ x: x0 + 15 + (k % per) * (w / per), y: 0, z: z - (inland < 0 ? 15 : 0), bays, rows: 6, tiers: 4, lane: towardsLand ? far : -6, back });
      }
      const stacks = yardStacks(blocks, rng, BOX_COLOURS);
      d.add(stacks);
      yards.push({ mesh: stacks, berth: b });
      blocksHere.push(...blocks.filter((bl) => !bl.back));
      for (const bl of blocks) {
        bl.crane = yardCrane(bl, stacks.userData.yard, RTG_MATS, d);
        bl.crane.berth = b;
        yardCranes.push(bl.crane);
        // The lane's distance inland, for the trucks' errands in the scene's plan.
        bl.laneIn = (bl.z + bl.lane) * inland;
        if (bl.back) gateTruck(bl, P, bl.laneIn, yardDepth - 20, 1, { berth: b, dressed: true });
      }
    } else if (use === 'bulk') {
      for (let k = 0; k < 2; k++) {
        const pile = new THREE.Mesh(new THREE.ConeGeometry(26, 16, 24), k ? REAL.coal : REAL.grain);
        pile.scale.set(1.5, 1, 1);
        pile.position.set(x0 + w * (0.3 + 0.4 * k), 8, inland * 120);
        pile.castShadow = pile.receiveShadow = true;
        d.add(pile);
      }
    }
    if (cargo) {
      // Sheds, and steel coils and timber on the apron in front of them.
      const sw = Math.min(90, (cargo[1] - cargo[0]) / 2 - 10);
      for (let k = 0; k < 2; k++) d.add(box(sw, 14, 36, REAL.shed, cargo[0] + sw / 2 + 5 + k * (sw + 10), 7, inland * 110));
      const coils = new THREE.InstancedMesh(new THREE.TorusGeometry(0.8, 0.45, 8, 16), REAL.steel, 24);
      const m = new THREE.Matrix4();
      for (let i = 0; i < 24; i++) { m.makeTranslation(cargo[0] + 10 + (i % 8) * 2.6, 1.2, inland * (55 + Math.floor(i / 8) * 2.8)); coils.setMatrixAt(i, m); }
      coils.castShadow = true;
      d.add(coils);
      for (let i = 0; i < 4; i++) d.add(box(12, 1.6, 2.4, REAL.grain, cargo[0] + 40 + i * 14, 0.8, inland * 62));
    }
    if (cars) {
      // The vehicle park: rows of cars waiting to be shipped or collected.
      const perRow = Math.max(4, Math.floor((cars[1] - cars[0]) / 5.2));
      const rows = 16;
      const park = new THREE.InstancedMesh(new THREE.BoxGeometry(4.4, 1.5, 1.9), new THREE.MeshStandardMaterial({ roughness: 0.35, metalness: 0.5 }), perRow * rows);
      const m = new THREE.Matrix4();
      const c = new THREE.Color();
      const carColours = [0xffffff, 0x111111, 0x8a8f94, 0xb71c1c, 0x1a3c8c, 0xc0c4c8, 0x2e4b2e];
      let i = 0;
      for (let row = 0; row < rows; row++) {
        for (let k = 0; k < perRow; k++) {
          m.makeTranslation(cars[0] + k * 5.2, rng() < 0.8 ? 0.75 : -100, inland * (60 + row * 4.4 + Math.floor(row / 2) * 3));
          park.setMatrixAt(i, m);
          park.setColorAt(i, c.setHex(carColours[Math.floor(rng() * carColours.length)]));
          i++;
        }
      }
      park.castShadow = park.receiveShadow = true;
      d.add(park);
    }
    // High masts along the berth, lit at night.
    const masts = [];
    for (let x = x0 + 30; x < x1 - 10; x += 60) {
      for (const z of use === 'container' ? [45, 105, 165] : [45, 165]) masts.push(at(x, z));
    }
    d.add(mastRow(masts));
    g.add(d);
    b.dress = d;
    // Mobile harbour cranes on a berth without stoppers, unless it only takes RoRo ships.
    if (!b.sts && use !== 'roro') {
      for (const off of w > 200 ? [-0.22, 0.22] : [0]) {
        const crane = harbourCrane('working');
        const p = quayPoint(quay, b.mid + off * w, 16);
        crane.position.set(p.x, top, p.z);
        crane.rotation.y = facing(p.leg.sea);
        Object.assign(crane.userData, { along: b.mid + off * w, berth: b, dressed: true, working: false });
        g.add(crane);
        cranes.push(crane);
      }
    }
    // Two tractors (trucks at a cargo berth) for each crane, each running between its crane and a
    // stack (or a shed's door) and back; cars one way between the ship's ramp and the park.
    if (use !== 'roro' && use !== 'bulk') {
      const here = cranes.filter((c) => c.userData.berth === b);
      const sheds = cargo ? [cargo[0] + 40, cargo[1] - 40] : null;
      for (const c of here.length ? here : [{ userData: { along: b.mid } }]) {
        const a = c.userData.along - leg.from;
        for (let k = 0; k < 2; k++) {
          const v = vehicle(use === 'container' ? 'tractor' : 'truck', [0xeeeeee, 0x1565c0, 0xc62828, 0xf9a825][(k + here.indexOf(c) * 2) % 4]);
          g.add(v);
          const ax = a + (k ? 4 : -4);
          const mv = { object: v, offset: rng(), wait: 20 + rng() * 15, speed: 6, berth: b, dressed: true, needs: 'cargo', load: v.userData.load };
          if (use === 'container' && blocksHere.length) {
            const bl = blocksHere[Math.floor(rng() * blocksHere.length)];
            Object.assign(mv, toBlock(bl, P, [ax, 22], [ax, 34], 44, bl.laneIn));
          } else {
            const sx = sheds[0] + rng() * (sheds[1] - sheds[0]);
            mv.trip = trip([P(ax, 22), P(ax, 34), P(sx, 44), P(sx, 86)]);
          }
          movers.push(mv);
        }
      }
    }
    if (cars) {
      // The ship lies with its stern ramp on the quay; its stern is towards the start of the leg
      // or the end, whichever way it faces (see shipPose).
      const { bow } = shipPose(b);
      const stern = b.mid - leg.from - bow * (b.loa / 2 - 18);
      for (let k = 0; k < 10; k++) {
        const v = vehicle('car', [0xffffff, 0x111111, 0x8a8f94, 0xb71c1c, 0x1a3c8c, 0xc0c4c8, 0x2e4b2e, 0xeeeeee][k % 8]);
        v.visible = false;
        g.add(v);
        const slot = cars[0] + 10 + rng() * (cars[1] - cars[0] - 20);
        const row = 58 + Math.floor(rng() * 8) * 9;
        movers.push({ object: v, trip: trip([P(stern, 24), P(stern + bow * 30, 40), P(slot, 50), P(slot, row)], 'oneway'), offset: k / 10, gap: 12, speed: 7,
          berth: b, dressed: true, needs: 'roro' });
      }
    }
  }
  return { group: g, movers, cranes, lights, kind, yardDepth, berths, quay, mainBerth, dress, yards, yardCranes };
}

// --- the scene -----------------------------------------------------------------------

// The ship loader (marinetwin-ui.js) over the view while it builds, as in Triton.
let voyage = null;
// With a Revit model the download (or the kept copy) is the first 60–80%, measured in bytes; the
// steps after it share the rest. exact shows f at once, without sailing up to it.
function progress(f, words, ahead = 0, exact = false) {
  if (!voyage && window.MarineVoyage) voyage = window.MarineVoyage(view, words);
  if (voyage) voyage.set(f, words, ahead, exact);
}

async function main() {
  progress(0, 'Loading the twin', 0.02);
  const twin = await (await fetch(view.dataset.twin, { credentials: 'same-origin' })).json();
  if (twin.model) progress(0, 'Opening the Revit model');
  else progress(0.15, 'Drawing the berth', 0.2);
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
  // Where the elements' own positions (metres from the site's origin, x and y) are in the scene
  // before it is turned: the model's meshes sit around the IFC's first placement, so the offset is
  // read from them (the middle of many, as an element's mesh centre is not its insertion point).
  const geoOff = { x: 0, z: 0 };
  {
    const dx = [];
    const dz = [];
    const box3 = new THREE.Box3();
    const c = new THREE.Vector3();
    const step = Math.max(1, Math.floor(clickable.length / 2000));
    for (let i = 0; i < clickable.length; i += step) {
      const e = clickable[i].userData.element;
      if (!e || !Number.isFinite(e.x) || !Number.isFinite(e.y)) continue;
      box3.setFromObject(clickable[i]).getCenter(c);
      dx.push(c.x - e.x);
      dz.push(c.z + e.y);
    }
    const middle = (a) => (a.length ? a.sort((p, q) => p - q)[Math.floor(a.length / 2)] : 0);
    geoOff.x = middle(dx);
    geoOff.z = middle(dz);
  }
  progress(twin.model ? 0.85 : 0.55, 'Building the terminal around it', twin.model ? 0.04 : 0.15);

  // Turn the model so its quay faces the sea (-z): the longest leg of the quay, traced from its
  // fenders, runs along x, and the berth is on it. Without fenders, the old way: fenders' centre
  // to the bollards'.
  const plan = (pick) => clickable.filter((m) => pick(m.userData.element.kind)).map((m) => {
    const c = new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3());
    return [c.x, c.z];
  });
  let quay = null;
  let mainLeg = null;
  if (twin.model) {
    const fenderPts = plan((k) => k === 'fender');
    const deckPts = plan((k) => k !== 'fender' && k !== 'crane_stopper');
    quay = quayLine(fenderPts.length >= 4 ? fenderPts : plan((k) => k === 'bollard'), deckPts.length > 3000 ? deckPts.filter((_, i) => i % Math.ceil(deckPts.length / 3000) === 0) : deckPts);
    if (quay) {
      const stopperPts = plan((k) => k === 'crane_stopper');     // before the turn, like the rest
      mainLeg = quay.legs.reduce((a, l) => (l.len > a.len ? l : a));
      const angle = Math.atan2(mainLeg.sea[0], -mainLeg.sea[1]);
      content.rotation.y = angle;
      content.updateMatrixWorld(true);
      turnQuay(quay, angle);
      quay.stoppers = stopperPts.map((p) => turned(p, angle));
    }
  }
  const centreOf = (kind) => {
    const pts = clickable.filter((m) => m.userData.element.kind === kind).map((m) => new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3()));
    if (!pts.length) return null;
    return pts.reduce((a, b) => a.add(b), new THREE.Vector3()).divideScalar(pts.length);
  };
  const fenders = quay ? null : centreOf('fender');
  const bollards = quay ? null : centreOf('bollard') || centreOf('crane_rail') || centreOf('slab');
  if (twin.model && fenders && bollards) {
    const v = fenders.clone().sub(bollards);
    if (Math.hypot(v.x, v.z) > 0.3) content.rotation.y = Math.atan2(v.x, -v.z) * -1;
    content.updateMatrixWorld(true);
  }
  const bbox = new THREE.Box3().setFromObject(content);
  if (bbox.isEmpty()) bbox.set(new THREE.Vector3(-10, -10, -10), new THREE.Vector3(10, 5, 10));
  let fenderBoxes = clickable.filter((m) => m.userData.element.kind === 'fender').map((m) => new THREE.Box3().setFromObject(m));
  const legX = mainLeg ? [Math.min(mainLeg.a[0], mainLeg.b[0]), Math.max(mainLeg.a[0], mainLeg.b[0])] : null;
  if (mainLeg) {
    // The berth's own fenders: those along the main leg.
    const z = (mainLeg.a[1] + mainLeg.b[1]) / 2;
    const near = fenderBoxes.filter((b) => { const c = b.getCenter(new THREE.Vector3()); return Math.abs(c.z - z) < 12 && c.x >= legX[0] - 5 && c.x <= legX[1] + 5; });
    if (near.length) fenderBoxes = near;
  }
  const slabTops = clickable.filter((m) => ['slab', 'beam'].includes(m.userData.element.kind)).map((m) => new THREE.Box3().setFromObject(m).max.y);
  const frame = {
    minX: legX ? legX[0] : bbox.min.x, maxX: legX ? legX[1] : bbox.max.x,
    front: fenderBoxes.length ? fenderBoxes.reduce((m, b) => Math.max(m, b.max.z), -Infinity) : bbox.min.z,
    fenderFace: fenderBoxes.length ? fenderBoxes.reduce((m, b) => Math.min(m, b.min.z), Infinity) : bbox.min.z - 1.5,
    top: slabTops.length ? slabTops.reduce((m, y) => Math.max(m, y), -Infinity) : bbox.max.y,
  };

  // Sky, sun and sea.
  const lat = twin.asset.latitude ?? 0;
  const lon = twin.asset.longitude ?? -new Date().getTimezoneOffset() / 4;
  const theta = THREE.MathUtils.degToRad(twin.asset.rotation || 0);
  // The scene and the map: a point in the scene as metres east and north of the site's location,
  // and back. The model is turned in the scene (content.rotation) and on the map (theta).
  const turn = content.rotation.y;
  const toEn = (x, z) => {
    const [lx, lz] = turned([x, z], -turn);
    const mx = lx - geoOff.x;
    const my = geoOff.z - lz;
    return [mx * Math.cos(theta) - my * Math.sin(theta), mx * Math.sin(theta) + my * Math.cos(theta)];
  };
  const toScene = (e, n) => {
    const mx = e * Math.cos(theta) + n * Math.sin(theta);
    const my = -e * Math.sin(theta) + n * Math.cos(theta);
    return turned([mx + geoOff.x, geoOff.z - my], turn);
  };
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
  const site = terminal(scene, frame, twin, rng, quay);
  tagSite(site, twin);
  const dressOnly = site.dress;
  site.dress = (b, use) => { dressOnly(b, use); tagSite(site, twin); };
  let vessel = null;
  if (LIVE || LIFE) {
    // The live and lifecycle players bring the ships in and out themselves.
  } else if (twin.alongside) {
    // At the main berth, no longer than it, so she does not overlap the ships at the next berths.
    const a = twin.alongside;
    const spot = berthSpot(site, frame, a.beam);
    vessel = ship(a.type, Math.min(a.loa, spot.room), a.beam, a.draught, rng, flagCode(a.name, a.flag));
    vessel.position.set(spot.x, 0, spot.z);
    vessel.rotation.y = spot.rot;
    vessel.traverse((m) => { if (m.isMesh) m.castShadow = true; });
    setFill(vessel.userData.stacks, 0.7);
    scene.add(vessel);
    vessel.userData.pick = () => ({ ...shipCardStill(a, 'Alongside, discharging', vessel, site.mainBerth), follow: vessel });
  } else if (twin.next_ship) {
    // The berth is empty: the next ship waits at anchor off the port, clear of the ships alongside.
    const a = twin.next_ship;
    const spot = berthSpot(site, frame, a.beam);
    const at = anchorSpot(spot, seaChecker(site.quay, frame));
    vessel = ship(a.type, Math.min(a.loa, spot.room), a.beam, a.draught, rng, flagCode(a.name, a.flag));
    if (at) vessel.position.set(at.x, 0, at.z);
    else vessel.visible = false;                 // no open water near enough to show her on
    vessel.rotation.y = spot.rot + 0.4;
    vessel.traverse((m) => { if (m.isMesh) m.castShadow = true; });
    scene.add(vessel);
    vessel.userData.pick = () => ({ ...shipCardStill(a, 'At anchor, waiting for the berth', vessel, site.mainBerth), follow: vessel });
  }
  // The other berths along the quay: most have a ship alongside, worked by their own cranes.
  if (!LIVE && !LIFE) {
    if (vessel && twin.alongside) Object.assign(site.mainBerth, { state: 'discharging', shipKind: vessel.userData.kind, fill: 0.7 });
    for (const b of site.berths.filter((x) => !x.main)) {
      if (rng() > 0.7 || b.loa < 120) continue;
      const m = ship(berthShipType(b.use, b.n), b.loa, b.beam, 12, rng, flagCode(`berth ${b.n}`));
      const { rot } = shipPose(b);
      const p = quayPoint(site.quay, b.mid, -(b.beam / 2 + 2));
      m.position.set(p.x, 0, p.z);
      m.rotation.y = rot;
      m.traverse((n) => { if (n.isMesh) n.castShadow = true; });
      scene.add(m);
      Object.assign(b, { ship: m, state: rng() < 0.5 ? 'discharging' : 'loading', shipKind: m.userData.kind, fill: 0.3 + rng() * 0.6 });
      setFill(m.userData.stacks, b.fill);
      m.userData.pick = () => ({
        kind: shipKindWord(berthShipType(b.use, b.n)), title: `Ship at ${berthName(b).toLowerCase()}`,
        rows: [['Berth', berthName(b)], ['Now', `Alongside, ${b.state}`], ['Flag', FLAG_NAMES[m.userData.flag]], ['Length overall', `${b.loa} m`], ['Beam', `${b.beam} m`], ['Cargo aboard', pct(fillOf(m, b))]],
        follow: m,
      });
      if (m.userData.kind !== 'roro') for (const c of site.cranes) if (c.userData.berth === b) { c.userData.idle = false; c.userData.working = true; }
    }
  }
  for (const y of site.yards) setFill(y.mesh, yardFill(y.berth));
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
  let eventStates = null;                // on the risks page: what the event shown did to each element
  const stateOf = (e) => (eventStates ? eventStates.get(e.ref) || eventStates.get(e.name) || 'neutral' : e.state);
  function paint() {
    content.traverse((m) => {
      if (!m.isMesh) return;
      const e = m.userData.element;
      if (byCondition) {
        if (e) {
          const state = stateOf(e);
          if (!conditionMats.has(state)) conditionMats.set(state, material(state));
          m.material = conditionMats.get(state);
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
    progress(twin.model ? 0.9 : 0.72, 'Reading the weather and tide there', twin.model ? 0.05 : 0.18);
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
  let power = true;
  let clock = null;                      // the live player's clock, when it runs one
  function setTime() {
    const when = clock ? new Date(clock) : new Date(Date.now() + offsetHours * 3600000);
    const { alt, az } = sunPosition(when, lat, lon);
    // Sun direction, geographic to the model's frame (x along the berth, -z to the sea side).
    const east = Math.cos(alt) * Math.sin(az);
    const north = Math.cos(alt) * Math.cos(az);
    const mx = east * Math.cos(theta) + north * Math.sin(theta);
    const my = -east * Math.sin(theta) + north * Math.cos(theta);
    // ...and turned with the model, as the scene turns it so its quay faces the sea.
    const [sx, sz] = turned([mx, -my], turn);
    const dir = new THREE.Vector3(sx, Math.sin(alt), sz).normalize();
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
    const lit = night && power;          // the yard is lit at night, unless the power is cut
    for (const l of lamps) l.intensity = lit ? 900 : 0;
    REAL.lamp.emissiveIntensity = lit ? 3 : 0;
    GLOW.visible = lit;
    SHIP_LAMP.emissiveIntensity = night ? 4 : 0;
    SHIP_HOUSE.emissiveIntensity = night ? 1 : 0;      // her accommodation lit from inside
    SHIP_GLOW.visible = night;
    for (const m of Object.values(NAV)) m.visible = night;
    REAL.glass.emissive.setHex(night ? 0x665533 : 0x000000);
    water.material.uniforms.waterColor.value.setHex(day > 0.3 ? 0x0f3b4f : 0x041018);
    const tide = tideAt(when);
    water.position.y = tide;
    if (vessel) vessel.position.y = tide;
    for (const b of site.berths) if (b.ship && !LIVE) b.ship.position.y = tide;
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
  // On a quay kilometres long, the berth where the ship lies, not the whole quay: zoom out for that.
  const radius = Math.max(Math.min(bbox.getSize(new THREE.Vector3()).length() / 2, 700), ((twin.alongside || {}).loa || 0) * 0.8, 120);
  camera.position.copy(focus).add(new THREE.Vector3(radius * 0.8, radius * 0.95, -radius * 1.25));
  controls.target.copy(focus);
  controls.maxDistance = 4000;
  camera.updateProjectionMatrix();

  // Picking: a click (not a drag) on anything with something to say (an element of the model, a
  // ship, a crane, a tractor, a stack) opens its card on the right of the view; an element is also
  // shown beside the view where the page has room for it.
  const ray = new THREE.Raycaster();
  let downAt = null;
  let picked = null;
  const card = document.createElement('aside');
  card.className = 'mt-card';
  card.hidden = true;
  card.setAttribute('aria-live', 'polite');
  view.appendChild(card);
  let cardOf = null;
  let cardTimer = null;
  function drawCard() {
    if (!cardOf) return;
    const c = cardOf();
    if (!c) { closeCard(); return; }
    const rows = (c.rows || []).filter(([, v]) => v !== null && v !== undefined && v !== '');
    const html = `<button type="button" class="close" aria-label="Close">×</button>
      <p class="mt-card-kind">${escapeHtml(c.kind || '')}</p><h3>${escapeHtml(c.title)}</h3>
      ${c.state ? `<p><span class="badge ${c.state}">${escapeHtml(c.stateWord || STATE_WORD[c.state] || c.state)}</span></p>` : ''}
      <dl>${rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`).join('')}</dl>
      ${c.list && c.list.length ? `<h4>${escapeHtml(c.listTitle || '')}</h4><ul>${c.list.map((x) => `<li><span class="state-${x.state}" aria-hidden="true">●</span> <strong>${escapeHtml(x.label)}</strong><br><span>${escapeHtml(x.text)}</span></li>`).join('')}</ul>` : ''}
      ${c.link ? `<p><a href="${c.link.href}">${escapeHtml(c.link.text)} →</a></p>` : ''}
      ${c.follow ? `<p class="mt-card-follow">${follow && follow.object === c.follow
        ? `<button type="button" data-follow="${follow.mode === 'bridge' ? 'orbit' : 'bridge'}">${follow.mode === 'bridge' ? 'Orbit her' : 'Bridge'}</button> <button type="button" data-follow="stop">Stop following</button>`
        : '<button type="button" data-follow="orbit">Follow</button> <button type="button" data-follow="bridge">Bridge</button>'}</p>` : ''}`;
    if (html === card.shown) return;          // unchanged: keep the buttons under the pointer
    card.shown = html;
    card.innerHTML = html;
    card.querySelector('.close').addEventListener('click', closeCard);
    for (const b of card.querySelectorAll('[data-follow]')) {
      b.addEventListener('click', () => (b.dataset.follow === 'stop' ? stopFollow() : startFollow(c.follow, b.dataset.follow, c.title)));
    }
  }
  function openCard(source) {
    cardOf = source;
    card.hidden = false;
    view.classList.add('has-card');
    drawCard();
    clearInterval(cardTimer);
    cardTimer = setInterval(drawCard, 600);         // what it is doing changes as the clock runs
  }
  function closeCard() {
    cardOf = null;
    card.hidden = true;
    view.classList.remove('has-card');
    clearInterval(cardTimer);
  }
  // Following a ship: the view goes with her as she moves (in from the sea, alongside, out again).
  // Orbit keeps the centre of the view on her, so the mouse still turns and zooms about her;
  // Bridge puts the camera on her bridge looking over the bow, and dragging looks about from
  // there. Esc, or Stop following, puts the camera back where it was.
  let follow = null;
  const followBar = document.createElement('div');
  followBar.className = 'mt-follow';
  followBar.hidden = true;
  view.appendChild(followBar);
  const fp = new THREE.Vector3();
  function drawFollowBar() {
    followBar.hidden = !follow;
    if (!follow) return;
    followBar.innerHTML = `<span>Following <strong>${escapeHtml(follow.name || 'the ship')}</strong></span>
      <span role="group" aria-label="View"><button type="button" data-mode="orbit" aria-pressed="${follow.mode === 'orbit'}">Orbit</button><button type="button" data-mode="bridge" aria-pressed="${follow.mode === 'bridge'}">Bridge</button></span>
      <button type="button" data-mode="stop">Stop following <kbd>Esc</kbd></button>`;
    for (const b of followBar.querySelectorAll('[data-mode]')) {
      b.addEventListener('click', () => (b.dataset.mode === 'stop' ? stopFollow() : startFollow(follow.object, b.dataset.mode, follow.name)));
    }
  }
  function startFollow(object, mode = 'orbit', name = '') {
    const saved = follow ? follow.saved : { position: camera.position.clone(), target: controls.target.clone() };
    const u = object.userData;
    object.getWorldPosition(fp);
    follow = { object, mode, name, saved, last: fp.clone(), yaw: object.rotation.y, lost: 0 };
    if (mode === 'bridge' && u.bridge) {
      const eye = object.localToWorld(u.bridge.clone());
      camera.position.copy(eye);
      controls.target.copy(object.localToWorld(u.bridge.clone().add(new THREE.Vector3(250, -14, 0)))).sub(eye).setLength(2).add(eye);
    } else {
      follow.mode = 'orbit';
      // From her seaward quarter, far enough back to see all of her.
      const loa = u.loa || 200;
      controls.target.copy(fp).setY(fp.y + (u.deck || 10));
      const off = new THREE.Vector3(-loa * 0.75, loa * 0.42, -loa * 0.7).applyAxisAngle(new THREE.Vector3(0, 1, 0), object.rotation.y);
      camera.position.copy(controls.target).add(off);
    }
    controls.update();
    drawFollowBar();
    view.dispatchEvent(new CustomEvent('mt-follow', { detail: { on: true, name, mode: follow.mode } }));
    if (cardOf) drawCard();
  }
  function stopFollow() {
    if (!follow) return;
    camera.position.copy(follow.saved.position);
    controls.target.copy(follow.saved.target);
    controls.update();
    follow = null;
    drawFollowBar();
    view.dispatchEvent(new CustomEvent('mt-follow', { detail: { on: false } }));
    if (cardOf) drawCard();
  }
  // Each frame, after the ships have moved: the camera moves with her.
  function followShip(dt) {
    if (!follow) return;
    const o = follow.object;
    if (!o.visible || !o.parent) {
      follow.lost += dt;                     // her call is over: back to the view before
      if (follow.lost > 1.5) stopFollow();
      return;
    }
    follow.lost = 0;
    o.getWorldPosition(fp);
    if (follow.mode === 'bridge') {
      // Keep the way the person is looking, turned as she turns. The centre of the view is kept a
      // couple of metres ahead of the eye, so dragging turns the head rather than walking about.
      const look = controls.target.clone().sub(camera.position).applyAxisAngle(new THREE.Vector3(0, 1, 0), o.rotation.y - follow.yaw);
      if (look.lengthSq() < 1e-6) look.set(1, 0, 0);
      look.setLength(2);
      camera.position.copy(o.localToWorld(o.userData.bridge.clone()));
      controls.target.copy(camera.position).add(look);
    } else {
      const d = fp.clone().sub(follow.last);
      camera.position.add(d);
      controls.target.add(d);
    }
    follow.last.copy(fp);
    follow.yaw = o.rotation.y;
  }
  window.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && follow) stopFollow(); });

  const elementCard = (e) => () => ({
    kind: (e.kind || 'element').replace(/_/g, ' '), title: e.name, state: stateOf(e),
    rows: [...(eventStates ? [['In this event', { critical: 'destroyed or failed: replace', warning: 'damaged: repair' }[stateOf(e)] || 'not damaged']] : []),
      ['Material', e.material], ['Zone', (e.zone || '').replace(/_/g, ' ')], ['Health', e.health ?? '—'],
      ['Design utilisation', e.design_ur == null ? '—' : Number(e.design_ur).toFixed(2)],
      ['Utilisation at end of life', e.ur_at_life == null ? '—' : Number(e.ur_at_life).toFixed(2)]],
    listTitle: 'Sensors', list: e.sensors.map((x) => ({ state: x.state, label: x.label, text: x.headline })),
    link: { href: e.href, text: 'Condition, maintenance and history' },
  });
  const notScenery = new Set([sky, water, stars]);
  renderer.domElement.addEventListener('pointerdown', (ev) => { downAt = [ev.clientX, ev.clientY]; });
  renderer.domElement.addEventListener('pointerup', (ev) => {
    if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 4) return;
    const rect = renderer.domElement.getBoundingClientRect();
    const at = new THREE.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
    ray.setFromCamera(at, camera);
    // The nearest thing hit that has a card, looking up from the mesh to whatever it belongs to.
    let found = null;
    for (const hit of ray.intersectObjects(scene.children.filter((o) => !notScenery.has(o) && o.visible), true)) {
      let o = hit.object;
      while (o && !o.userData.element && !o.userData.pick) o = o.parent;
      if (o && o.visible !== false) { found = { object: hit.object, owner: o }; break; }
    }
    if (picked) for (const m of clickable) if (m.userData.element === picked) m.material.emissive?.setHex(0x000000);
    picked = found && found.owner.userData.element ? found.owner.userData.element : null;
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
    if (LIFE) return;                    // the lifecycle player has its own card for the parts
    if (picked) openCard(elementCard(picked));
    else if (found) openCard(() => found.owner.userData.pick(found.object));
    else closeCard();
  });

  window.addEventListener('resize', () => {
    if (!view.clientWidth || !view.clientHeight) return;   // on a section tab not showing
    camera.aspect = view.clientWidth / view.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(view.clientWidth, view.clientHeight);
  });

  // The risks page: the event shown, its damage on the elements and the area it closes laid over the
  // deck as a red carpet of 10 m squares, with a banner saying what it is.
  // The live port shows the same when it plays an extreme event, once the event has struck.
  let showEvent = null;
  if ((RISK || LIVE) && view.dataset.eventUrl) {
    const closedMat = new THREE.MeshBasicMaterial({ color: 0xd03b3b, transparent: true, opacity: 0.3, depthWrite: false });
    const cellGeo = new THREE.BoxGeometry(1, 1, 1);
    let carpet = null;
    const banner = document.createElement('div');
    banner.className = 'mt-risk-banner';
    banner.hidden = true;
    view.appendChild(banner);
    const homeTarget = controls.target.clone();
    const homeCamera = camera.position.clone();
    let asked = 0;
    showEvent = async (key) => {
      const mine = ++asked;
      let ev = null;
      try {
        if (key) ev = await (await fetch(view.dataset.eventUrl.replace('KEY', encodeURIComponent(key)), { credentials: 'same-origin' })).json();
      } catch (err) { ev = null; }
      if (mine !== asked) return;              // another event was picked meanwhile
      if (carpet) { scene.remove(carpet); carpet.dispose(); carpet = null; }
      if (!ev) { eventStates = null; paint(); banner.hidden = true; return; }
      eventStates = new Map();
      for (const d of ev.damaged) { eventStates.set(d.ref, d.state); eventStates.set(d.name, d.state); }
      paint();
      // The deck's level: the top of the slabs and beams, or of everything when there are none.
      content.updateMatrixWorld(true);
      const box = new THREE.Box3();
      let deck = -Infinity;
      let top = -Infinity;
      const closed = new Set(ev.closed);
      const cells = new Map();
      const CELL = 10;
      content.traverse((m) => {
        const e = m.isMesh && m.userData.element;
        if (!e) return;
        box.setFromObject(m);
        if (box.isEmpty()) return;
        top = Math.max(top, box.max.y);
        if (e.kind === 'slab' || e.kind === 'beam') deck = Math.max(deck, box.max.y);
        if (!(ev.whole || closed.has(e.ref) || closed.has(e.name))) return;
        for (let x = Math.floor((box.min.x - 3) / CELL); x <= Math.floor((box.max.x + 3) / CELL); x++) {
          for (let z = Math.floor((box.min.z - 3) / CELL); z <= Math.floor((box.max.z + 3) / CELL); z++) cells.set(`${x},${z}`, [x, z]);
        }
      });
      if (!Number.isFinite(deck)) deck = Number.isFinite(top) ? top : frame.top;
      const centre = new THREE.Vector3();
      if (cells.size) {
        carpet = new THREE.InstancedMesh(cellGeo, closedMat, cells.size);
        const mat = new THREE.Matrix4();
        let i = 0;
        for (const [x, z] of cells.values()) {
          mat.makeScale(CELL, 0.05, CELL).setPosition((x + 0.5) * CELL, deck + 0.35, (z + 0.5) * CELL);
          carpet.setMatrixAt(i++, mat);
          centre.x += (x + 0.5) * CELL; centre.z += (z + 0.5) * CELL;
        }
        centre.divideScalar(cells.size).setY(deck);
        carpet.renderOrder = 2;
        scene.add(carpet);
      }
      if (LIVE) return;                      // the live player keeps its own camera and log
      // A closed berth is not worked: the cranes and tractors stand still while it is shown.
      moving = !ev.days;
      const moveBox = hud.querySelector('.marine-hud-move');
      if (moveBox) moveBox.checked = moving;
      // The camera goes to the area hit, or back to the whole berth when the whole quay is closed.
      if (cells.size && !ev.whole) {
        const span = Math.sqrt(cells.size) * CELL;
        const back = Math.max(120, span * 1.6);
        const dir = homeCamera.clone().sub(homeTarget).normalize();
        controls.target.copy(centre);
        camera.position.copy(centre).addScaledVector(dir, back);
      } else {
        controls.target.copy(homeTarget);
        camera.position.copy(homeCamera);
      }
      controls.update();
      const d = (n) => (n >= 60 ? `${Math.round(n / 30.4)} months` : n >= 1 ? `${Math.round(n)} days` : `${Math.round(n * 24)} h`);
      const replace = ev.damaged.filter((x) => x.state === 'critical').length;
      const repair = ev.damaged.length - replace;
      banner.innerHTML = `<strong>${escapeHtml(ev.name)}</strong><br>` +
        (ev.days ? `${ev.whole ? 'The whole quay' : `${ev.closed_m.toLocaleString()} m of the quay`} closed ${d(ev.days)}` +
          (ev.days_known !== ev.days ? ` (${d(ev.days_known)} knowing early)` : '') : 'Nothing closed: trade falls away') +
        (ev.damaged.length ? `<br>${replace ? `${replace} to replace` : ''}${replace && repair ? ', ' : ''}${repair ? `${repair} to repair` : ''}` : '');
      banner.hidden = false;
    };
    view.addEventListener('mt-event', (ev) => showEvent(ev.detail));
    if (RISK && view.dataset.event) showEvent(view.dataset.event);
  }

  // The sensors plan: a pin on its host element for every planned sensor, coloured for the year
  // picked under the view (its assumed reading, or its maintenance check when a visit is due).
  if (PLAN && view.dataset.plan) {
    // Pins big enough to see along the whole quay; the structure greyed so they stand out.
    const size = Math.min(Math.max(bbox.getSize(new THREE.Vector3()).length() / 700, 1), 5);
    const pinGeo = new THREE.SphereGeometry(1.1 * size, 14, 10);
    const stemGeo = new THREE.CylinderGeometry(0.12 * size, 0.12 * size, 2.2 * size, 6);
    eventStates = new Map();
    paint();
    const pinMats = {};
    const pinMat = (state) => (pinMats[state] ||= new THREE.MeshStandardMaterial({
      color: new THREE.Color(STATE_COLOUR[state || 'neutral']()), emissive: new THREE.Color(STATE_COLOUR[state || 'neutral']()), emissiveIntensity: 0.35 }));
    const pins = new THREE.Group();
    scene.add(pins);
    // Where each element is: the top of its meshes.
    content.updateMatrixWorld(true);
    const tops = new Map();
    const b = new THREE.Box3();
    content.traverse((m) => {
      const e = m.isMesh && m.userData.element;
      if (!e) return;
      b.setFromObject(m);
      if (b.isEmpty()) return;
      for (const k of [e.ref, e.name]) {
        const had = tops.get(k);
        tops.set(k, had ? had.union(b) : b.clone());
      }
    });
    let asked = 0;
    const showPlan = async (year) => {
      const mine = ++asked;
      let data;
      try { data = await (await fetch(`${view.dataset.plan}?year=${encodeURIComponent(year)}`, { credentials: 'same-origin' })).json(); } catch (err) { return; }
      if (mine !== asked) return;
      pins.clear();
      const stacked = new Map();
      for (const s of data.sensors) {
        const box = tops.get(s.ref) || tops.get(s.host);
        if (!box) continue;
        const n = stacked.get(s.ref) || 0;
        stacked.set(s.ref, n + 1);
        const c = box.getCenter(new THREE.Vector3());
        const pin = new THREE.Group();
        const head = new THREE.Mesh(pinGeo, pinMat(s.state));
        head.position.y = (2.4 + n * 2.4) * size;
        const stem = new THREE.Mesh(stemGeo, pinMat(s.state));
        stem.position.y = 1.1 * size;
        pin.add(head, stem);
        pin.position.set(c.x + (s.face === 'back' ? 0.8 : 0), box.max.y, c.z);
        pin.userData.pick = () => ({
          kind: 'sensor', title: `${s.tag} · ${s.name}`, state: s.state,
          rows: [['On', s.host || '—'], ['Year of service', String(data.year)],
            ['Assumed reading', s.value == null ? 'no reading series' : `${Number(s.value).toLocaleString()} ${s.unit}`],
            ['Maintenance check', s.check_note]],
        });
        pins.add(pin);
      }
      view.dataset.pins = String(pins.children.length);
    };
    view.addEventListener('mt-plan-year', (ev) => showPlan(ev.detail));
    showPlan(view.dataset.year || 4);
  }

  // The live port: the player takes over the clock, the ships, the cranes and the weather.
  let player = null;
  if (LIVE) {
    progress(twin.model ? 0.95 : 0.8, 'Loading the next two days at the berth', twin.model ? 0.03 : 0.1);
    const { startLive } = await import('./marinetwin-live.js');
    player = await startLive({
      THREE, view, scene, camera, controls, renderer, twin, frame, site, rng, focus, radius, water, sky, sunLight, hemi,
      ship, vehicle, box, REAL, BOX_COLOURS, berthShipType, shipPose, quayPoint, setFill, yardFill, berthSpot, atSea: seaChecker(site.quay, frame),
      flagCode, FLAG_NAMES, follow: startFollow, stopFollow, following: () => follow && follow.object,
      setClock(ms) { clock = ms; setTime(); },
      setPower(on) { if (on !== power) { power = on; setTime(); } },
      setTide(fn) { tideSource = fn; },
      setMoving(on) { moving = on; },
      showEvent,
    });
  }

  // The lifecycle: the design life month by month, the parts wearing and being mended on the model.
  if (LIFE) {
    progress(twin.model ? 0.95 : 0.9, 'Running the design life', twin.model ? 0.03 : 0.08);
    const { startLife } = await import('./marinetwin-life.js');
    player = await startLife({
      THREE, view, scene, camera, controls, renderer, twin, frame, site, rng, focus, radius, water, sky, sunLight, hemi,
      ship, box, REAL, clickable, content, flagCode,
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
  let around = null;                     // the real surroundings, once the map has given them
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
          // At the other berths: only while a ship is worked, cars for a car carrier, tractors otherwise.
          const b = m.dressed ? m.berth : null;
          if (b && (!b.state || (m.needs === 'roro') !== (b.shipKind === 'roro'))) continue;
          m.u = ((m.u ?? m.offset) + dt * pace * m.speed) % 1;
          const u = m.u;
          // A tractor runs full from the cranes to the stacks when the ship is discharging, and
          // full from the stacks to the cranes when it is loading.
          if (m.load) {
            const state = m.berth && m.berth.state;
            const yardward = u >= 0.4 && u < 0.75;
            m.load.visible = state === 'loading' ? !yardward : state === 'discharging' ? yardward : true;
          }
          m.curve.getPointAt(u, point);
          m.curve.getPointAt((u + 0.002) % 1, ahead);
          m.object.position.copy(point);
          m.object.lookAt(ahead.x, point.y, ahead.z);
          m.object.rotateY(-Math.PI / 2);
        } else if (m.trip) {
          // An errand: only while this berth's ship is being worked (cars for a car carrier,
          // tractors for any other), and parked otherwise.
          const b = m.berth;
          // (a road truck from the gate comes whether a ship is in or not)
          const busy = m.gate || (b && b.state && (m.needs === 'roro') === (b.shipKind === 'roro'));
          const tr = m.trip;
          if (tr.mode === 'oneway') m.object.visible = false;
          if (!busy) {
            if (m.job) { m.rtg.cancel(m.job); m.job = null; }
            m.hold = false;
            m.status = tr.mode === 'oneway' ? 'Waiting for a car carrier' : 'Parked by its crane: no ship being worked';
            if (!m.parked && tr.mode !== 'oneway') {            // waiting by its crane for the next ship
              tr.curve.getPointAt(0, point); tr.curve.getPointAt(0.02, ahead);
              m.object.position.copy(point); m.object.lookAt(ahead.x, point.y, ahead.z); m.object.rotateY(-Math.PI / 2);
              if (m.load) m.load.visible = false;
              m.parked = true;
            }
            continue;
          }
          m.parked = false;
          const travel = tr.len / m.speed;
          const loading = !!b && b.state === 'loading';
          let u;
          let back = false;
          if (tr.mode === 'oneway') {
            // A car off the ship to the park while discharging, from the park onto it while loading.
            const T = travel + m.gap;
            m.s = ((m.s ?? m.offset * T) + dt * pace) % T;
            if (m.s >= travel) continue;
            u = m.s / travel;
            if (loading) { u = 1 - u; back = true; }
            m.status = loading ? 'Driving from the park onto the ship' : 'Driving off the ship to the park';
            m.object.visible = true;
          } else {
            // Waits at the quay crane (a road truck: at the gate), drives to the stack, waits under
            // the yard crane (held there until it has taken its box off or put one on), and back.
            const far = m.far ?? m.wait;
            const T = 2 * travel + m.wait + far;
            const was = m.s;
            m.s = ((m.s ?? m.offset * T) + (m.hold ? 0 : dt * pace)) % T;
            const p = m.s;
            if (m.gate && was !== undefined && p < was) m.deliver = Math.random() < 0.5;   // the next truck: in full or empty
            // Brings a box to the stack: a tractor while its ship is discharged, a truck with an export.
            const bring = m.gate ? m.deliver : !loading;
            if (p < m.wait) u = 0;                                            // under the crane, or at the gate
            else if (p < m.wait + travel) u = (p - m.wait) / travel;          // to the stack
            else if (p < m.wait + far + travel) u = 1;                        // under the yard crane
            else { u = 1 - (p - m.wait - far - travel) / travel; back = true; } // back
            const out = p >= m.wait && p < m.wait + far + travel;
            let full = bring ? out : !out;
            if (u === 1 && m.rtg) {
              if (!m.job) m.job = m.rtg.serve(m, bring ? 'off' : 'on');
              m.hold = !m.job.done;
              full = bring ? !m.job.taken : m.job.given;
              if (m.job.done && !m.job.left) { m.job.left = true; m.s = Math.max(m.s, m.wait + far + travel - 1.5); }
            } else if (m.job) {
              m.job = null;
              m.hold = false;
            }
            if (m.gate) {
              m.status = p < m.wait ? (m.deliver ? 'At the gate with an export box' : 'At the gate, come to collect an import box')
                : u === 1 ? (m.deliver ? 'Under the yard crane, its box being lifted off' : 'Under the yard crane, a box being put on')
                : !back ? (m.deliver ? 'Bringing an export box to the stack' : 'Driving to the stack to collect a box')
                : (full ? 'Leaving for the gate with its box' : 'Leaving for the gate, empty');
            } else {
              m.status = p < m.wait ? (loading ? 'Under the ship crane, its box being lifted aboard' : 'Under the ship crane, taking a box off the ship')
                : !back && u < 1 ? (loading ? 'Back to the stack for the next box' : 'Taking the box to the stack')
                : u === 1 ? (loading ? (m.hold ? 'In the lane, waiting for the yard crane to put a box on' : 'At the stack, a box put on')
                  : (m.hold ? 'In the lane, waiting for the yard crane to lift its box off' : 'At the stack, its box lifted off'))
                : (loading ? 'Taking a box to the ship' : 'Back to the ship crane, empty');
            }
            if (m.load) m.load.visible = full;
            if (u === 0 || u === 1) { tr.curve.getPointAt(u, point); m.object.position.copy(point); continue; }
          }
          tr.curve.getPointAt(u, point);
          tr.curve.getPointAt(Math.max(0, Math.min(1, u + (back ? -0.004 : 0.004))), ahead);
          m.object.position.copy(point);
          if (ahead.distanceToSquared(point) > 1e-4) {
            m.object.lookAt(ahead.x, point.y, ahead.z);
            m.object.rotateY(-Math.PI / 2);
          }
        }
      }
      // The yard cranes work the boxes the tractors and trucks bring and fetch; the stacks follow
      // the berth's ship a few boxes at a time where the cranes are not working.
      for (const r of site.yardCranes) r.tick(dt * pace);
      for (const y of site.yards) if (y.mesh.userData.yard) y.mesh.userData.yard.tick(dt);
      for (const c of player ? [] : site.cranes) {     // the live player works the cranes itself
        const u = c.userData;
        // Only with a ship alongside its berth to work.
        const b = u.berth || site.mainBerth;
        if (!b || !b.state) { if (u.load) u.load.visible = false; continue; }
        if (u.trolley && u.working) {
          const s = (Math.sin(t * 0.35 + c.position.x) + 1) / 2;
          u.trolley.position.z = -28 + 40 * s;
          u.spreader.position.y = -10 - 22 * Math.abs(Math.sin(t * 0.7 + c.position.x));
        }
        if (u.top && u.working) u.top.rotation.y = 0.9 * Math.sin(t * 0.18 + c.position.x);
        if (u.load) u.load.visible = !!u.working && Math.cos(t * 0.18 + c.position.x) > 0;
      }
      if (vessel) vessel.rotation.x = 0.004 * Math.sin(t * 0.6) * (1 + hs);
      if (around) around.tick(dt * Math.min(pace, 30));
    }
    followShip(dt);
    controls.update();
    // The near plane moves out as the camera does, so the land and the sea a few metres below it
    // stay apart in the depth buffer when looking over a quay kilometres long.
    const near = Math.max(0.5, camera.position.distanceTo(controls.target) / 400);
    if (Math.abs(near - camera.near) > camera.near * 0.2) { camera.near = near; camera.updateProjectionMatrix(); }
    renderer.render(scene, camera);
  }
  renderer.setAnimationLoop(animate);
  if (voyage) await voyage.done('Ready');
  if (voyage) voyage.remove();
  // For scripts and the browser tests: the scene, its camera and what is on the quay.
  view.twin = { THREE, scene, camera, controls, site, frame };
  view.dataset.ready = String(clickable.length);
  view.dataset.cranes = String(site.cranes.length);

  // The real surroundings, from the map at the site's location: after the twin is up, as they
  // come from the internet and the twin does not need them.
  if (twin.surroundings) {
    const D = site.yardDepth + 15;
    const keepLand = [];
    const keepSea = [];                    // the water in front of the quay, where the ships berth
    if (site.quay) {
      const legs = site.quay.legs;
      const P = (p, v, k) => [p[0] + v[0] * k, p[1] + v[1] * k];
      legs.forEach((l, i) => {
        keepLand.push([P(l.a, l.land, -3), P(l.b, l.land, -3), P(l.b, l.land, D), P(l.a, l.land, D)]);
        const [a, b] = [P(l.a, l.dir, -60), P(l.b, l.dir, 60)];
        keepSea.push([P(a, l.land, -3), P(b, l.land, -3), P(b, l.land, -400), P(a, l.land, -400)]);
        if (i + 1 < legs.length) keepLand.push([l.b, P(l.b, l.land, D), P(l.b, legs[i + 1].land, D)]);
      });
    } else {
      keepLand.push([[frame.minX - 300, frame.fenderFace - 3], [frame.maxX + 300, frame.fenderFace - 3],
        [frame.maxX + 300, frame.front + D], [frame.minX - 300, frame.front + D]]);
      keepSea.push([[frame.minX - 300, frame.fenderFace - 3], [frame.maxX + 300, frame.fenderFace - 3],
        [frame.maxX + 300, frame.fenderFace - 400], [frame.minX - 300, frame.fenderFace - 400]]);
    }
    const inside = (poly, x, z) => {
      let inn = false;
      for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        const [xi, zi] = poly[i];
        const [xj, zj] = poly[j];
        if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inn = !inn;
      }
      return inn;
    };
    const grounds = [];
    scene.traverse((m) => { if (m.isMesh && m.userData.ground) grounds.push(m); });
    import('./marinetwin-surroundings.js')
      .then(({ addSurroundings }) => addSurroundings({
        THREE, scene, twin, toScene, toEn, top: frame.top, grounds, vehicle, view, keepLand, keepSea,
        keepOut: (x, z) => keepLand.some((poly) => inside(poly, x, z)),
        mainLeg: site.quay ? site.quay.legs.reduce((m, l) => (l.len > m.len ? l : m)) : { a: [frame.minX, frame.fenderFace], b: [frame.maxX, frame.fenderFace] },
        centre: { x: (frame.minX + frame.maxX) / 2, z: frame.front + 100 },
      }))
      .then((got) => { around = got; view.dataset.surroundings = got && got.found ? 'yes' : 'no'; })
      .catch((err) => { console.warn('Surroundings', err); view.dataset.surroundings = 'no'; });
  }
}

if (view) {
  main().catch((err) => {
    console.error(err);
    if (voyage) voyage.remove();
    note('The 3D view could not start: ' + (err.message || err));
  });
}
