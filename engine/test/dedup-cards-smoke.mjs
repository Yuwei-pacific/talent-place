// node test/dedup-cards-smoke.mjs
import { strict as assert } from 'node:assert';
import { dedupCards } from '../lib/dedup-cards.js';

// A4 §9's THIRD key: "combinazione azienda + titolo normalizzato + luogo".
// Only the URL and source-id keys are merged here, because the triple is not a
// merge — A4 says "Confermare l'identità prima di fondere record", and two
// identical titles at one company in one city can be two openings.
//
// The case is measured, not invented: on the 2026-09-24 Strategic design run,
// Ferrero's "Assistant Chef de produit Glaces" arrived under two LinkedIn ids
// with identical company, title, city and date, so neither key above could join
// them. Reporting the pair is what makes the resolution reproducible.
{
  const a = { title: 'Assistant Chef de produit Glaces - Stage', company: 'Ferrero', location: 'Rouen, France',
              url: 'https://fr.linkedin.com/jobs/view/x-4460373968', snippet: '', sourceJobId: '4460373968',
              source: 'linkedin', discoveryQuery: 'q' };
  const b = { ...a, url: 'https://fr.linkedin.com/jobs/view/x-4460388636', sourceJobId: '4460388636' };
  const other = { ...a, title: 'Chef de Projet Digitalisation Supply Chain', sourceJobId: '1', url: 'https://fr.linkedin.com/jobs/view/y-1' };
  const r = dedupCards([a, b, other]);
  assert.equal(r.unique.length, 3, 'different ids and different URLs: nothing above merges them');
  assert.equal(r.dupCount, 0);
  assert.equal(r.nearDuplicates.length, 1, 'A4 §9 calls the pair one role, so the run must say so');
  assert.equal(r.nearDuplicates[0].cards.length, 2);
  assert.ok(r.nearDuplicates[0].key.startsWith('x:ferrero|'), 'keyed on the normalised triple');

  // ...and the report must NOT fire on a genuinely different role.
  const clean = dedupCards([a, other]);
  assert.equal(clean.nearDuplicates.length, 0, 'different titles are different roles, not near-duplicates');

  // The normalisation is shared with the history lookup, so it folds what that
  // folds: a legal suffix, an accent, an intern synonym, a city alias.
  const folded = dedupCards([a, { ...b, company: 'Ferrero S.p.A.', title: 'Assistant Chef de Produit Glaces - Stage', location: 'Rouen, Francia' }]);
  assert.equal(folded.nearDuplicates.length, 1, 'the triple is compared normalised, not raw');
  assert.equal(folded.unique.length, 2, 'and folding never merges — only reports');
}

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
