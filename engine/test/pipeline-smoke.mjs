// node test/pipeline-smoke.mjs — the deterministic half of a run.
//
// Driven by a stub adapter, so this never touches the network. The assertions
// are about ORDER (geo before dedup before prefilter) — the property that is
// invisible in the output and expensive when wrong, because a duplicate that
// consumes a topK slot silently removes a real role from the run.
import { strict as assert } from 'node:assert';
import { buildQueries, tagCards, runPipeline } from '../lib/pipeline.js';
import { runDiscovery } from '../lib/discovery/run.js';

const card = (over) => ({
  title: 'Intern',
  company: 'Acme',
  location: 'Milan, Italy',
  url: 'https://example.com/1',
  snippet: '',
  source: 'stub',
  discoveryQuery: 'service design stage — Milan, Italy',
  ...over,
});

const cfg = {
  masterId: 'test-master',
  edition: 'ED.00',
  areas: { 'Area One': ['service design', 'customer experience'], 'Area Two': ['innovation'] },
  internshipTerms: ['stage', 'internship'],
  locations: ['Milan, Italy'],
  falseFriends: [],
  topK: 10,
};

// ---------------------------------------------------------------------------
// 1. The fan-out. A1: explore every area, combine activity terms with internship
//    terms, and do NOT run only the first term of a list.
// ---------------------------------------------------------------------------
{
  const pairs = buildQueries(cfg);
  assert.equal(pairs.length, (2 + 1) * 2, 'every area term x every internship term');
  assert.ok(pairs.some((p) => p.query === 'service design stage'));
  assert.ok(pairs.some((p) => p.query === 'innovation internship'), 'the second area must not be dropped');
  assert.ok(pairs.some((p) => p.area === 'Area Two'), 'area tagging must survive the fan-out');
  const deduped = new Set(pairs.map((p) => p.query));
  assert.equal(deduped.size, pairs.length, 'the fan-out must not repeat a query');
}

// ---------------------------------------------------------------------------
// 2. Tagging. Adapters append their own location to discoveryQuery, so the
//    match is by prefix; a card found by two areas belongs to both.
// ---------------------------------------------------------------------------
{
  const pairs = buildQueries(cfg);
  const tagged = tagCards(
    [
      card({ discoveryQuery: 'service design stage — Milan, Italy' }),
      card({ discoveryQuery: 'innovation internship — Milan, Italy' }),
      card({ discoveryQuery: 'something we did not ask for' }),
    ],
    pairs,
  );
  assert.deepEqual(tagged[0].areas, ['Area One']);
  assert.deepEqual(tagged[1].areas, ['Area Two']);
  assert.deepEqual(tagged[2].areas, [], 'an untracked card gets no area rather than a guessed one');
  assert.deepEqual(tagged[0].queries, ['service design stage']);

  // A card found by two queries belongs to BOTH areas. dedupCards records that
  // as "q1 + q2", so a whole-string prefix test only ever credits the first —
  // which silently drops the second area from Master-fit Themes downstream.
  const multi = tagCards(
    [{ ...card(), discoveryQuery: 'service design stage — Milan, Italy + innovation internship — Milan, Italy' }],
    pairs,
  );
  assert.deepEqual(
    multi[0].areas.sort(),
    ['Area One', 'Area Two'],
    'a card surfaced by two queries must carry both areas, not just the first',
  );
  assert.deepEqual(multi[0].queries.sort(), ['innovation internship', 'service design stage']);
}

// ---------------------------------------------------------------------------
// 3. Order: geo -> dedup -> prefilter.
// ---------------------------------------------------------------------------
{
  const stub = {
    id: 'stub',
    async discover() {
      return [
        // A duplicate pair: same sourceJobId, so dedupCards must collapse them.
        card({ company: 'Alpha', sourceJobId: '1', url: 'https://example.com/a', title: 'Service Design Intern' }),
        card({ company: 'Alpha', sourceJobId: '1', url: 'https://example.com/a-mirror', title: 'Service Design Intern' }),
        // A second real role, so topK has something to compete with.
        card({ company: 'Beta', sourceJobId: '2', url: 'https://example.com/b', title: 'Innovation Intern' }),
        // Out of scope, and attractive enough that it would win a topK slot.
        card({
          company: 'Gamma',
          sourceJobId: '3',
          url: 'https://example.com/c',
          title: 'Service Design Intern',
          location: 'Austin, TX',
        }),
      ];
    },
  };

  const r = await runPipeline([stub], { ...cfg, topK: 2 }, {}, { rates: { stub: 1000 } });

  assert.equal(r.counters.cardsSeen, 4);
  assert.equal(r.counters.afterGeo, 3, 'the Austin card must leave before anything else spends budget');
  assert.equal(r.counters.afterDedup, 2, 'the mirror must collapse before prefilter can spend a topK slot');
  assert.equal(r.droppedNonEu.length, 1);
  assert.equal(r.droppedNonEu[0].company, 'Gamma');

  const keptCompanies = r.kept.map((c) => c.company).sort();
  assert.deepEqual(
    keptCompanies,
    ['Alpha', 'Beta'],
    'dedup must run BEFORE prefilter: with topK=2 a duplicate that survived into prefilter would eat a slot and drop a real role',
  );
  assert.equal(r.kept.length, 2);
}

