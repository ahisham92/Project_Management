// MarineTwin: the container yard at work.
//
// The stacks here hold real boxes, slot by slot: each column of a block (one bay, one row) is so
// many boxes high, and a box lifted off the top of a column is gone from it. The yard cranes
// (rubber-tyred gantries, RTGs) do the lifting. Each serves one block: a tractor from the quay
// cranes or a road truck from the gate stops in the truck lane under it and asks for a box to be
// taken off or put on; the crane gantries along the block to the tractor's bay, trolleys across,
// lowers its spreader, locks on, hoists, trolleys over the stack (or the lane) and sets the box
// down. With no tractor or truck waiting it parks where it is, its spreader up.
//
// What the berth is doing still sets how full the yard is overall (a ship discharged fills it, a
// ship loaded empties it): the yard follows that slowly, a few boxes at a time in the columns the
// cranes are not working, so the boxes the cranes move are the ones seen moving.
//
// Frame: a block's bays run along x (12.6 m apart, one 40-foot box each), its rows along z
// (2.6 m apart), tiers up from its y. A crane stands in the same frame as its block.

import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/BufferGeometryUtils.js';

export const BAY = 12.6;
export const ROW = 2.6;
export const TIER = 2.6;
const HIDDEN = new THREE.Matrix4().makeScale(0, 0, 0);
const TRUCK_TOP = 4.1;        // m, the top of a box on a tractor's or a truck's trailer
const GANTRY = 2.2;           // m/s along the block
const TROLLEY = 1.2;          // m/s across it
const HOIST = 0.9;            // m/s up and down
const LOCK = 2.5;             // s to land the spreader and turn its twistlocks

// --- the stacks --------------------------------------------------------------------------
// Every slot of every block is an instance of one mesh; an empty slot is drawn at zero size.
// Each block gets `cols[bay][row]`, its columns, and `lane`: where the truck lane under its crane
// runs (z, from its first row), on the side its tractors or trucks come from.
export function yardStacks(blocks, rng, colours) {
  let slots = 0;
  for (const b of blocks) slots += b.bays * b.rows * b.tiers;
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(12.0, 2.55, 2.4),
    new THREE.MeshStandardMaterial({ roughness: 0.7, metalness: 0.2 }), Math.max(1, slots));
  const colour = new THREE.Color();
  const columns = [];
  let base = 0;
  for (const b of blocks) {
    b.cols = [];
    for (let bay = 0; bay < b.bays; bay++) {
      const line = [];
      for (let row = 0; row < b.rows; row++) {
        const col = { block: b, bay, row, x: b.x + bay * BAY, z: b.z + row * ROW, y: b.y, h: 0, max: b.tiers, base, busy: false };
        for (let t = 0; t < b.tiers; t++) {
          mesh.setMatrixAt(base + t, HIDDEN);
          mesh.setColorAt(base + t, colour.setHex(colours[Math.floor(rng() * colours.length)]));
        }
        base += b.tiers;
        line.push(col);
        columns.push(col);
      }
      b.cols.push(line);
    }
  }
  mesh.count = Math.max(1, slots);
  mesh.castShadow = mesh.receiveShadow = true;
  const yard = new Yard(mesh, columns, slots, rng);
  mesh.userData.yard = yard;
  mesh.userData.total = slots;
  return mesh;
}

class Yard {
  constructor(mesh, columns, slots, rng) {
    Object.assign(this, { mesh, columns, slots, rng, shown: 0, target: null, wait: 0 });
    this.m = new THREE.Matrix4();
  }

  // A box on top of a column (of the given colour, or the slot's own), if there is room.
  put(col, colour) {
    if (col.h >= col.max) return false;
    const i = col.base + col.h;
    this.mesh.setMatrixAt(i, this.m.makeTranslation(col.x, col.y + TIER / 2 + col.h * TIER, col.z));
    if (colour) { this.mesh.setColorAt(i, colour); this.mesh.instanceColor.needsUpdate = true; }
    col.h++;
    this.shown++;
    this.mesh.instanceMatrix.needsUpdate = true;
    return true;
  }

