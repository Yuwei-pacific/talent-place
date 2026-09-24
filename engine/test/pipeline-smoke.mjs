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
// 2. Tagging. Adapters append their own location to discoveryQuery, so the query
//    is the segment's HEAD; a card found by two areas belongs to both.
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

  // A query that is a PREFIX of another must not credit both areas. Comparing
  // with `startsWith` did exactly that, so the card carried a theme from an area
  // whose query it never matched — safe only for as long as no A2 term list
  // happens to collide, which is not a property anyone maintains.
  const prefixPairs = [
    { query: 'design intern', area: 'Broad' },
    { query: 'design intern ux', area: 'Narrow' },
  ];
  const collided = tagCards([card({ discoveryQuery: 'design intern ux — Milan' })], prefixPairs);
  assert.deepEqual(
    collided[0].areas,
    ['Narrow'],
    'a card found by "design intern ux" must not also be credited to "design intern"',
  );
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
// 3b. The false-friend list reports its own effect. A2 used to state its false
//     positives as SENTENCES about situations, and a sentence wrapped in \b...\b
//     matches no title or snippet — so the list could look populated while
//     scoring nothing down, and nothing said so.
// ---------------------------------------------------------------------------
{
  const stub = {
    id: 'stub',
    async discover() {
      return [card({ company: 'Alpha', sourceJobId: '1', url: 'https://example.com/a', title: 'Customer Service Agent' })];
    },
  };
  const sentence = 'Un CX Intern che gestisce chiamate senza analisi è un falso positivo.';
  const r = await runPipeline(
    [stub],
    { ...cfg, falseFriends: ['customer service agent', sentence], topK: 5 },
    {},
    { rates: { stub: 1000 } },
  );

  assert.equal(r.falseFriendHits['customer service agent'], 1, 'the term-shaped entry fires');
  assert.equal(r.falseFriendHits[sentence], 0, 'the sentence-shaped entry cannot fire, and the run says so');
  assert.ok(
    r.kept.some((c) => c.company === 'Alpha'),
    'scored down is not dropped: A2 says keep the recall and pay for the noise',
  );
}

// ---------------------------------------------------------------------------
// 4. Nothing is silently discarded: every card that entered leaves through a
//    named exit. This is what makes the "declare coverage" duty auditable.
//
//    Every new exit path has to be added here, and that is the point of the
//    assertion rather than an annoyance: a gate that removes cards without a
//    bucket is exactly how a rule becomes invisible.
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
    r.kept.length +
    r.dropped.length +
    r.droppedNonEu.length +
    r.unresolved.length +
    r.excluded.length +
    r.duplicates.length;
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

