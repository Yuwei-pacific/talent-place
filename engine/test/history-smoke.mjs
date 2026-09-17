// node test/history-smoke.mjs — history load + dup verdicts against canonical CSV
import { strict as assert } from 'node:assert';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { loadHistory, checkDup } from '../lib/history.js';

// Resolved relative to this file so the test is not machine-specific.
const HERE = dirname(fileURLToPath(import.meta.url));
const CSV = join(HERE, '..', '..', 'index', 'Strategic_Design_Company_Index.csv');

const h = loadHistory(CSV);
assert.ok(h.size >= 100, `expected >=100 companies, got ${h.size}`);

// ---------------------------------------------------------------------------
// Invariant: every URL stored in history must be a SINGLE URL.
//
// This is the regression guard for the bug where `loadHistory` split cells on
// '|' only, while the CSV mostly stores them with embedded newlines. That
// produced one blob per row ("...url1\n2. url2") which could never match an
// incoming single URL, so checkDup could never report a duplicate for the 24
// affected companies. The old assertion took the blob itself and compared it to
// itself, so it was structurally incapable of failing.
// ---------------------------------------------------------------------------
const malformed = [];
for (const [key, entry] of h) {
  for (const url of entry.urls) {
    const problems = [];
    if (/\s/.test(url)) problems.push('contains whitespace');
    if ((url.match(/https?:\/\//g) || []).length > 1) problems.push('contains >1 URL');
    if (url.includes('|')) problems.push('contains a pipe');
    if (!/^https?:\/\//.test(url)) problems.push('is not a URL');
    if (problems.length) malformed.push(`${key}: ${problems.join(', ')} — ${JSON.stringify(url).slice(0, 120)}`);
  }
}
assert.deepEqual(
  malformed,
  [],
  `every history URL must be a single well-formed URL; found ${malformed.length} malformed:\n${malformed.slice(0, 5).join('\n')}`,
);

// ---------------------------------------------------------------------------
// Invariant: a URL taken FROM history must round-trip through checkDup.
//
// This is the property the old test only pretended to check. It exercises every
// company rather than one hardcoded one, so a separator regression anywhere in
// the file fails the build.
// ---------------------------------------------------------------------------
const nonRoundTripping = [];
let checked = 0;
for (const [, entry] of h) {
  for (const url of entry.urls) {
    checked++;
    const verdict = checkDup(h, entry.company, 'anything', 'Milan', url);
    if (verdict.dup !== true) nonRoundTripping.push(`${entry.company}: ${url}`);
  }
}
assert.ok(checked > 100, `expected to round-trip >100 URLs, only saw ${checked}`);
assert.deepEqual(
  nonRoundTripping,
  [],
  `${nonRoundTripping.length}/${checked} URLs from history are not reported as duplicates by checkDup:\n${nonRoundTripping.slice(0, 5).join('\n')}`,
);

// ---------------------------------------------------------------------------
// Behavioural checks
// ---------------------------------------------------------------------------
// Known company, new role -> not dup, companyKnown
const v = checkDup(h, 'Accenture', 'Quantum Gardening Intern — Milan', 'Milan, Italy', 'https://example.com/jobs/xyz-999');
assert.equal(v.dup, false);
assert.equal(v.companyKnown, true);

// Unknown company
assert.deepEqual(checkDup(h, 'Nonexistent Corp XYZ', 'Intern', 'Milan', 'https://example.com/1'), {
  dup: false,
  companyKnown: false,
});

// Cross-portal key match: a known role re-spelled on another portal is a dup.
// Key shape is `x:<normCompany>|<normTitle>|<normCity>` — note the `x:` prefix
// rides on the first field, so the split index is shifted by one.
const accenture = h.get('accenture');
assert.ok(accenture && accenture.keys.size > 0, 'Accenture should have at least one role key');
const sampleKey = [...accenture.keys].find((k) => {
  const [, title] = k.split('|');
  return Boolean(title);
});
assert.ok(sampleKey, 'Accenture should have at least one key with a non-empty normalized title');
const [head, title, city] = sampleKey.split('|');
assert.ok(head.startsWith('x:') && title && city, `role key should decompose as x:<company>|<title>|<city>, got ${sampleKey}`);
assert.equal(
  checkDup(h, accenture.company, title, city, 'https://example.com/never-seen').dup,
  true,
  'a known company+title+city must dedup regardless of URL',
);

console.log(`history-smoke: OK (${h.size} companies, ${checked} URLs round-tripped)`);