  // The top box off a column; its colour goes into `colour`, for the box now on the spreader.
  take(col, colour) {
    if (col.h <= 0) return false;
    col.h--;
    const i = col.base + col.h;
    if (colour) this.mesh.getColorAt(i, colour);
    this.mesh.setMatrixAt(i, HIDDEN);
    this.shown--;
    this.mesh.instanceMatrix.needsUpdate = true;
    return true;
  }

  // How full the yard should be, as a share of its slots. The first time, it is filled at once,
  // unevenly, as a yard is; after that it follows in tick().
  setTarget(f) {
    const want = Math.round(this.slots * Math.max(0, Math.min(1, f)));
    const first = this.target === null;
    this.target = want;
    if (first) this.settle(Infinity);
  }

  // Up to n boxes on or off, in random columns the cranes are not working.
  settle(n) {
    const cols = this.columns;
    let tries = 0;
    while (n > 0 && this.shown !== this.target && tries++ < 20000) {
      const col = cols[Math.floor(this.rng() * cols.length)];
      if (col.busy) continue;
      if (this.shown < this.target ? this.put(col) : this.take(col)) n--;
    }
  }

  // A few times a second: a handful of boxes towards the yard's share for the berth's ship, all at
  // once if the clock has jumped (the timeline scrubbed). Small differences are left to the cranes.
  tick(dt) {
    if (this.target === null) return;
    this.wait -= dt;
    if (this.wait > 0) return;
    this.wait = 0.4;
    const off = Math.abs(this.target - this.shown);
    if (off <= Math.max(3, this.slots * 0.01)) return;
    this.settle(off > this.slots * 0.08 ? off : Math.ceil(off / 25));
  }
}

// How many boxes are in a yard's stacks (an InstancedMesh from yardStacks or any other stack).
export function boxesIn(mesh) {
  return mesh.userData.yard ? mesh.userData.yard.shown : mesh.count;
}

// --- the yard crane ------------------------------------------------------------------------
// The steel of an RTG (legs, sill beams, the two portal beams and the girders the trolley runs
// on, the engine house on one sill) as one geometry, shared by every crane of the same span.
const frames = new Map();
function rtgFrame(zA, zB) {
  const key = `${zA},${zB}`;
  if (frames.has(key)) return frames.get(key);
  const parts = [];
  const add = (w, h, d, x, y, z) => { const g = new THREE.BoxGeometry(w, h, d); g.translate(x, y, z); parts.push(g); };
  const mid = (zA + zB) / 2;
  const span = zB - zA;
  for (const z of [zA, zB]) {
    for (const x of [-4.5, 4.5]) add(1.1, 19, 1.1, x, 10.2, z);            // legs
    add(10.5, 1.0, 1.5, 0, 1.4, z);                                         // sill beam over the wheels
    for (const x of [-4.5, 4.5]) add(1.6, 1.2, 1.8, x, 0.6, z);             // wheel bogies
    add(10.5, 1.4, 1.4, 0, 19.6, z);                                        // portal beam
  }
  for (const x of [-4.5, 4.5]) add(1.3, 1.6, span + 1.4, x, 20.9, mid);    // trolley girders
  add(3.2, 2.6, 2.2, -7.2, 3.2, zB);                                        // engine house
  const geo = mergeGeometries(parts);
  frames.set(key, geo);
  return geo;
}

const TROLLEY_GEO = new THREE.BoxGeometry(10.5, 1.4, 4.2);
const CAB_GEO = new THREE.BoxGeometry(2.2, 2.2, 2.2).translate(-4, -2.2, 0);
const SPREADER_GEO = new THREE.BoxGeometry(12.2, 0.5, 2.5).translate(0, 0.25, 0);
// The hoist ropes, two pairs of unit length upwards from the spreader, stretched to the trolley.
const ROPES_GEO = mergeGeometries([-3.5, 3.5].flatMap((x) => [-0.8, 0.8].map((z) => new THREE.BoxGeometry(0.1, 1, 0.1).translate(x, 0.5, z))));
const BOX_GEO = new THREE.BoxGeometry(12.0, 2.55, 2.4);