// ---------------------------------------------------------------------------
// 7. A1 §Fonti: a board or an agency is a discovery source, never an employer.
//
//    These are the 2026-09-22 Accessory design ED.14 collapses, as cards. Note
//    what dedup can and cannot do here: `leManoosh — CMF Designer Internship`
//    IS `Italdesign — CMF Designer Internship`, but the two copies carry
//    different URLs and different company names, so `dedupCards` merges nothing
//    and only the poster reveals what happened.
// ---------------------------------------------------------------------------
{
  const stub = {
    id: 'stub',
    async discover() {
      return [
        card({ company: 'Italdesign', sourceJobId: '1', url: 'https://example.com/ital', title: 'CMF Designer Internship' }),
        card({ company: 'leManoosh', sourceJobId: '2', url: 'https://example.com/leman', title: 'CMF Designer Internship' }),
        card({ company: 'Miu Miu', sourceJobId: '3', url: 'https://example.com/miu', title: 'Stage Sviluppo Prodotto Calzature' }),
        card({ company: 'BoF Careers', sourceJobId: '4', url: 'https://example.com/bof1', title: 'Stage Sviluppo Prodotto Calzature' }),
        card({ company: 'BoF Careers', sourceJobId: '5', url: 'https://example.com/bof2', title: 'Stage PRADA Windows Creative Intern' }),
      ];
    },
  };
  const r = await runPipeline([stub], { ...cfg, topK: 10 }, {}, { rates: { stub: 1000 } });

  assert.deepEqual(
    r.unresolved.map((c) => c.company).sort(),
    ['BoF Careers', 'BoF Careers', 'leManoosh'],
    'a posting attributed to a board is not attributed to the board',
  );
  assert.deepEqual(
    r.kept.map((c) => c.company).sort(),
    ['Italdesign', 'Miu Miu'],
    'the employers on the same run must survive — a flag that catches everything protects nothing',
  );
  assert.ok(
    !r.kept.some((c) => c.company === 'BoF Careers'),
    'an aggregator must never reach the corpus that becomes Company / Outreach Account',
  );

  // A1: "l'aggregatore resta registrato come fonte". The board's name is kept
  // for `Sources / Portals`; `company` is left as observed, because that is the
  // evidence the agent resolves the real employer against. The BUCKET is what
  // refuses the attribution — not an emptied field.
  const bof = r.unresolved.find((c) => c.company === 'BoF Careers');
  assert.equal(bof.poster, 'BoF Careers', 'the board is recorded as the poster');
  assert.equal(bof.company, 'BoF Careers', 'and the observed name is not destroyed on the way');

  // Per-entry counts, the `falseFriendHits` remedy: a list that stops firing
  // says so instead of sitting there looking like cover.
  assert.equal(r.aggregatorHits['bof careers'], 2);
  assert.equal(r.aggregatorHits['lemanoosh'], 1);
  assert.equal(r.aggregatorHits['adecco'], 0, 'an entry that matched nothing reports 0 rather than being absent');
  assert.equal(r.aggregatorTable.missing, false);
  assert.equal(r.counters.unresolved, 3);
}

// ---------------------------------------------------------------------------
// 8. A1 §44 at the card stage — the two grounds that need no read.
//
//    `senior-title` and `closed-signal` used to live in `prefilter` as score
//    deductions, and a deduction is not a rule: a senior card at base 0.3 lost
//    0.5 (clamped to 0) but query-term overlap put up to 0.25 back, so it reached
//    `kept` whenever topK was not tight.
// ---------------------------------------------------------------------------
{
  const stub = {
    id: 'stub',
    async discover() {
      return [
        card({ company: 'Alpha', sourceJobId: '1', title: 'Service Design Intern' }),
        card({ company: 'Beta', sourceJobId: '2', url: 'https://example.com/b', title: 'Senior Service Design Manager' }),
        card({ company: 'Gamma', sourceJobId: '3', url: 'https://example.com/c', title: 'Design Intern', snippet: 'offerta chiusa' }),
        card({ company: 'Delta', sourceJobId: '4', url: 'https://example.com/d', title: 'Design Intern', workMode: 'fully_remote' }),
        card({ company: 'Epsilon', sourceJobId: '5', url: 'https://example.com/e', title: 'Design Intern', workMode: 'to_verify' }),
      ];
    },
  };
  const r = await runPipeline([stub], { ...cfg, topK: 10 }, {}, { rates: { stub: 1000 } });

  assert.deepEqual(
    r.excluded.map((e) => e.ground).sort(),
    ['closed-ad', 'fully-remote', 'senior-without-stage'],
  );
  assert.deepEqual(
    r.kept.map((c) => c.company).sort(),
    ['Alpha', 'Epsilon'],
    'A1 §47: an undeclared — or explicitly unestablished — work mode must not exclude',
  );
  assert.ok(
    r.excluded.every((e) => e.detail.length > 0),
    'A4 asks for motivated examples, so every exclusion carries its reason',
  );
  assert.ok(
    !r.kept.some((c) => c.company === 'Beta'),
    'a senior role must be excluded, not merely scored down',
  );

  // The exclusions are a DIFFERENT bucket from the geography drop and from the
  // prefilter drop. A4: "Non confondere escluso per incompatibilità, duplicato
  // storico e non verificabile: sono esiti diversi."
  assert.equal(r.droppedNonEu.length, 0, 'nothing was out of geography here');
  assert.equal(r.counters.excluded, 3);
}

console.log(
  'pipeline-smoke: OK (fan-out, tagging, geo->gates->dedup->prefilter order, no silent loss, ' +
    'source isolation, cap, A1 §Fonti attribution, A1 §44 admissibility)',
);
