// MarineTwin's 3D view: the asset's Revit model (IFC or glTF), or a schematic
// drawn from its elements when there is no model yet, coloured by condition.
//
// three.js is vendored under static/vendor/three. web-ifc, which reads IFC in
// the browser, is about 6 MB with its WebAssembly, so it is fetched only when
// an IFC model is opened, from the address in data-web-ifc.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';

const view = document.querySelector('.marine-view');
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

function material(state, opacity = 1) {
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(STATE_COLOUR[state || 'neutral']()),
    roughness: 0.65, metalness: 0.1, transparent: opacity < 1, opacity,
  });
}

function showElement(element) {
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
// Positions are the elements' own x (along the berth), y (across) and z (up), in metres.

function schematic(elements) {
  const group = new THREE.Group();
  const xs = elements.map((e) => e.x);
  const ys = elements.map((e) => e.y);
  const span = Math.max(...xs, 0) - Math.min(...xs, 0) + 8;
  const depth = Math.max(...ys, 0) - Math.min(...ys, 0) + 8;
  const midX = (Math.max(...xs, 0) + Math.min(...xs, 0)) / 2;
  const midY = (Math.max(...ys, 0) + Math.min(...ys, 0)) / 2;
  for (const e of elements) {
    let geometry;
    let at = new THREE.Vector3(e.x, e.z, -e.y);
    switch (e.kind) {
      case 'pile':
        geometry = new THREE.CylinderGeometry(0.6, 0.6, 24, 24);
        at = new THREE.Vector3(e.x, e.z - 9, -e.y);
        break;
      case 'combi_wall':
      case 'sheet_pile':
        geometry = new THREE.BoxGeometry(12, 26, 0.9);
        at = new THREE.Vector3(e.x, e.z - 10, -e.y);
        break;
      case 'slab':
        geometry = new THREE.BoxGeometry(span, 0.8, depth);
        at = new THREE.Vector3(midX, e.z, -midY);
        break;
      case 'beam':
        geometry = new THREE.BoxGeometry(8, 1.2, 1.2);
        break;
      case 'bollard':
        geometry = new THREE.CylinderGeometry(0.35, 0.45, 0.9, 16);
        break;
      case 'fender':
        geometry = new THREE.BoxGeometry(2, 2.5, 1);
        break;
      default:
        geometry = new THREE.BoxGeometry(1.5, 1.5, 1.5);
    }
    const mesh = new THREE.Mesh(geometry, material(e.state, e.kind === 'slab' ? 0.55 : 1));
    mesh.position.copy(at);
    mesh.userData.element = e;
    group.add(mesh);
  }
  return group;
}

function sea(box) {
  const size = box.getSize(new THREE.Vector3());
  const centre = box.getCenter(new THREE.Vector3());
  const width = Math.max(size.x, size.z, 20) * 2.2;
  const group = new THREE.Group();
  const water = new THREE.Mesh(
    new THREE.PlaneGeometry(width, width),
    new THREE.MeshStandardMaterial({ color: 0x2a78d6, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false }),
  );
  water.rotation.x = -Math.PI / 2;
  water.position.set(centre.x, 0, centre.z);
  water.userData.background = true;
  group.add(water);
  return group;
}

// --- the Revit model -----------------------------------------------------------------

async function loadIfc(url, base) {
  const WebIFC = await import(base + 'web-ifc-api.js');
  const api = new WebIFC.IfcAPI();
  api.SetWasmPath(base, true);
  await api.Init();
  const bytes = new Uint8Array(await (await fetch(url, { credentials: 'same-origin' })).arrayBuffer());
  const modelID = api.OpenModel(bytes, { COORDINATE_TO_ORIGIN: true });
  const group = new THREE.Group();
  const byExpress = new Map();
  api.StreamAllMeshes(modelID, (flat) => {
    const placed = flat.geometries;
    for (let i = 0; i < placed.size(); i++) {
      const pg = placed.get(i);
      const geometry = api.GetGeometry(modelID, pg.geometryExpressID);
      const verts = api.GetVertexArray(geometry.GetVertexData(), geometry.GetVertexDataSize());
      const index = api.GetIndexArray(geometry.GetIndexData(), geometry.GetIndexDataSize());
      const buffer = new THREE.BufferGeometry();
      const positions = new Float32Array(verts.length / 2);
      const normals = new Float32Array(verts.length / 2);
      for (let k = 0; k < verts.length; k += 6) {
        positions.set([verts[k], verts[k + 1], verts[k + 2]], k / 2);
        normals.set([verts[k + 3], verts[k + 4], verts[k + 5]], k / 2);
      }
      buffer.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      buffer.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
      buffer.setIndex(new THREE.BufferAttribute(index, 1));
      const mesh = new THREE.Mesh(buffer, material('neutral', 0.35));
      mesh.applyMatrix4(new THREE.Matrix4().fromArray(pg.flatTransformation));
      mesh.userData.expressID = flat.expressID;
      group.add(mesh);
      if (!byExpress.has(flat.expressID)) byExpress.set(flat.expressID, []);
      byExpress.get(flat.expressID).push(mesh);
      geometry.delete();
    }
  });
  // What each product is called: its GlobalId, Tag (Revit's element id) and Name.
  const names = new Map();
  for (const id of byExpress.keys()) {
    try {
      const line = api.GetLine(modelID, id);
      names.set(id, [line.GlobalId?.value, line.Tag?.value, line.Name?.value].filter(Boolean).map(String));
    } catch (err) { /* a product without properties is still drawn */ }
  }
  api.CloseModel(modelID);
  return {
    group,
    meshesFor(ref) {
      const want = String(ref).trim().toLowerCase();
      for (const [id, keys] of names) {
        if (keys.some((k) => k.toLowerCase() === want)) return byExpress.get(id);
      }
      for (const [id, keys] of names) {
        if (keys.some((k) => k.toLowerCase().includes(want))) return byExpress.get(id);
      }
      return [];
    },
  };
}

async function loadGltf(url) {
  const gltf = await new GLTFLoader().loadAsync(url);
  const group = gltf.scene;
  const nodes = [];
  group.traverse((node) => {
    if (node.isMesh) node.material = material('neutral', 0.35);
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
      const exact = nodes.find((n) => n.name && n.name.toLowerCase() === want);
      const loose = exact || nodes.find((n) => n.name && n.name.toLowerCase().includes(want));
      return loose ? meshesOf(loose) : [];
    },
  };
}

// --- the scene -----------------------------------------------------------------------

async function main() {
  const twin = await (await fetch(view.dataset.twin, { credentials: 'same-origin' })).json();
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, view.clientWidth / view.clientHeight, 0.1, 20000);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(view.clientWidth, view.clientHeight);
  view.prepend(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.4));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(60, 120, 80);
  scene.add(sun);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  let content;
  const unmatched = [];
  const clickable = [];
  if (twin.model) {
    note('Loading ' + (twin.model_kind === 'ifc' ? 'the IFC model' : 'the model') + '…');
    try {
      const model = twin.model_kind === 'ifc'
        ? await loadIfc(twin.model, view.dataset.webIfc)
        : await loadGltf(twin.model);
      for (const e of twin.elements) {
        const meshes = model.meshesFor(e.ref);
        if (!meshes.length) { unmatched.push(e.name); continue; }
        for (const mesh of meshes) {
          mesh.material = material(e.state);
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

  const box = new THREE.Box3().setFromObject(content);
  if (box.isEmpty()) box.set(new THREE.Vector3(-10, -10, -10), new THREE.Vector3(10, 10, 10));
  scene.add(sea(box));
  const centre = box.getCenter(new THREE.Vector3());
  const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 5);
  camera.position.copy(centre).add(new THREE.Vector3(radius * 0.9, radius * 0.7, radius * 1.4));
  camera.near = radius / 100;
  camera.far = radius * 50;
  camera.updateProjectionMatrix();
  controls.target.copy(centre);

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
    if (picked) for (const m of clickable) if (m.userData.element === picked) m.material.emissive?.setHex(0x333333);
    showElement(picked);
  });

  window.addEventListener('resize', () => {
    camera.aspect = view.clientWidth / view.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(view.clientWidth, view.clientHeight);
  });
  view.dataset.ready = String(clickable.length);
  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.render(scene, camera);
  });
}

if (view) {
  main().catch((err) => {
    console.error(err);
    note('The 3D view could not start: ' + (err.message || err));
  });
}
