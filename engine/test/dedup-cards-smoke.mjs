// node test/dedup-cards-smoke.mjs
import { strict as assert } from 'node:assert';
import { dedupCards } from '../lib/dedup-cards.js';

const mk = (id, q, snippet = '') => ({
  title: 'T', company: 'C', location: 'Milan', url: `https://it.linkedin.com/jobs/view/t-${id}?trk=x`,
  snippet, sourceJobId: String(id), source: 'linkedin', discoveryQuery: q,
});
const { unique, dupCount } = dedupCards([mk(1, 'q1', 'short'), mk(1, 'q2', 'a longer snippet here'), mk(2, 'q1')]);
assert.equal(unique.length, 2);
assert.equal(dupCount, 1);
assert.equal(unique[0].snippet, 'a longer snippet here');
assert.ok(unique[0].discoveryQuery.includes('q1') && unique[0].discoveryQuery.includes('q2'));
console.log('dedup-cards-smoke: OK');
