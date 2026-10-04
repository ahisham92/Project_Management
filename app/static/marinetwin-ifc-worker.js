// Opens a Revit IFC for the 3D view, away from the page so the page never freezes.
//
// Asked with {bytes, base, refs, skip}: it reads the model with web-ifc (from `base`) one product at
// a time, saying which it is on (so the page can tell one that never finishes, and ask again with
// it in `skip`), and sends back the shapes. Without `bytes` it downloads `url` itself. An element
// MarineTwin tracks (its GlobalId, name or tag is in `refs`) comes back as a part of its own, so it
// can be coloured and clicked; everything else is merged into a few big parts, which draws thousands of objects as a handful.
// Positions are in metres, y up, around `origin` (a model on its map grid sits hundreds of
// kilometres out, too far for the graphics card's precision).

const REST_LIMIT = 1_500_000;          // vertices in one merged part

const say = (msg, transfer) => self.postMessage(msg, transfer || []);

async function download(url) {
  const answer = await fetch(url, { credentials: 'same-origin' });
  if (!answer.ok) throw new Error(`the model could not be downloaded (error ${answer.status})`);
  const total = Number(answer.headers.get('Content-Length')) || 0;
  if (!answer.body || !total) return new Uint8Array(await answer.arrayBuffer());
  const bytes = new Uint8Array(total);
  const reader = answer.body.getReader();
  let got = 0;
  let told = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (got + value.length > bytes.length) throw new Error('the model was bigger than the server said');
    bytes.set(value, got);
    got += value.length;
    if (got - told > total / 100 || got === total) {
      say({ type: 'progress', stage: 'download', loaded: got, total });
      told = got;
    }
  }
  return got === total ? bytes : bytes.subarray(0, got);
}

// The products with a shape, as web-ifc's StreamAllMeshes picks them: every element type in the
// file but openings and spaces.
function products(api, WebIFC, modelID) {
  const leave = new Set([WebIFC.IFCOPENINGELEMENT, WebIFC.IFCSPACE, WebIFC.IFCOPENINGSTANDARDCASE].filter((t) => typeof t === 'number'));
  const ids = [];
  for (const type of api.GetIfcEntityList(modelID)) {
    if (leave.has(type) || !api.IsIfcElement(type)) continue;
    const found = api.GetLineIDsWithType(modelID, type);
    for (let i = 0; i < found.size(); i++) ids.push(found.get(i));
  }
  return ids;
}

// Openings (pile holes, sleeves, voids) are cut into their slab or wall one boolean at a time,
// which is where web-ifc spends almost all its time on a big Revit model: a deck slab with 80
// holes takes about a second, without them a millisecond. The twin is drawn without the cuts:
// each "IFCRELVOIDSELEMENT(" in the file is renamed to a type web-ifc does not know, in place.
function dropOpenings(bytes) {
  const find = new TextEncoder().encode('IFCRELVOIDSELEMENT(');
  const put = new TextEncoder().encode('IFCRELVOIDSELEMENX(');
  let at = 0;
  let count = 0;
  for (;;) {
    at = bytes.indexOf(find[0], at);
    if (at < 0) return count;
    let same = true;
    for (let k = 1; k < find.length; k++) if (bytes[at + k] !== find[k]) { same = false; break; }
    if (same) { bytes.set(put, at); count++; at += find.length; } else at++;
  }
}

// One growing set of shapes: positions, normals and triangle indices.
class Bucket {
  constructor() { this.pos = []; this.nor = []; this.idx = []; this.count = 0; }
  add(verts, index, m, origin) {
    const base = this.count;
    const pos = new Float32Array(verts.length / 2);
    const nor = new Int8Array(verts.length / 2);
    for (let k = 0, j = 0; k < verts.length; k += 6, j += 3) {
      const x = verts[k], y = verts[k + 1], z = verts[k + 2];
      // In double precision first, then around the origin, so the float that is kept is small.
      pos[j] = m[0] * x + m[4] * y + m[8] * z + m[12] - origin[0];
      pos[j + 1] = m[1] * x + m[5] * y + m[9] * z + m[13] - origin[1];
      pos[j + 2] = m[2] * x + m[6] * y + m[10] * z + m[14] - origin[2];
      const nx = verts[k + 3], ny = verts[k + 4], nz = verts[k + 5];
      const tx = m[0] * nx + m[4] * ny + m[8] * nz;
      const ty = m[1] * nx + m[5] * ny + m[9] * nz;
      const tz = m[2] * nx + m[6] * ny + m[10] * nz;
      const len = Math.hypot(tx, ty, tz) || 1;
      nor[j] = Math.round((tx / len) * 127);
      nor[j + 1] = Math.round((ty / len) * 127);
      nor[j + 2] = Math.round((tz / len) * 127);
    }
    const idx = new Uint32Array(index.length);
    for (let i = 0; i < index.length; i++) idx[i] = index[i] + base;
    this.pos.push(pos); this.nor.push(nor); this.idx.push(idx);
    this.count += pos.length / 3;
  }
  take() {
    const join = (parts, Kind) => {
      const out = new Kind(parts.reduce((n, p) => n + p.length, 0));
      let at = 0;
      for (const p of parts) { out.set(p, at); at += p.length; }
      return out;
    };
    const out = { positions: join(this.pos, Float32Array), normals: join(this.nor, Int8Array), index: join(this.idx, Uint32Array) };
    this.pos = []; this.nor = []; this.idx = []; this.count = 0;
    return out;
  }
}

