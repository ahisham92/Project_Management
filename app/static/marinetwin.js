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
  const shape = new THREE.Shape(outline.map(([x, z]) => new THREE.Vector2(x, -z)));
  const below = 8;
  const land = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: top - 0.3 + below, bevelEnabled: false }), REAL.land);
  land.rotation.x = -Math.PI / 2;
  land.position.y = -below;
  land.receiveShadow = true;
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

function terminal(scene, frame, twin, rng, quay) {
  const { minX, maxX, front, top } = frame;
  const kind = twin.asset.terminal || 'container';
  const centre = (minX + maxX) / 2;
  const length = Math.max(maxX - minX, 120);
  const g = new THREE.Group();
  const movers = [];
  const cranes = [];
  const lights = [];

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

  // Rail-mounted cranes: one in each bay between crane stoppers, on the deck of whichever leg it
  // is; the rest of the quay is worked by mobile harbour cranes. Only the cranes by the berth
  // where the ship lies work; the others wait.
  const bays = quay && quay.stoppers ? craneBays(quay, quay.stoppers) : [];
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
    bays.forEach((b, i) => order.push({ along: (b.from + b.to) / 2, make: () => (kind === 'bulk' ? unloader(stateOf(i)) : stsCrane(stateOf(i))), inland: 6 }));
    // Mobile cranes along the stretches no bay covers, one every 300 m or so.
    let mobile = 0;
    const gaps = [];
    let at = 0;
    for (const b of bays) { gaps.push([at, b.from]); at = b.to; }
    gaps.push([at, quay.length]);
    for (const [a, b] of gaps) {
      for (let x = a + 150; x <= b - 60 && mobile < 12; x += 300) { order.push({ along: x, make: () => harbourCrane('working'), inland: 16 }); mobile++; }
    }
    // Those by the berth first, so the cameras and the live port take a working one.
    const dist = (o) => { const p = quayPoint(quay, o.along); return Math.hypot(p.x - berthAt[0], p.z - berthAt[1]); };
    order.sort((x, y) => dist(x) - dist(y));
    for (const o of order.slice(0, 40)) cranes.push(place(o.make(), o.along, o.inland));
  }

  if (kind === 'container' || kind === 'multipurpose') {
    const count = bays.length ? 0 : kind === 'container' ? Math.max(3, equipment.length) : 1;
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
  // Along a traced quay, every berth is a working one: each stretch of about 300 m of a leg is a
  // berth with its own ships (the live port brings them in and out), and the yard behind every
  // leg has its stacks and its tractors.
  const berths = [];
  if (quay) {
    const mainAt = onQuay(quay, [centre, front]).s;
    for (const leg of quay.legs) {
      if (leg.len < 200) continue;
      const n = Math.max(1, Math.floor(leg.len / 300));
      for (let k = 0; k < n; k++) {
        const from = leg.from + (k * leg.len) / n;
        const to = leg.from + ((k + 1) * leg.len) / n;
        berths.push({ leg, from, to, mid: (from + to) / 2, length: to - from, main: mainAt >= from && mainAt <= to });
      }
    }
    for (const c of cranes) {
      const b = berths.find((x) => !x.main && c.userData.along >= x.from && c.userData.along <= x.to);
      if (b) c.userData.berth = b;
    }
    for (const leg of quay.legs) {
      if (leg.len < 150 || berths.some((b) => b.main && b.leg === leg)) continue;     // the main leg has its own
      const yardOf = new THREE.Group();
      // Local x along the leg, local z inland.
      const inland = Math.sign(leg.land[0] * -leg.dir[1] + leg.land[1] * leg.dir[0]) || 1;
      yardOf.position.set(leg.a[0], top, leg.a[1]);
      yardOf.rotation.y = Math.atan2(-leg.dir[1], leg.dir[0]);
      const blocks = [];
      const bays = Math.max(4, Math.floor(leg.len / 3 / 12.6) - 1);
      for (let b = 0; b < 6; b++) blocks.push({ x: 10 + (b % 3) * (leg.len / 3), y: 0, z: inland * (60 + Math.floor(b / 3) * 70) - (inland < 0 ? 15 : 0), bays, rows: 6, tiers: 4 });
      if (kind === 'container' || kind === 'multipurpose') yardOf.add(containerStacks(blocks, rng));
      g.add(yardOf);
      // Tractors between the quay and the stacks of this leg.
      const p = (t, z) => [leg.a[0] + leg.dir[0] * t + leg.land[0] * z, leg.a[1] + leg.dir[1] * t + leg.land[1] * z];
      const route = loop([p(20, 14), p(leg.len - 20, 14), p(leg.len - 10, 50), p(10, 50)], top + 0.1);
      for (let k = 0; k < 4; k++) {
        const v = vehicle(kind === 'roro' ? 'car' : kind === 'container' || kind === 'multipurpose' ? 'tractor' : 'truck', [0xeeeeee, 0x1565c0, 0xc62828, 0xf9a825][k]);
        g.add(v);
        movers.push({ object: v, curve: route, offset: k / 4, speed: 6 / route.getLength() });
      }
    }
  }
  return { group: g, movers, cranes, lights, kind, yardDepth, berths, quay };
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
  // The other berths along the quay: most have a ship alongside, worked by their own cranes.
  if (!LIVE && !LIFE) {
    for (const b of site.berths.filter((x) => !x.main)) {
      if (rng() > 0.7) continue;
      const loa = Math.min(b.length - 30, 180 + rng() * 170);
      if (loa < 120) continue;
      const beam = Math.round(loa * 0.14);
      const m = ship(site.kind === 'roro' ? 'ro-ro' : site.kind === 'bulk' ? 'bulk carrier' : 'container ship', loa, beam, 12, rng);
      const p = quayPoint(site.quay, b.mid, -(beam / 2 + 2));
      m.position.set(p.x, 0, p.z);
      m.rotation.y = Math.atan2(-p.leg.dir[1], p.leg.dir[0]);
      m.traverse((n) => { if (n.isMesh) n.castShadow = true; });
      scene.add(m);
      b.ship = m;
      for (const c of site.cranes) if (c.userData.berth === b) { c.userData.idle = false; c.userData.working = true; }
    }
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
    progress(twin.model ? 0.95 : 0.8, 'Loading the next two days at the berth', twin.model ? 0.03 : 0.1);
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
    progress(twin.model ? 0.95 : 0.9, 'Running the design life', twin.model ? 0.03 : 0.08);
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
    // The near plane moves out as the camera does, so the land and the sea a few metres below it
    // stay apart in the depth buffer when looking over a quay kilometres long.
    const near = Math.max(0.5, camera.position.distanceTo(controls.target) / 400);
    if (Math.abs(near - camera.near) > camera.near * 0.2) { camera.near = near; camera.updateProjectionMatrix(); }
    renderer.render(scene, camera);
  }
  renderer.setAnimationLoop(animate);
  if (voyage) await voyage.done('Ready');
  if (voyage) voyage.remove();
  view.dataset.ready = String(clickable.length);
  view.dataset.cranes = String(site.cranes.length);
}

if (view) {
  main().catch((err) => {
    console.error(err);
    if (voyage) voyage.remove();
    note('The 3D view could not start: ' + (err.message || err));
  });
}
