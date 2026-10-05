// MarineTwin: the real surroundings of the site, from the map, around the modelled terminal.
//
// Where the site's location is set, the land around the terminal is laid with satellite imagery
// (Esri World Imagery, the same as the Map tab), cut away where the map has water (the coastline
// and the lakes, creeks and docks of OpenStreetMap), and the map's buildings, roads and railways
// are drawn on it at their real places, with traffic on the main roads. The terminal's own yard,
// drawn from the model, is kept clear. Move the site and the next visit fetches the new place.
//
// The map data comes from OpenStreetMap through Overpass, fetched by the browser and kept on the
// server (the key is the site's location), so later visits draw it at once. Nothing here is
// needed for the twin to work: offline, it simply keeps its plain land.

import { mergeGeometries } from 'three/addons/BufferGeometryUtils.js';

const RADIUS = 1600;                  // metres from the berth to each side, map data and imagery
const OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
  'https://overpass.private.coffee/api/interpreter'];
const IMAGERY = (z, x, y) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`;
const ROAD_WIDTH = {
  motorway: 22, trunk: 18, primary: 14, secondary: 11, tertiary: 9, unclassified: 7, residential: 6, living_street: 5,
  road: 7, service: 5, motorway_link: 8, trunk_link: 8, primary_link: 7, secondary_link: 7, tertiary_link: 6,
};
const BUSY = new Set(['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'trunk_link', 'primary_link']);

// --- where things are: metres east and north of the site's location, and Web Mercator pixels ---
const M_PER_DEG = 111320;
function enToLatLon(e, n, lat0, lon0) {
  return [lat0 + n / M_PER_DEG, lon0 + e / (M_PER_DEG * Math.max(Math.cos((lat0 * Math.PI) / 180), 1e-6))];
}
function latLonToEn(lat, lon, lat0, lon0) {
  return [(lon - lon0) * M_PER_DEG * Math.max(Math.cos((lat0 * Math.PI) / 180), 1e-6), (lat - lat0) * M_PER_DEG];
}
// The pixel at zoom z (256-pixel tiles) for a latitude and longitude.
function mercator(lat, lon, z) {
  const s = 256 * 2 ** z;
  const r = (Math.max(-85, Math.min(85, lat)) * Math.PI) / 180;
  return [((lon + 180) / 360) * s, ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * s];
}

// --- the map data ------------------------------------------------------------------------
function query(s, w, n, e) {
  const bb = `(${s.toFixed(6)},${w.toFixed(6)},${n.toFixed(6)},${e.toFixed(6)})`;
  const roads = Object.keys(ROAD_WIDTH).join('|');
  return `[out:json][timeout:90];(
way["building"]${bb};relation["building"]["type"="multipolygon"]${bb};
way["highway"~"^(${roads})$"]${bb};
way["railway"~"^(rail|light_rail|narrow_gauge)$"]${bb};
way["natural"="coastline"]${bb};
way["natural"="water"]${bb};relation["natural"="water"]${bb};way["waterway"="riverbank"]${bb};way["landuse"="basin"]${bb};
);out geom;`;
}

// Overpass's answer, cut down to what is drawn: points as [east, north] metres, to 0.1 m.
function digest(osm, lat0, lon0) {
  const en = (g) => g.map((p) => latLonToEn(p.lat, p.lon, lat0, lon0).map((v) => Math.round(v * 10) / 10));
  const rings = (el) => {
    if (el.type === 'way') return el.geometry ? [{ outer: true, pts: en(el.geometry) }] : [];
    return (el.members || []).filter((m) => m.type === 'way' && m.geometry && m.geometry.length > 2)
      .map((m) => ({ outer: m.role !== 'inner', pts: en(m.geometry) }));
  };
  const out = { buildings: [], roads: [], rail: [], water: [], coast: [] };
  for (const el of osm.elements || []) {
    const t = el.tags || {};
    if (t.building) {
      const levels = parseFloat(t['building:levels']);
      const h = parseFloat(t.height) || (levels ? levels * 3.2 + 1 : 0);
      for (const r of rings(el)) {
        if (r.outer && r.pts.length > 3) out.buildings.push({ k: t.building, h: Math.round(h * 10) / 10 || 0, c: t['roof:colour'] || t['building:colour'] || '', p: r.pts });
      }
    } else if (t.highway && el.geometry) {
      out.roads.push({ k: t.highway, b: t.bridge ? 1 : 0, p: en(el.geometry) });
    } else if (t.railway && el.geometry) {
      out.rail.push({ p: en(el.geometry) });
    } else if (t.natural === 'coastline' && el.geometry) {
      out.coast.push({ p: en(el.geometry) });
    } else if (t.natural === 'water' || t.waterway === 'riverbank' || t.landuse === 'basin') {
      for (const r of rings(el)) if (r.pts.length > 3) out.water.push({ o: r.outer ? 1 : 0, p: r.pts });
    }
  }
  // A dense town can hold tens of thousands of buildings: the biggest are kept, the sheds and
  // houses too small to see from the port left out, so the scene stays quick to draw.
  const area = (p) => Math.abs(p.reduce((s, a, k) => { const b = p[(k + 1) % p.length]; return s + a[0] * b[1] - b[0] * a[1]; }, 0)) / 2;
  out.buildings = out.buildings.map((b) => [area(b.p), b]).filter(([a]) => a >= 25).sort((x, y) => y[0] - x[0]).slice(0, 15000).map(([, b]) => b);
  return out;
}

async function fromOverpass(lat0, lon0, centre) {
  const [s, w] = enToLatLon(centre[0] - RADIUS, centre[1] - RADIUS, lat0, lon0);
  const [n, e] = enToLatLon(centre[0] + RADIUS, centre[1] + RADIUS, lat0, lon0);
  const body = 'data=' + encodeURIComponent(query(s, w, n, e));
  for (const url of OVERPASS) {
    try {
      const answer = await fetch(url, { method: 'POST', body, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
      if (answer.ok) return digest(await answer.json(), lat0, lon0);
    } catch (err) {
      console.warn('Overpass', url, err);
    }
  }
  return null;
}

async function mapData(twin, lat0, lon0, centre) {
  const s = twin.surroundings;
  if (s.kept) {
    try {
      const answer = await fetch(s.url, { credentials: 'same-origin' });
      if (answer.ok) return await answer.json();
    } catch (err) { /* fetched again below */ }
  }
  const got = await fromOverpass(lat0, lon0, centre);
  if (got) {
    // Kept for the next visit; a failure only means the next visit asks Overpass again.
    fetch(s.url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: s.key, ...got, source: 'OpenStreetMap via Overpass' }) }).catch(() => {});
  }
  return got;
}

// --- the ground: imagery, cut away where the map has water ------------------------------
async function imagery(lat0, lon0, centre) {
  const [s, w] = enToLatLon(centre[0] - RADIUS, centre[1] - RADIUS, lat0, lon0);
  const [n, e] = enToLatLon(centre[0] + RADIUS, centre[1] + RADIUS, lat0, lon0);
  let z = 17;
  let a;
  let b;
  for (; z > 12; z--) {
    a = mercator(n, w, z);
    b = mercator(s, e, z);
    if (b[0] - a[0] <= 4000 && b[1] - a[1] <= 4000) break;
  }
  const tx0 = Math.floor(a[0] / 256);
  const ty0 = Math.floor(a[1] / 256);
  const tx1 = Math.floor(b[0] / 256);
  const ty1 = Math.floor(b[1] / 256);
  const canvas = document.createElement('canvas');
  canvas.width = (tx1 - tx0 + 1) * 256;
  canvas.height = (ty1 - ty0 + 1) * 256;
  const g = canvas.getContext('2d');
  g.fillStyle = '#8c8a6c';
  g.fillRect(0, 0, canvas.width, canvas.height);
  let got = 0;
  const jobs = [];
  for (let x = tx0; x <= tx1; x++) {
    for (let y = ty0; y <= ty1; y++) {
      jobs.push(fetch(IMAGERY(z, x, y)).then((r) => (r.ok ? r.blob() : null)).then((blob) => (blob ? createImageBitmap(blob) : null))
        .then((img) => { if (img) { g.drawImage(img, (x - tx0) * 256, (y - ty0) * 256); got++; } }).catch(() => {}));
    }
  }
  await Promise.all(jobs);
  if (!got) return null;
  // A plain band round the edge, so the land past the imagery is plain land, not smeared pixels.
  g.strokeStyle = '#8c8a6c';
  g.lineWidth = 6;
  g.strokeRect(0, 0, canvas.width, canvas.height);
  return { canvas, z, ox: tx0 * 256, oy: ty0 * 256 };
}

// Land white, water black, in the imagery's pixels: the coastline drawn and the sea side of it
// flooded (the sea lies to the right of a coastline as it is drawn), lakes and docks filled.
function waterMask(data, toPx, width, height, keepLand, keepSea = []) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const g = canvas.getContext('2d');
  g.fillStyle = '#fff';
  g.fillRect(0, 0, width, height);
  const coast = data.coast || [];
  if (coast.length) {
    g.strokeStyle = '#808080';
    g.lineWidth = 3;
    for (const c of coast) {
      g.beginPath();
      c.p.forEach((p, i) => { const [x, y] = toPx(p); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      g.stroke();
    }
    const img = g.getImageData(0, 0, width, height);
    const px = img.data;
    const stack = [];
    for (const c of coast) {
      for (let i = 1; i < c.p.length; i++) {
        const [x0, y0] = toPx(c.p[i - 1]);
        const [x1, y1] = toPx(c.p[i]);
        const len = Math.hypot(x1 - x0, y1 - y0);
        if (len < 1) continue;
        // To the right of the line's direction, in pixels (y runs down the image).
        const [rx, ry] = [-(y1 - y0) / len, (x1 - x0) / len];
        for (const f of [0.25, 0.5, 0.75]) stack.push([Math.round(x0 + (x1 - x0) * f + rx * 6), Math.round(y0 + (y1 - y0) * f + ry * 6)]);
      }
    }
    while (stack.length) {
      const [x, y] = stack.pop();
      if (x < 0 || y < 0 || x >= width || y >= height) continue;
      let i = (y * width + x) * 4;
      if (px[i] !== 255) continue;
      // A span to the left and right, then the rows above and below it.
      let l = x;
      while (l > 0 && px[(y * width + l - 1) * 4] === 255) l--;
      let r = x;
      while (r < width - 1 && px[(y * width + r + 1) * 4] === 255) r++;
      for (let k = l; k <= r; k++) {
        i = (y * width + k) * 4;
        px[i] = px[i + 1] = px[i + 2] = 0;
        if (y > 0 && px[i - width * 4] === 255) stack.push([k, y - 1]);
        if (y < height - 1 && px[i + width * 4] === 255) stack.push([k, y + 1]);
      }
    }
    // The coastline itself is the water's edge.
    for (let i = 0; i < px.length; i += 4) if (px[i] === 128) px[i] = px[i + 1] = px[i + 2] = 0;
    g.putImageData(img, 0, 0);
  }
  const fill = (rings, colour) => {
    g.fillStyle = colour;
    for (const r of rings) {
      g.beginPath();
      r.p.forEach((p, i) => { const [x, y] = toPx(p); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      g.closePath();
      g.fill();
    }
  };
  fill((data.water || []).filter((w) => w.o), '#000');
  fill((data.water || []).filter((w) => !w.o), '#fff');
  // The modelled terminal is land, and the water in front of its quay is water, whatever the map says.
  fill(keepSea, '#000');
  fill(keepLand, '#fff');
  return canvas;
}

// --- buildings, roads and railways ------------------------------------------------------
const ROOFS = {
  warehouse: [0xd9ddd8, 0xc4ced4, 0xb9c4c9, 0x7f9fbf, 0xe2e2da, 0xa7744f],
  industrial: [0xd0d4cf, 0xbfc8cc, 0x9fb3c1, 0xe6e4dc, 0x8c8d86],
  other: [0xcdc3b3, 0xe0d8c8, 0xb5a48d, 0xd8cfc3, 0x9e968a, 0xc9b9a6],
};
const TALL = { warehouse: 12, industrial: 12, hangar: 14, silo: 28, storage_tank: 14, office: 14, commercial: 10, apartments: 15, retail: 7, house: 6, residential: 7, garage: 4, shed: 4, roof: 5 };

function colourOf(b, i) {
  if (b.c && /^#?[0-9a-f]{6}$/i.test(b.c)) return parseInt(b.c.replace('#', ''), 16);
  const named = { white: 0xeeeeea, grey: 0x9a9a96, gray: 0x9a9a96, red: 0xa0463c, blue: 0x5f84b0, green: 0x5f8a5f, brown: 0x7d5a43, black: 0x333333 };
  if (named[b.c]) return named[b.c];
  const list = ROOFS[b.k] || ROOFS[['shed', 'hangar', 'silo', 'storage_tank'].includes(b.k) ? 'industrial' : 'other'];
  return list[i % list.length];
}

export async function addSurroundings(o) {
  const { THREE, scene, twin, toScene, toEn, top, keepOut, keepLand, keepSea, grounds, vehicle, view } = o;
  const lat0 = twin.asset.latitude;
  const lon0 = twin.asset.longitude;
  const centre = toEn(o.centre.x, o.centre.z);
  const [data, sat] = await Promise.all([mapData(twin, lat0, lon0, centre).catch(() => null), imagery(lat0, lon0, centre).catch(() => null)]);
  const group = new THREE.Group();
  group.name = 'surroundings';
  const credits = [];

  // The ground: imagery, with the water cut away so the sea shows through.
  if (sat) {
    const toPx = ([e, n]) => {
      const [lat, lon] = enToLatLon(e, n, lat0, lon0);
      const [x, y] = mercator(lat, lon, sat.z);
      return [x - sat.ox, y - sat.oy];
    };
    const map = new THREE.CanvasTexture(sat.canvas);
    map.colorSpace = THREE.SRGBColorSpace;
    map.anisotropy = 8;
    const mat = new THREE.MeshStandardMaterial({ map, roughness: 0.95, metalness: 0 });
    const shore = data && ((data.coast || []).length || (data.water || []).length);
    if (data) {
      const land = keepLand.map((p) => ({ p: p.map(([x, z]) => toEn(x, z)) }));
      const sea = keepSea.map((p) => ({ p: p.map(([x, z]) => toEn(x, z)) }));
      mat.alphaMap = new THREE.CanvasTexture(waterMask(data, toPx, sat.canvas.width, sat.canvas.height, land, sea));
      mat.alphaTest = 0.5;
    }
    // Where the map has land beyond the land drawn behind the quay (a far shore, a headland, an
    // island), a sheet of it, just under the quay's own land; only when the map says where its
    // water is, or the sheet would cover the sea.
    if (shore) {
      const sheet = new THREE.PlaneGeometry(2 * RADIUS, 2 * RADIUS, 24, 24);
      sheet.rotateX(-Math.PI / 2);
      const pos = sheet.attributes.position;
      for (let i = 0; i < pos.count; i++) {
        const [x, z] = toScene(centre[0] + pos.getX(i), centre[1] - pos.getZ(i));
        pos.setXYZ(i, x, top - 0.45, z);
      }
      sheet.computeVertexNormals();
      const far = new THREE.Mesh(sheet, mat);
      far.receiveShadow = true;
      group.add(far);
      grounds.push(far);
    }
    for (const mesh of grounds) {
      const pos = mesh.geometry.attributes.position;
      const uv = new Float32Array(pos.count * 2);
      const v = new THREE.Vector3();
      mesh.updateMatrixWorld(true);
      for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld);
        const [x, y] = toPx(toEn(v.x, v.z));
        uv[i * 2] = x / sat.canvas.width;
        uv[i * 2 + 1] = 1 - y / sat.canvas.height;
      }
      mesh.geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
      mesh.material = mat;
    }
    credits.push('Imagery © Esri, Maxar, Earthstar Geographics');
  }

  const movers = [];
  if (data) {
    const at = ([e, n]) => toScene(e, n);
    const outside = (pts) => pts.filter((p) => { const [x, z] = at(p); return !keepOut(x, z); });
    // Buildings, walls and roofs coloured, all as one mesh.
    const parts = [];
    const colour = new THREE.Color();
    data.buildings.forEach((b, i) => {
      const pts = b.p.map(at);
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
      const cz = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      if (keepOut(cx, cz)) return;
      const area = Math.abs(pts.reduce((s, p, k) => { const q = pts[(k + 1) % pts.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0)) / 2;
      if (area < 12) return;
      const h = b.h || TALL[b.k] || (area > 2500 ? 12 : area > 400 ? 8 : 6);
      const shape = new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, -z)));
      const geo = new THREE.ExtrudeGeometry(shape, { depth: h, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      geo.translate(0, top - 0.3, 0);
      const n = geo.attributes.normal;
      const c = new Float32Array(n.count * 3);
      const roof = colour.setHex(colourOf(b, i)).clone();
      const wall = roof.clone().multiplyScalar(0.78);
      for (let k = 0; k < n.count; k++) {
        const use = n.getY(k) > 0.5 ? roof : wall;
        c[k * 3] = use.r; c[k * 3 + 1] = use.g; c[k * 3 + 2] = use.b;
      }
      geo.setAttribute('color', new THREE.BufferAttribute(c, 3));
      geo.deleteAttribute('uv');
      parts.push(geo);
    });
    if (parts.length) {
      const mesh = new THREE.Mesh(mergeGeometries(parts), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8, metalness: 0.15 }));
      mesh.castShadow = mesh.receiveShadow = true;
      mesh.userData.pick = () => ({ kind: 'Surroundings', title: 'Buildings around the port', rows: [['From', 'OpenStreetMap'], ['Buildings', parts.length.toLocaleString()]] });
      group.add(mesh);
    }
    // Roads and railways: ribbons just above the ground, cut where they enter the terminal.
    const ribbon = (pts, width, y) => {
      const v = [];
      const idx = [];
      for (let k = 0; k < pts.length; k++) {
        const a = pts[Math.max(0, k - 1)];
        const b = pts[Math.min(pts.length - 1, k + 1)];
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
        const [nx, nz] = [-(b[1] - a[1]) / len * width / 2, (b[0] - a[0]) / len * width / 2];
        v.push(pts[k][0] + nx, y, pts[k][1] + nz, pts[k][0] - nx, y, pts[k][1] - nz);
        if (k) { const i = k * 2; idx.push(i - 2, i, i - 1, i - 1, i, i + 1); }      // facing up
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
      geo.setIndex(idx);
      geo.setAttribute('normal', new THREE.Float32BufferAttribute(new Array(v.length).fill(0).map((_, k) => (k % 3 === 1 ? 1 : 0)), 3));
      return geo;
    };
    const runs = (p) => {
      // The stretches of a line outside the terminal.
      const out = [];
      let cur = [];
      for (const q of p.map(at)) {
        if (keepOut(q[0], q[1])) { if (cur.length > 1) out.push(cur); cur = []; } else cur.push(q);
      }
      if (cur.length > 1) out.push(cur);
      return out;
    };
    const roadGeo = [];
    const busy = [];
    for (const r of data.roads) {
      for (const run of runs(r.p)) {
        roadGeo.push(ribbon(run, ROAD_WIDTH[r.k] || 6, top - 0.22 + (ROAD_WIDTH[r.k] || 6) * 0.002 + (r.b ? 0.3 : 0)));
        if (BUSY.has(r.k)) busy.push(run);
      }
    }
    if (roadGeo.length) {
      const roads = new THREE.Mesh(mergeGeometries(roadGeo), new THREE.MeshStandardMaterial({ color: 0x3a3c3f, roughness: 0.92, polygonOffset: true, polygonOffsetFactor: -2 }));
      roads.receiveShadow = true;
      group.add(roads);
    }
    const railGeo = [];
    for (const r of data.rail) for (const run of runs(r.p)) railGeo.push(ribbon(run, 3.2, top - 0.2));
    if (railGeo.length) group.add(new THREE.Mesh(mergeGeometries(railGeo), new THREE.MeshStandardMaterial({ color: 0x5b4a3c, roughness: 1, polygonOffset: true, polygonOffsetFactor: -2 })));
    // Traffic on the main roads: trucks to and from the port, and cars, each way on its own side.
    busy.sort((a, b) => b.length - a.length);
    let made = 0;
    for (const run of busy.slice(0, 24)) {
      const curve = new THREE.CatmullRomCurve3(run.map(([x, z]) => new THREE.Vector3(x, top, z)), false, 'catmullrom', 0.1);
      const len = curve.getLength();
      if (len < 120) continue;
      for (let k = 0; k < Math.min(6, Math.floor(len / 150)) && made < 80; k++, made++) {
        const truck = k % 3 !== 2;
        const v = vehicle(truck ? 'truck' : 'car', [0xeeeeee, 0x1565c0, 0xc62828, 0xf9a825, 0x2e7d32, 0x37474f, 0x8a8f94][(made * 5) % 7]);
        group.add(v);
        movers.push({ object: v, curve, len, s: (k / 6 + Math.random() * 0.1) * len, dir: k % 2 ? -1 : 1, speed: truck ? 9 : 12 });
      }
    }
    credits.push('Map data © OpenStreetMap contributors');
  }
  scene.add(group);
  if (credits.length && view) {
    const line = document.createElement('p');
    line.className = 'mt-credits';
    line.textContent = credits.join(' · ');
    view.appendChild(line);
  }
  const p = new THREE.Vector3();
  const q = new THREE.Vector3();
  const side = new THREE.Vector3();
  return {
    group,
    found: !!(data || sat),
    // Moves the traffic on by dt seconds of the twin's own clock.
    tick(dt) {
      for (const m of movers) {
        m.s += dt * m.speed * m.dir;
        if (m.s > m.len) { m.s = m.len; m.dir = -1; }
        if (m.s < 0) { m.s = 0; m.dir = 1; }
        const u = m.s / m.len;
        m.curve.getPointAt(u, p);
        m.curve.getPointAt(Math.min(1, Math.max(0, u + 0.002 * m.dir)), q);
        // Keep to the right of the road's middle.
        side.set(-(q.z - p.z), 0, q.x - p.x).normalize().multiplyScalar(-2.2);
        m.object.position.copy(p).add(side);
        if (q.distanceToSquared(p) > 1e-6) { m.object.lookAt(q.x + side.x, p.y, q.z + side.z); m.object.rotateY(-Math.PI / 2); }
      }
    },
  };
}
