// node test/attribution-smoke.mjs
//
// A1 §Fonti: "Una pagina aggregata è una fonte di scoperta, non un datore di
// lavoro." The names below are the ones the 2026-09-22 Accessory design ED.14
// run actually produced — 363 unique cards, of which these arrived attributed to
// a body that does not hire.
import { strict as assert } from 'node:assert';
import { existsSync } from 'node:fs';
import {
  loadAggregators,
  defaultAggregatorPath,
  aggregatorFor,
  matchesCompany,
} from '../lib/attribution.js';
import { normCompany } from '../lib/normalize.js';

// ---------------------------------------------------------------------------
// The table must be where the code looks.
//
// `company-aliases.csv` was written, then pointed at a path that did not exist,
// so its rung never fired and nothing said so. A table that is not read is
// indistinguishable from a table with nothing in it — unless something asserts
// it was read.
// ---------------------------------------------------------------------------
const path = defaultAggregatorPath();
assert.ok(existsSync(path), `aggregator table not found at ${path} — the entry list would silently never fire`);
const table = loadAggregators(path);
assert.equal(table.missing, false, 'the shipped table must be found');
assert.ok(table.entries.length >= 10, `expected the measured entries, got ${table.entries.length}`);

// Every pattern must be a fixed point of `normCompany`, because that is what it
// is matched against. An entry written as "Lavoropiù SpA" would be a pattern
// that can never fire — the list would look populated and do nothing.
for (const e of table.entries) {
  assert.equal(
    normCompany(e.pattern),
    e.pattern,
    `entry "${e.pattern}" is not in normalised form; write normCompany("${e.pattern}") instead`,
  );
  assert.ok(e.note.length > 0, `entry "${e.pattern}" has no note saying what it is`);
}

// ---------------------------------------------------------------------------
// Measured on that run: these arrived attributed to a non-employer.
// ---------------------------------------------------------------------------
const MEASURED = [
  ['BoF Careers', 'bof careers'],
  ['leManoosh', 'lemanoosh'],
  ['Ali Lavoro', 'ali lavoro'],
  ['Ali Professional', 'ali professional'],
  ['Orienta Agenzia per il Lavoro', 'orienta agenzia per il lavoro'],
  ['AFOL Milano', 'afol milano'],
  ['Adecco', 'adecco'],
  ['Lavoropiù SpA', 'lavoropiu'],
  ['Openjobmetis SpA', 'openjobmetis'],
  ['GRETA de la Création…', 'greta de la creation'],
];
for (const [asSeen, expected] of MEASURED) {
  const hit = aggregatorFor(asSeen, table);
  assert.ok(hit, `"${asSeen}" must be recognised as a discovery source, not an employer`);
  assert.equal(hit.pattern, expected, `"${asSeen}" resolved to the wrong entry`);
}

// ---------------------------------------------------------------------------
// And the employers on that same run must survive. A mismatch detector that
// flags everything protects nothing: two of the aggregator's postings were
// duplicates of roles the employers themselves had also published.
// ---------------------------------------------------------------------------
for (const employer of ['Miu Miu', 'Prada Group', 'Italdesign', 'Zenesis', 'Ferrari']) {
  assert.equal(
    aggregatorFor(employer, table),
    null,
    `"${employer}" hires people — attributing it to a board is the same error in the other direction`,
  );
}

// ---------------------------------------------------------------------------
// The matching rule itself.
//
// Whole-token runs, not substrings. "Orienta" had to catch "Orienta Agenzia per
// il Lavoro" while leaving "Orientamento Srl" alone, and a substring test cannot
// do both.
// ---------------------------------------------------------------------------
assert.equal(matchesCompany('orienta', normCompany('Orienta Agenzia per il Lavoro')), true);
assert.equal(
  matchesCompany('orienta', normCompany('Orientamento Srl')),
  false,
  'a substring test would match here and demote a real employer',
);
assert.equal(matchesCompany('adecco', normCompany('Adecco Italia SpA')), true, 'legal suffixes do not block a hit');
assert.equal(matchesCompany('adecco', normCompany('Adeccology')), false);
assert.equal(matchesCompany('ali lavoro', normCompany('Ali Lavoro')), true);
assert.equal(matchesCompany('ali lavoro', normCompany('Ali')), false, 'a pattern longer than the name cannot match');
assert.equal(matchesCompany('bof careers', ''), false, 'an empty poster matches nothing');

// ---------------------------------------------------------------------------
// A missing file and an empty file are different answers, and the manifest has
// to be able to tell them apart — the distinction `load_aliases` had to make.
// ---------------------------------------------------------------------------
const gone = loadAggregators('/nonexistent/definitely/not/here.csv');
assert.equal(gone.missing, true);
assert.deepEqual(gone.entries, []);

console.log('attribution-smoke: OK');
