// Pure behavior checks: no browser, credentials, external requests or paid calls.
import assert from 'node:assert/strict';
import { Player } from '../src/sequence/player.js';
import { TraceLoader } from '../src/sequence/loader.js';
import { Flight } from '../src/globe/camera.js';

const steps = [{ kind: 'evidence' }, { kind: 'candidate' }, { kind: 'refutation' }];
let shown = [], completed = 0;
const player = new Player({ steps, final: { answer: null } }, {
  onStep: (_, index) => shown.push(index), onDone: () => completed++,
});
player.update(.7);
assert.deepEqual(shown, [0, 1, 2]);
assert.equal(completed, 0);
player.update(1.179);
assert.equal(completed, 0);
player.update(.0011);
assert.equal(completed, 1);
player.update(20);player.finish();
assert.equal(completed, 1);
shown = [];
const instant = new Player({ steps, final: {} }, { onStep: (_, i) => shown.push(i) });
instant.finish();
assert.deepEqual(shown, [0, 1, 2]);
assert.equal(instant.done, true);
const cancelled = new Player({ steps }, { onStep: () => assert.fail('cancelled player advanced') });
cancelled.cancel();cancelled.finish();cancelled.update(2);
let emptyDone = 0;
new Player({ steps: [], final: {} }, { onDone: () => emptyDone++ }).update(.01);
assert.equal(emptyDone, 1);

await new TraceLoader(function () {
  assert.equal(this, undefined, 'platform fetch must not receive the TraceLoader as its receiver');
  return Promise.resolve({ ok: true, json: async () => ({ steps: [], final: {} }) });
}).load('platform.json');

const pending = new Map();
const loader = new TraceLoader((url, { signal }) => new Promise(resolve => pending.set(url, { resolve, signal })));
const a = loader.load('a.json'), b = loader.load('b.json');
assert.equal(pending.get('/traces/a.json').signal.aborted, true);
const trace = { steps, final: { answer: null } };
pending.get('/traces/b.json').resolve({ ok: true, json: async () => trace });
assert.deepEqual(await b, trace);
pending.get('/traces/a.json').resolve({ ok: true, json: async () => ({ steps: [], final: {} }) });
assert.equal(await a, null, 'obsolete response must never replace the selected photograph');
await assert.rejects(new TraceLoader(async () => ({ ok: false, status: 404 })).load('missing.json'), /404/);
await assert.rejects(new TraceLoader(async () => ({ ok: true, json: async () => ({ steps: 'broken', final: {} }) })).load('bad.json'), /Invalid/);
await assert.rejects(new TraceLoader(() => assert.fail('invalid filename reached fetch')).load('../private.json'), /Invalid/);
const originalTimer = globalThis.setTimeout;
try {
  let timeout;
  globalThis.setTimeout = callback => { timeout = callback; return undefined; };
  const timed = new TraceLoader((_, { signal }) => new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Timed out', 'AbortError')));
  })).load('slow.json');
  timeout();await assert.rejects(timed, { name: 'AbortError' });
} finally { globalThis.setTimeout = originalTimer; }

let arrivals = 0;
const globe = { metal: { rotation: { x: 0, y: 0 } }, camera: { position: { z: 4 } }, fit: 1, hold() {} };
const flight = new Flight(globe);
flight.to(31.5, 74.3, 'city', { instant: true, onDone: () => arrivals++ });
assert.equal(flight.active, null);assert.equal(globe.spinning, false);
assert.equal(globe.camera.position.z, 2.22);assert.equal(arrivals, 1);
assert(Number.isFinite(globe.metal.rotation.y));
console.log('Frontend behavior: timing, cancellation, reduced-motion completion, stale fetches, invalid/missing data, timeout and instant arrival pass.');