// A yard crane over `block` (its stacks in `yard`), in the block's frame, which `parent` holds.
// mats: { frame, trolley, spreader, rope, cab }. Returns the crane; call tick(dt) each frame.
export function yardCrane(block, yard, mats, parent) {
  const rowsEnd = (block.rows - 1) * ROW;
  const zA = Math.min(-1.2, block.lane) - 3;
  const zB = Math.max(rowsEnd + 1.2, block.lane) + 3;
  const object = new THREE.Group();
  const frame = new THREE.Mesh(rtgFrame(zA, zB), mats.frame);
  frame.castShadow = true;
  object.add(frame);
  const trolley = new THREE.Group();
  const deck = new THREE.Mesh(TROLLEY_GEO, mats.trolley);
  deck.castShadow = true;
  trolley.add(deck, new THREE.Mesh(CAB_GEO, mats.cab));
  trolley.position.y = 22.3;
  object.add(trolley);
  const spreader = new THREE.Group();
  spreader.add(new THREE.Mesh(SPREADER_GEO, mats.spreader));
  const carried = new THREE.Mesh(BOX_GEO, new THREE.MeshStandardMaterial({ roughness: 0.7, metalness: 0.2 }));
  carried.position.y = -TIER / 2;
  carried.castShadow = true;
  carried.visible = false;
  spreader.add(carried);
  object.add(spreader);
  const ropes = new THREE.Mesh(ROPES_GEO, mats.rope);
  object.add(ropes);
  parent.add(object);

  const safe = TIER * (block.tiers + 1) + 1;            // spreader high enough to carry a box over a full stack
  const crane = {
    object, block, yard, queue: [], job: null, steps: [], phase: 'park', carrying: false, idle: 0,
    x: block.x + BAY * Math.floor(block.bays / 2), z: rowsEnd / 2, y: safe, status: 'Parked: no tractor or truck waiting',
    // A tractor or truck in the lane asks for a box: 'off' its trailer onto the stack, or 'on' to
    // it from the stack. The job says when the box has left it (taken), reached it (given), and
    // when the trailer is clear to drive away (done).
    serve(mover, kind) {
      const job = { mover, kind, taken: false, given: false, done: false, cancelled: false };
      crane.queue.push(job);
      return job;
    },
    // The tractor has gone (its ship sailed): forget its job, or finish it without it.
    cancel(job) {
      job.cancelled = true;
      const i = crane.queue.indexOf(job);
      if (i >= 0) crane.queue.splice(i, 1);
      if (crane.job === job && crane.carrying && job.kind === 'on') {
        // The box it lifted for that tractor goes back where it came from.
        const col = job.col;
        crane.steps = [{ x: col.x, z: col.z - block.z, y: () => TIER * (col.h + 1), act: 'release' }];
        crane.phase = 'up';
      }
    },
    tick,
  };
  const colour = new THREE.Color();
  const bayX = (x) => Math.max(0, Math.min(block.bays - 1, Math.round((x - block.x) / BAY)));

  // The column to put a box on (the fullest one with room, near the bay asked), or to take one off.
  function column(bay, putting) {
    for (const d of [0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6]) {
      const line = block.cols[bay + d];
      if (!line) continue;
      let best = null;
      for (const col of line) {
        if (col.busy) continue;
        if (putting ? col.h < col.max && (!best || col.h > best.h) : col.h > 0 && (!best || col.h > best.h)) best = col;
      }
      if (best) return best;
    }
    return null;
  }

  // The moves for a job: to the trailer and the column, in the order the box goes.
  function plan(job) {
    const truckX = job.mover.stopX ?? crane.x;
    const col = column(bayX(truckX), job.kind === 'off');
    if (!col) return false;
    col.busy = true;
    job.col = col;
    const atTruck = { x: truckX, z: block.lane, y: () => TRUCK_TOP, act: job.kind === 'off' ? 'grab' : 'release', truck: true };
    const atStack = { x: col.x, z: col.z - block.z, y: () => TIER * (job.kind === 'off' ? col.h + 1 : col.h), act: job.kind === 'off' ? 'release' : 'grab' };
    crane.steps = job.kind === 'off' ? [atTruck, atStack] : [atStack, atTruck];
    return true;
  }

  const toward = (v, to, step) => (Math.abs(to - v) <= step ? to : v + Math.sign(to - v) * step);

  function tick(dt) {
    if (!crane.job) {
      const job = crane.queue.shift();
      if (job && !job.cancelled && plan(job)) {
        crane.job = job;
        crane.phase = 'up';
      } else if (job) {
        job.done = true;                                // no box to give, no room for one: wave it on
      } else if (crane.phase !== 'park') {
        crane.idle += dt;
        crane.y = toward(crane.y, safe, HOIST * dt);
        if (crane.idle > 20) { crane.phase = 'park'; crane.status = 'Parked: no tractor or truck waiting'; }
      }
    }
    const job = crane.job;
    const step = crane.steps[0];
    if (job && step) {
      crane.idle = 0;
      const what = job.mover.gate ? 'road truck' : 'tractor';
      if (crane.phase === 'up') {
        crane.y = toward(crane.y, safe, HOIST * dt);
        crane.status = crane.carrying ? 'Hoisting the box' : 'Hoisting the spreader';
        if (crane.y >= safe) {
          if (job.truckDone) job.done = true;           // the trailer is clear to go
          crane.phase = 'move';
        }
      } else if (crane.phase === 'move') {
        crane.x = toward(crane.x, step.x, GANTRY * dt);
        crane.z = toward(crane.z, step.z, TROLLEY * dt);
        crane.status = step.truck ? `${crane.carrying ? 'Taking the box' : 'Going'} to the ${what} in the lane, bay ${bayX(step.x) + 1}`
          : `${crane.carrying ? 'Carrying the box' : 'Going'} to bay ${bayX(step.x) + 1}, row ${job.col.row + 1} of the stack`;
        if (crane.x === step.x && crane.z === step.z) crane.phase = 'down';
      } else if (crane.phase === 'down') {
        crane.y = toward(crane.y, step.y(), HOIST * 1.2 * dt);
        crane.status = step.act === 'grab' ? `Lowering the spreader onto the box ${step.truck ? `on the ${what}` : 'in the stack'}`
          : `Setting the box down ${step.truck ? `on the ${what}` : 'on the stack'}`;
        if (crane.y === step.y()) { crane.phase = 'lock'; crane.lock = LOCK; }
      } else if (crane.phase === 'lock') {
        crane.lock -= dt;
        if (crane.lock <= 0) {
          if (step.act === 'grab') {
            if (step.truck) {
              job.taken = true;
              const load = job.mover.load;
              if (load) colour.copy(load.material.color);
            } else {
              yard.take(job.col, colour);
            }
            crane.carrying = true;
            carried.material.color.copy(colour);
          } else {
            crane.carrying = false;
            if (step.truck) {
              if (job.cancelled) yard.put(job.col, colour);          // the tractor has gone: back on the stack
              else { job.given = true; if (job.mover.load) job.mover.load.material.color.copy(colour); }
            } else {
              yard.put(job.col, colour);
            }
          }
          if (step.truck) job.truckDone = true;
          crane.steps.shift();
          crane.phase = 'up';
          if (!crane.steps.length) {
            // Hoist clear, then the next job.
            if (!job.done) job.done = true;
            job.col.busy = false;
            crane.job = null;
            crane.phase = 'up-idle';
            crane.idle = 0;
          }
        }
      }
    }
    if (job && job.cancelled && !crane.carrying && crane.steps.length && crane.steps[0].act === 'grab' && crane.steps[0].truck) {
      // Its tractor left before the box was taken off it: nothing to do.
      job.col.busy = false;
      crane.job = null;
      crane.steps = [];
    }
    if (!crane.job && crane.phase === 'up-idle') {
      crane.status = 'Waiting for the next tractor or truck';
      crane.y = toward(crane.y, safe, HOIST * dt);
    }
    // Where it all is.
    object.position.x = crane.x;
    trolley.position.z = crane.z;
    spreader.position.set(0, crane.y, crane.z);
    ropes.position.set(0, crane.y + 0.5, crane.z);
    ropes.scale.y = Math.max(0.1, trolley.position.y - crane.y - 1.2);
    carried.visible = crane.carrying;
  }
  object.position.set(crane.x, block.y, block.z);
  tick(0);
  return crane;
}
