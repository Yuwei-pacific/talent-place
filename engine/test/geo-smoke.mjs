// node test/geo-smoke.mjs
import { strict as assert } from 'node:assert';
import { geoVerdict, geoFilter } from '../lib/geo.js';

assert.equal(geoVerdict('Milan, Lombardy, Italy'), 'eu');
assert.equal(geoVerdict('Milano'), 'eu');
assert.equal(geoVerdict('Naples, Campania, Italy'), 'eu');
assert.equal(geoVerdict('College Station, TX'), 'non-eu');
assert.equal(geoVerdict('London'), 'non-eu');
assert.equal(geoVerdict(''), 'unknown');
assert.equal(geoVerdict('To verify'), 'unknown');
const cards = [
  { title: 'A', company: 'X', location: 'Milan, Italy', url: 'u1', snippet: '', source: 'linkedin', discoveryQuery: 'q' },
  { title: 'B', company: 'X', location: 'Taylor, TX', url: 'u2', snippet: '', source: 'linkedin', discoveryQuery: 'q' },
];
const { eu, droppedNonEu } = geoFilter(cards);
assert.equal(eu.length, 1);
assert.equal(droppedNonEu.length, 1);
console.log('geo-smoke: OK');