// Copied, not handed over: the reader keeps its own to pack for the server afterwards.
function send(part, kept) {
  say({ type: 'part', ...part });
  if (kept) kept.push(part);
}

// The shapes as one gzipped file: "MTM1", the header's length, a JSON header (origin, and each
// part's ids and sizes), then each part's positions (float32), indices (uint32) and normals
// (int8, padded to 4). marinetwin.js reads it back.
async function pack(parts, origin) {
  const header = new TextEncoder().encode(JSON.stringify({
    origin, parts: parts.map((p) => ({ global: p.global || null, name: p.name || null, tag: p.tag || null, nv: p.positions.length / 3, ni: p.index.length })),
  }));
  const pad = (n) => (4 - (n % 4)) % 4;
  let size = 8 + header.length + pad(header.length);
  for (const p of parts) size += p.positions.byteLength + p.index.byteLength + p.normals.byteLength + pad(p.normals.length);
  const out = new Uint8Array(size);
  out.set(new TextEncoder().encode('MTM1'), 0);
  new DataView(out.buffer).setUint32(4, header.length, true);
  out.set(header, 8);
  let at = 8 + header.length + pad(header.length);
  for (const p of parts) {
    for (const a of [p.positions, p.index, p.normals]) {
      out.set(new Uint8Array(a.buffer, a.byteOffset, a.byteLength), at);
      at += a.byteLength;
    }
    at += pad(p.normals.length);
  }
  return new Response(new Blob([out]).stream().pipeThrough(new CompressionStream('gzip'))).blob();
}

self.onmessage = async (ev) => {
  const { url, base, refs, keepAt } = ev.data;
  const skip = new Set(ev.data.skip || []);
  try {
    const wanted = new Set((refs || []).map((r) => String(r).trim().toLowerCase()));
    const started = import(base + 'web-ifc-api.js');
    const bytes = ev.data.bytes ? new Uint8Array(ev.data.bytes) : await download(url);
    const openings = dropOpenings(bytes);
    say({ type: 'progress', stage: 'open', openings });
    const WebIFC = await started;
    const api = new WebIFC.IfcAPI();
    api.SetWasmPath(base, true);
    await api.Init(undefined, true);
    const modelID = api.OpenModel(bytes, { COORDINATE_TO_ORIGIN: false, MEMORY_LIMIT: 3221225472 });
    if (modelID < 0) throw new Error('web-ifc could not open the file');
    const ids = products(api, WebIFC, modelID).filter((id) => !skip.has(id));
    const total = ids.length;
    say({ type: 'progress', stage: 'shapes', done: 0, total });

    let origin = null;
    let done = 0;
    const rest = new Bucket();
    let parts = 0;
    const kept = keepAt && typeof CompressionStream !== 'undefined' ? [] : null;
    const take = (flat, ids) => {
      const placed = flat.geometries;
      const tracked = [ids.global, ids.name, ids.tag].some((v) => v && wanted.has(String(v).trim().toLowerCase()));
      const bucket = tracked ? new Bucket() : rest;
      for (let i = 0; i < placed.size(); i++) {
        const pg = placed.get(i);
        const m = pg.flatTransformation;
        if (!origin) origin = [Math.round(m[12]), 0, Math.round(m[14])];   // heights stay as modelled
        const geometry = api.GetGeometry(modelID, pg.geometryExpressID);
        const verts = api.GetVertexArray(geometry.GetVertexData(), geometry.GetVertexDataSize());
        const index = api.GetIndexArray(geometry.GetIndexData(), geometry.GetIndexDataSize());
        bucket.add(verts, index, m, origin);
        geometry.delete();
      }
      if (tracked && bucket.count) { send({ ...bucket.take(), ...ids }, kept); parts++; }
      if (rest.count > REST_LIMIT) { send(rest.take(), kept); parts++; }
    };
    for (const id of ids) {
      let named = {};
      try {
        const line = api.GetLine(modelID, id);
        named = { global: line.GlobalId?.value, name: line.Name?.value, tag: line.Tag?.value };
      } catch (err) { /* a product without properties is still drawn */ }
      // Before the shape: if this one never finishes, the page knows which it was.
      say({ type: 'at', id, name: named.name || named.tag || named.global || `#${id}`, done, total });
      api.StreamMeshes(modelID, [id], (flat) => take(flat, named));
      done++;
    }
    if (rest.count) { send(rest.take(), kept); parts++; }
    api.CloseModel(modelID);
    say({ type: 'done', origin: origin || [0, 0, 0], parts, products: done });
    if (kept) {
      try {
        const blob = await pack(kept, origin || [0, 0, 0]);
        const answer = await fetch(keepAt, { method: 'POST', body: blob, credentials: 'same-origin', headers: { 'Content-Type': 'application/octet-stream' } });
        say({ type: 'kept', ok: answer.ok, bytes: blob.size });
      } catch (err) {
        say({ type: 'kept', ok: false, why: String(err && err.message || err) });
      }
    }
  } catch (err) {
    say({ type: 'error', message: String(err && err.message || err) });
  }
  self.close();
};
