// node test/url-normalize-smoke.mjs — one URL identity for the whole engine
//
// There were three implementations and they disagreed, which is how one run came
// to hold two opinions about what the same URL was:
//
//   dedup-cards.ts  stripped the WHOLE query -> `?gh_jid=123` and `?gh_jid=456`
//                   collapsed into one posting and a role vanished. Silently:
//                   dedupCards has no `duplicates` list, the merged card is
//                   simply not there.
//   history.ts      kept the whole query    -> a URL carrying a tracking
//                   parameter never matched the same URL without one.
//   sync_export.py  stripped the whole query (the third opinion).
//
// A4 states the rule: dedup "per URL diretto normalizzato (senza rimuovere
// parametri identificativi dell'annuncio)". Identity is kept; tracking is not.
// `test_sync_export.py` asserts the Python mirror equals this one.
import { strict as assert } from 'node:assert';
import { normalizeUrl, isTrackingParam } from '../lib/normalize.js';
import { dedupCards } from '../lib/dedup-cards.js';

const card = (url, over = {}) => ({
  title: 'Intern',
  company: 'Acme',
  location: 'Milan',
  url,
  snippet: '',
  source: 'employer',
  discoveryQuery: 'q',
  ...over,
});

// ---------------------------------------------------------------------------
// Identity survives
// ---------------------------------------------------------------------------
assert.notEqual(
  normalizeUrl('https://x.test/jobs/1?gh_jid=123'),
  normalizeUrl('https://x.test/jobs/1?gh_jid=456'),
  'two job ids on one path are two postings, not one',
);

// ---------------------------------------------------------------------------
// Tracking does not, in any order, and never changes the key
// ---------------------------------------------------------------------------
const bare = normalizeUrl('https://x.test/jobs/1?gh_jid=123');
for (const noisy of [
  'https://x.test/jobs/1?utm_source=linkedin&gh_jid=123',
  // the bare `utm` some tools emit, and a `utm_*` variant nobody enumerated
  'https://x.test/jobs/1?utm=abc&gh_jid=123',
  'https://x.test/jobs/1?utm_id=9&gh_jid=123',
  'https://x.test/jobs/1?gh_jid=123&trackingId=abc',
  'https://x.test/jobs/1?gh_jid=123&trk=public_jobs',
  'https://x.test/jobs/1?gh_jid=123#apply',
]) {
  assert.equal(normalizeUrl(noisy), bare, `${noisy} must normalise to ${bare}`);
}

// The prefix rule must not over-match. `utmost` is not a utm parameter, and a
// rule that swallowed it would quietly drop real ones next.
assert.notEqual(
  normalizeUrl('https://x.test/jobs/1?utmost=1'),
  normalizeUrl('https://x.test/jobs/1'),
  'utmost is not part of the utm family',
);
assert.equal(
  normalizeUrl('https://x.test/jobs/1?b=2&a=1'),
  normalizeUrl('https://x.test/jobs/1?a=1&b=2'),
  'parameter order must not change the key',
);
assert.equal(
  normalizeUrl('https://x.test/jobs/1?utm_source=x'),
  normalizeUrl('https://x.test/jobs/1'),
  'a query of nothing but tracking is the same as no query',
);
assert.equal(normalizeUrl('https://X.TEST/Jobs/1/'), normalizeUrl('https://x.test/jobs/1'));

// Unparseable input must not throw and must not invent a key.
assert.equal(normalizeUrl(''), '');
assert.equal(typeof normalizeUrl('not a url'), 'string');
assert.equal(normalizeUrl('not a url'), 'not a url');

// ---------------------------------------------------------------------------
// The behaviour this exists to protect, through the real merge path
// ---------------------------------------------------------------------------
const twoIds = dedupCards([
  card('https://boards.test/jobs?gh_jid=123'),
  card('https://boards.test/jobs?gh_jid=456'),
]);
assert.equal(
  twoIds.unique.length,
  2,
  'two postings that differ only by gh_jid must NOT merge — the merge loses one with no trace',
);
assert.equal(twoIds.dupCount, 0);

const onePosting = dedupCards([
  card('https://x.test/jobs/1?utm_source=linkedin'),
  card('https://x.test/jobs/1?trackingId=abc'),
]);
assert.equal(onePosting.unique.length, 1, 'one posting reached twice by different tracking must merge');

// A card carrying `sourceJobId` is keyed on that, never on the URL — so the
// change above cannot disturb the adapters that set one.
const byId = dedupCards([card('https://a.test/1', { sourceJobId: 'x1' }), card('https://b.test/2', { sourceJobId: 'x1' })]);
assert.equal(byId.unique.length, 1, 'same sourceJobId is the same posting whatever the URL says');

// The RULE, not the list: a `utm_*` variant nobody enumerated is still tracking,
// and a word that merely starts with the same letters is not.
assert.ok(isTrackingParam('utm_source'), 'an enumerated name');
assert.ok(isTrackingParam('utm_id'), 'a utm_ variant nobody enumerated');
assert.ok(isTrackingParam('utm'), 'the bare form some tools emit');
assert.ok(isTrackingParam('TRK'), 'case must not matter');
assert.ok(isTrackingParam('trk'), 'an enumerated name');
assert.ok(!isTrackingParam('utmost'), 'same first letters, not a utm parameter');
assert.ok(!isTrackingParam('gh_jid'), 'identity is never dropped');

console.log('url-normalize-smoke: OK (identity kept, tracking dropped, order-proof, gh_jid survives dedup)');