// ---------------------------------------------------------------------------
// 4. Nothing is silently discarded: every card that entered leaves through a
//    named exit. This is what makes the "declare coverage" duty auditable.
// ---------------------------------------------------------------------------
{
  const stub = {
    id: 'stub',
    async discover() {
      return [
        card({ company: 'Alpha', sourceJobId: '1', title: 'Service Design Intern' }),
        card({ company: 'Beta', sourceJobId: '2', url: 'https://example.com/b', title: 'Innovation Intern' }),
        card({ company: 'Gamma', sourceJobId: '3', url: 'https://example.com/c', title: 'Janitor', location: 'Austin, TX' }),
      ];
    },
  };
  const r = await runPipeline([stub], { ...cfg, topK: 1 }, {}, { rates: { stub: 1000 } });
  const accounted =
    r.kept.length + r.dropped.length + r.droppedNonEu.length + r.duplicates.length;
  assert.equal(accounted, r.counters.cardsSeen, `${accounted} != ${r.counters.cardsSeen}: a card left the run through no named exit`);
  assert.equal(r.kept.length, 1, 'topK is honoured');
  assert.equal(r.dropped.length, 1, 'what topK cut is kept, not discarded');
}

// ---------------------------------------------------------------------------
// 5. A source that throws is reported, and the run continues without it.
// ---------------------------------------------------------------------------
{
  const broken = {
    id: 'broken',
    async discover() {
      throw new Error('adapter exploded');
    },
  };
  const healthy = {
    id: 'healthy',
    async discover() {
      return [card({ company: 'Alpha', sourceJobId: '9' })];
    },
  };
  const r = await runPipeline([broken, healthy], cfg, {}, { rates: { broken: 1000, healthy: 1000 } });
  assert.equal(r.report.length, 2);
  assert.equal(r.report[0].status, 'error');
  assert.ok(r.report[0].reason.includes('exploded'), 'the reason must reach the report — that is the A1 declaration duty');
  assert.equal(r.kept.length, 1, 'a dead source must not cost the run');
}

// ---------------------------------------------------------------------------
// 6. The cap is a runaway guard, not a budget.
//
// Regression: the adapter used to return early at 200 cards, which looked
// harmless while the driver called `discover` once per query (counter reset
// every call, cap never fired). Driving all queries through one call made it
// fire after 20 of 72 queries and cost most of the fan-out — on a real replay,
// 200 cards instead of a possible ~720. A realistic fan-out must not be
// silently truncated.
// ---------------------------------------------------------------------------
{
  const QUERIES = 40; // realistic: a 7-area A2 at 3 terms x 2 suffixes is ~40-70
  const PER_QUERY = 10; // LinkedIn guest returns 10 per page
  const stub = {
    id: 'stub',
    async discover(_q, ctx) {
      const out = [];
      for (let i = 0; i < QUERIES * PER_QUERY; i++) {
        if (out.length >= ctx.cap) break;
        out.push(card({ company: `C${i}`, sourceJobId: String(i), url: `https://example.com/${i}` }));
      }
      return out;
    },
  };
  const r = await runPipeline([stub], cfg, {}, { rates: { stub: 1000 } });
  assert.equal(
    r.counters.cardsSeen,
    QUERIES * PER_QUERY,
    `a ${QUERIES}-query fan-out at ${PER_QUERY} cards each must not be truncated; ` +
      `saw ${r.counters.cardsSeen} of ${QUERIES * PER_QUERY}. If the default cap is the cause, it is a recall bug.`,
  );
  assert.equal(r.report[0].status, 'ok', 'and the source must not report itself as capped');
}

// An explicit cap is still honoured, and says so.
{
  const stub = {
    id: 'stub',
    async discover(_q, ctx) {
      return Array.from({ length: 50 }, (_, i) =>
        card({ company: `C${i}`, sourceJobId: String(i), url: `https://example.com/${i}` }),
      ).slice(0, ctx.cap);
    },
  };
  const r = await runDiscovery([stub], ['service design stage'], { cap: 5, rates: { stub: 1000 } });
  assert.equal(r.cards.length, 5);
  assert.equal(r.report[0].status, 'ok', 'a source that returns exactly cap without stopping itself is ok');
}

console.log('pipeline-smoke: OK (fan-out, tagging, geo->dedup->prefilter order, no silent loss, source isolation, cap)');
