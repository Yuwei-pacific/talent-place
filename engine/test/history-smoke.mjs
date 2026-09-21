// node test/history-smoke.mjs — history load + dup verdicts against canonical CSV
import { strict as assert } from 'node:assert';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readFileSync } from 'node:fs';
import { loadHistory, checkDup, stripSeatSuffix } from '../lib/history.js';
import { splitColumn } from '../lib/normalize.js';

// Resolved relative to this file so the test is not machine-specific.
const HERE = dirname(fileURLToPath(import.meta.url));
// Frozen sample, not the live history: the run dedups against the Master's
// Review.xlsx (via `sync_export.py export-history`), which no test can depend on
// and which has version history only in SharePoint. This file is the fixture
// the parser and the role key are tested against.
const CSV = join(HERE, 'fixtures', 'strategic-design-history.csv');

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

// ---------------------------------------------------------------------------
// Invariant: the seat suffix in `Matching Job Titles` must not break the key.
//
// History rows store "<Title> — <Location>". The role key is built from the bare
// title, so a row that keeps the suffix produces a key no lookup can reach —
// `normTitle` folds the dash away and glues the location onto the title, giving
// `x:foorban|customer care intern rho italy|rho` where the lookup builds
// `x:foorban|customer care intern|rho`. checkDup then only ever fires on an
// exact URL hit, so the same role re-posted under a new job id reads as new.
//
// The cross-portal check above CANNOT see this: it pulls the title back OUT of
// a key and feeds it in, so it passes whatever the key happened to be built
// from. This one starts from the cell, which is the only honest starting point.
// ---------------------------------------------------------------------------
const splitCsvLine = (line) => {
  const out = [];
  let cur = '';
  let inQ = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQ) {
      if (ch === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; } else inQ = false;
      } else cur += ch;
    } else if (ch === '"') inQ = true;
    else if (ch === ';') { out.push(cur); cur = ''; } else cur += ch;
  }
  out.push(cur);
  return out;
};

const raw = readFileSync(CSV, 'utf-8').replace(/^﻿/, '');
const cellHeader = splitCsvLine(raw.split('\n')[0]);
const iCo = cellHeader.indexOf('Company / Outreach Account');
const iTitle2 = cellHeader.indexOf('Matching Job Titles');
const iLoc2 = cellHeader.indexOf('Locations');

const unreachable = [];
let rolesSeen = 0;
for (const line of raw.split('\n').slice(1)) {
  if (!line.trim()) continue;
  const cols = splitCsvLine(line);
  const company = (cols[iCo] || '').trim();
  if (!company) continue;
  const titles = splitColumn(cols[iTitle2] || '', 'Matching Job Titles');
  const locs = splitColumn(cols[iLoc2] || '', 'Locations');
  titles.forEach((t, idx) => {
    const bare = stripSeatSuffix(t);
    if (!bare) return;
    rolesSeen++;
    // A never-seen URL forces the key to do the work: the URL check cannot help.
    const verdict = checkDup(h, company, bare, locs[idx] || locs[0] || '', 'https://example.com/never-seen-url');
    if (verdict.dup !== true) unreachable.push(`${company}: ${bare}`);
  });
}
assert.ok(rolesSeen > 50, `expected to walk >50 history roles, only saw ${rolesSeen}`);
assert.deepEqual(
  unreachable,
  [],
  `${unreachable.length}/${rolesSeen} history roles are unreachable by company+title+location ` +
    `(checkDup only matches their URL):\n${unreachable.slice(0, 5).join('\n')}`,
);

// ---------------------------------------------------------------------------
// Invariant: a spelling variant of a KNOWN company must still dedup.
//
// The map was keyed on `toLowerCase()` while every role key inside an entry is
// built with `normCompany` — which strips legal suffixes and folds accents. So
// "Acme S.p.A." and "Acme" were two entries on the outside and one key shape on
// the inside: the lookup missed, and the comparison written for exactly this
// case never ran. Measured before the fix, feeding the Accenture row's own URL
// back in under a suffixed spelling:
//
//     checkDup(h, "ACCENTURE S.P.A.", …, <a URL taken from history>)
//       -> {"dup": false, "companyKnown": false}
//
// Same URL, same company, reported as new — and not even as a known company.
//
// The seat-suffix invariant above cannot see this class: it starts from the
// cell's own spelling, so the lookup always succeeded. This one starts from a
// second spelling of the same name, which is what a portal actually returns.
// ---------------------------------------------------------------------------
const accentureUrl = [...accenture.urls][0];
assert.equal(
  checkDup(h, 'ACCENTURE S.P.A.', 'anything', 'Milan', accentureUrl).dup,
  true,
  'a legal-suffix variant with the same URL must dedup',
);

// With a role history has never seen, the variant must still be recognised as a
// KNOWN company — that is what stops a run from proposing it as `[NEW COMPANY]`
// and, with it, a second row for a company that already has one.
const variantNewRole = checkDup(h, 'ACCENTURE S.P.A.', 'Quantum Gardening Intern', 'Milan', 'https://example.com/never-seen');
assert.equal(variantNewRole.dup, false);
assert.equal(variantNewRole.companyKnown, true, 'a variant spelling is still a company we know');

// By role key alone, on a URL history has never seen, so the key has to do the
// work rather than the URL shortcut.
assert.equal(
  checkDup(h, 'Accenture S.p.A.', title, city, 'https://example.com/never-seen').dup,
  true,
  'a variant spelling must dedup on company+title+city, not only on an exact URL',
);

// The other half: normalising strips legal suffixes, not distinguishing words.
// `Accenture Italia` is a real value in this history (as a brand), so it is the
// honest neighbour to test against rather than an invented one.
assert.equal(
  checkDup(h, 'Accenture Italia', title, city, 'https://example.com/never-seen').dup,
  false,
  'stripping a legal suffix must not merge two genuinely different names',
);

console.log(
  `history-smoke: OK (${h.size} companies, ${checked} URLs round-tripped, ${rolesSeen} role keys reachable)`,
);
