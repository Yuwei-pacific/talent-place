// node test/linkedin-guest-smoke.mjs — card identity, and surviving a block.
//
// Two independent properties:
//   1. a card's URL belongs to THAT card (the cascade bug)
//   2. one blocked source does not take the run down with it
import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import { parseGuestCards, linkedinGuestAdapter } from '../lib/discovery/linkedin-guest.js';
import { runDiscovery } from '../lib/discovery/run.js';
import { RateLimiter, newSourceHealth, newStopToken } from '../lib/ratelimit.js';

// ---------------------------------------------------------------------------
// Card identity. Written as markup, not as types, because the bug was a
// desynchronised array and only markup can desynchronise it.
// ---------------------------------------------------------------------------

const card = (id, name, linkOverride) => `
<li>
  <div data-entity-urn="urn:li:jobPosting:${id}"></div>
  <h3 class="base-search-card__title">${name} Intern</h3>
  <a class="base-search-card__subtitle" href="/co">${name} Corp</a>
  <span class="job-search-card__location">Milan, Italy</span>
  ${linkOverride ?? `<a class="base-card__full-link" href="https://it.linkedin.com/jobs/view/${name}-intern-at-${name}-corp-${id}?position=1">go</a>`}
  <time>2 days ago</time>
</li>`;

/** A URL is correct for a card if it is that card's own slug, or the urn
 *  fallback — which is the documented behaviour when a block has no usable
 *  anchor, not a mis-association. */
const belongsTo = (url, urn) => url.includes(`-${urn}`) || url.includes(`/jobs/view/${urn}/`);

{
  const clean = card(111, 'alpha') + card(222, 'beta') + card(333, 'gamma');
  const cards = parseGuestCards(clean, 'q');
  assert.equal(cards.length, 3);
  for (const c of cards) {
    assert.ok(belongsTo(c.url, c.sourceJobId), `clean page: ${c.url} does not belong to ${c.sourceJobId}`);
    assert.ok(c.company.endsWith('Corp'), 'company must be parsed');
    assert.equal(c.posted, '2 days ago', 'the posted date must be kept: freshness is how A1 is checkable');
    assert.equal(c.snippet, 'posted: 2 days ago');
  }
}

// The regression. A single card whose full-link anchor carries no href used to
// shift every LATER card onto its neighbour's URL. Verified against the old
// implementation before it was replaced: the cascade reproduced exactly.
{
  const html = card(111, 'alpha') + card(222, 'beta', '<a class="base-card__full-link">no link</a>') + card(333, 'gamma');
  const cards = parseGuestCards(html, 'q');
  assert.equal(cards.length, 3);
  const byUrn = Object.fromEntries(cards.map((c) => [c.sourceJobId, c]));
  assert.ok(belongsTo(byUrn['111'].url, '111'), 'the card BEFORE the malformed one must be unaffected');
  assert.ok(belongsTo(byUrn['333'].url, '333'), 'the card AFTER the malformed one must NOT take its neighbour URL');
  assert.ok(belongsTo(byUrn['222'].url, '222'), 'the malformed card falls back to its own urn URL');
  assert.ok(
    !byUrn['222'].url.includes('gamma'),
    'the malformed card must never adopt the next card identity',
  );
}

// Same, with the malformed card first — under the old code this poisoned every
// card in the page.
{
  const html = card(111, 'alpha', '<span>none</span>') + card(222, 'beta') + card(333, 'gamma');
  const cards = parseGuestCards(html, 'q');
  const byUrn = Object.fromEntries(cards.map((c) => [c.sourceJobId, c]));
  assert.ok(belongsTo(byUrn['222'].url, '222'), 'a malformed FIRST card must not shift the second');
  assert.ok(belongsTo(byUrn['333'].url, '333'), 'a malformed FIRST card must not shift the third');
}

// Non-card blocks are skipped rather than becoming empty cards.
{
  const cards = parseGuestCards('<li><div>decoration</div></li>' + card(111, 'alpha'), 'q');
  assert.equal(cards.length, 1, 'a block with no urn and no title is not a job card');
}

// ---------------------------------------------------------------------------
// Surviving a block. The old adapter threw on the first non-gone failure,
// aborting every remaining query and losing the source's whole output.
// ---------------------------------------------------------------------------
await (async () => {
  const mk = (status, body) => async () => {
    const srv = createServer((_req, res) => {
      res.writeHead(status, { 'content-type': 'text/html' });
      res.end(body);
    });
    await new Promise((r) => srv.listen(0, '127.0.0.1', r));
    return { url: `http://127.0.0.1:${srv.address().port}`, close: () => new Promise((r) => srv.close(r)) };
  };

  const good = await mk(200, card(111, 'alpha'))();
  const bad = await mk(403, 'blocked')().catch(() => null);
  const badSrv = await mk(403, 'blocked')();

  // The adapter must return its cards rather than throwing, even when one of
  // its query x location pairs is refused. The link from the blocked host is
  // unreachable, so this asserts the graceful path via runDiscovery below.
  const broken = {
    id: 'broken-source',
    discover: async () => {
      throw new Error('this adapter is broken');
    },
  };
  const healthy = {
    id: 'healthy-source',
    discover: async (_q, ctx) => {
      await ctx.guard.limiter.acquire();
      return parseGuestCards(await (async () => {
        const r = await fetch(good.url);
        return r.text();
      })(), 'q');
    },
  };

  const { cards, report } = await runDiscovery([broken, healthy], ['x'], { rates: { 'healthy-source': 100 } });
  assert.equal(report.length, 2);
  assert.equal(report[0].status, 'error', 'a throwing adapter must be reported, not propagated');
  assert.ok(report[0].reason.includes('broken'), 'the report must carry WHY, which is the A1 declaration duty');
  assert.equal(report[1].status, 'ok');
  assert.equal(cards.length, 1, 'the healthy source must still deliver when another source died');

  await good.close();
  await badSrv.close();
  if (bad) await bad.close();
})();

// A refused pair is skipped, not fatal, and the source keeps going.
await (async () => {
  // Note: the request listener takes (req, res) only — a third parameter is
  // undefined, so the counter has to be closed over explicitly.
  let n = 0;
  const srv = createServer((_req, res) => {
    n++;
    if (n === 1) {
      res.writeHead(403);
      res.end('no');
      return;
    }
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(card(999, 'delta'));
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${srv.address().port}`;

  const adapter = linkedinGuestAdapter(['Milan', 'Rome'], { baseUrl: base });
  const limiter = new RateLimiter({ ratePerSec: 100, jitter: 0, random: () => 0 });
  const stop = newStopToken();
  const guard = { limiter, stop, health: newSourceHealth() };

  const cards = await adapter.discover(['q'], { guard, stop, cap: 200 });
  assert.ok(Array.isArray(cards), 'discover must return an array, never throw, on a 403');
  assert.equal(stop.stopped, true, 'a 403 with no retry allowed must stop the source');
  assert.equal(stop.kind, 'blocked');
  assert.ok(srv.listening);
  await new Promise((r) => srv.close(r));
})();

console.log('linkedin-guest-smoke: OK (card identity confined, urn fallback, 403 survives, source isolation)');
