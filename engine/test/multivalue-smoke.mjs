// node test/multivalue-smoke.mjs — per-column multi-value cell splitting
//
// The canonical CSV stores multi-value cells with mixed separators (measured:
// Job Links 19 newline / 12 pipe; Sources / Portals 8 newline / 14 pipe /
// 8 semicolon). Two failure modes are pinned here:
//   1. Splitting on a character that legitimately occurs INSIDE one value.
//   2. Splitting a numbered cell on a "N. " that is part of the value itself.
// Both produce wrong dedup keys, which is worse than producing none.
import { strict as assert } from 'node:assert';
import { splitMulti, splitColumn, MULTI_VALUE_SPEC } from '../lib/normalize.js';

const spec = (name) => MULTI_VALUE_SPEC[name];

// --- the load-bearing case: ';' inside a single Work Modes value -------------
// io.py writes "Physical location shown; onsite/hybrid status to verify" as ONE
// value (50 rows carry this default). Treating ';' as a separator here would
// shred one value into two and silently corrupt the column.
assert.deepEqual(
  splitColumn('Physical location shown; onsite/hybrid status to verify', 'Work Modes'),
  ['Physical location shown; onsite/hybrid status to verify'],
  'Work Modes must NOT split on ";"',
);
assert.equal(spec('Work Modes').semicolon, false);

// --- ';' IS a separator for Sources / Portals -------------------------------
assert.deepEqual(splitColumn('LinkedIn Jobs; iAgora (mirror annuncio aziendale)', 'Sources / Portals'), [
  'LinkedIn Jobs',
  'iAgora (mirror annuncio aziendale)',
]);

// --- numbered cells, both real separator forms ------------------------------
assert.deepEqual(
  splitColumn('1. Leather Goods Design Internship — Milan, Italy | 2. Design Textile Accessories Internship — Milan, Italy', 'Matching Job Titles'),
  ['Leather Goods Design Internship — Milan, Italy', 'Design Textile Accessories Internship — Milan, Italy'],
);
assert.deepEqual(splitColumn('1. Alpha Intern\n2. Beta Intern', 'Matching Job Titles'), ['Alpha Intern', 'Beta Intern']);

// --- the ambiguity: a "N. " that belongs to the VALUE ------------------------
// A title containing " 2. " mid-sentence must survive as one item. Splitting
// there would mint two bogus dedup keys.
assert.deepEqual(
  splitColumn('1. Intern - Level 2. Design', 'Matching Job Titles'),
  ['Intern - Level 2. Design'],
  'a mid-sentence " 2. " must not split the item',
);
assert.deepEqual(splitColumn('1. Analyst, 3.5 days a week', 'Matching Job Titles'), ['Analyst, 3.5 days a week']);

// --- non-sequential numbering falls back to separator splitting --------------
// A "2. … | 3. …" cell is not a 1..N run, so the numbering is not trusted as a
// separator; the pipe fallback still yields the right items.
assert.deepEqual(splitColumn('2. Alpha | 3. Beta', 'Matching Job Titles'), ['Alpha', 'Beta']);

// --- the "alt." alternate-URL marker (1 row in the wild: Cefriel) -----------
// The alternate is a real dedup target and must become its own item, not ride
// along inside the primary URL.
assert.deepEqual(
  splitColumn(
    '1. https://www.cefriel.com/careers/stage-junior-business-innovation-consultant/?lang=en\n   alt. https://it.linkedin.com/jobs/view/stage-junior-consultant-at-cefriel-4440015924',
    'Job Links',
  ),
  [
    'https://www.cefriel.com/careers/stage-junior-business-innovation-consultant/?lang=en',
    'https://it.linkedin.com/jobs/view/stage-junior-consultant-at-cefriel-4440015924',
  ],
);
// Only URL columns carry the marker; a title mentioning "alt." is untouched.
assert.deepEqual(splitColumn('Alt. Text Intern', 'Matching Job Titles'), ['Alt. Text Intern']);

// --- query parameters are identifying and must survive splitting ------------
// A4: normalise the URL "senza rimuovere parametri identificativi dell'annuncio".
assert.deepEqual(splitColumn('1. https://x.example/job?id=13727121_it', 'Job Links'), [
  'https://x.example/job?id=13727121_it',
]);

// --- degenerate input ------------------------------------------------------
for (const empty of ['', '   ', null, undefined]) {
  assert.deepEqual(splitColumn(empty, 'Matching Job Titles'), []);
}
assert.deepEqual(splitColumn('1. Only One', 'Matching Job Titles'), ['Only One']);
assert.deepEqual(splitColumn('No numbering at all', 'Matching Job Titles'), ['No numbering at all']);
// Stray numbering prefix is stripped even on the fallback path.
assert.deepEqual(splitColumn('1. Alpha\n1. Beta', 'Matching Job Titles'), ['Alpha', 'Beta']);

// --- every column in the policy table is reachable and self-consistent ------
for (const [name, s] of Object.entries(MULTI_VALUE_SPEC)) {
  assert.equal(typeof s.semicolon, 'boolean', `${name}.semicolon`);
  assert.equal(typeof s.numbered, 'boolean', `${name}.numbered`);
  assert.deepEqual(splitColumn('', name), [], `${name} empty`);
}
assert.throws(() => splitColumn('x', 'Notes'), /no multi-value spec/, 'free-text columns have no spec');

console.log('multivalue-smoke: OK');
