// node test/labels-calibration.mjs — 20 fixed cases pinning decision -> A1 mapping
import { strict as assert } from 'node:assert';
import { decisionToA1, assertNoScoreWithoutDescription } from '../lib/labels.js';

const cases = [
  // [decision, hasDescription, score, expected]
  ['shortlist', true, 95, 'pertinente'],
  ['shortlist', true, null, 'pertinente'],
  ['shortlist', false, null, 'non_risolto'],
  ['shortlist', false, 80, 'non_risolto'], // label wins even if a score was passed
  ['review', true, 70, 'adiacente'],
  ['review', true, null, 'adiacente'],
  ['review', false, null, 'non_risolto'],
  ['exclude', true, null, 'fuori profilo'],
  ['exclude', false, null, 'fuori profilo'],
  ['exclude', true, 10, 'fuori profilo'],
  ['shortlist', true, 100, 'pertinente'],
  ['shortlist', true, 0, 'pertinente'],
  ['review', true, 100, 'adiacente'],
  ['review', true, 0, 'adiacente'],
  ['shortlist', true, 50, 'pertinente'],
  ['review', false, 60, 'non_risolto'],
  ['exclude', false, 90, 'fuori profilo'],
  ['review', true, 84, 'adiacente'],
  ['shortlist', true, 74, 'pertinente'],
  ['review', true, 66, 'adiacente'],
];
for (const [decision, hasDesc, score, expected] of cases) {
  assert.equal(decisionToA1(decision, hasDesc, score), expected, JSON.stringify([decision, hasDesc, score]));
}
// A4 invariant: score without description throws
assert.throws(() => assertNoScoreWithoutDescription(false, 80), /A4 violation/);
assert.doesNotThrow(() => assertNoScoreWithoutDescription(true, 80));
assert.doesNotThrow(() => assertNoScoreWithoutDescription(false, null));
// score range guard
assert.throws(() => decisionToA1('shortlist', true, 101), /out of range/);
console.log('labels-calibration: OK (20 cases)');
