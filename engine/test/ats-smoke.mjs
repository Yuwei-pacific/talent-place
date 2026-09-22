// node test/ats-smoke.mjs — the employer-ATS adapter.
//
// Wired into `defaultAdapters` only on 2026-09-22. Until then it had no caller,
// so `run.ts`'s docstring ("plus ATS boards when the caller has tokens") described
// an unreachable branch -- the function accepted no boards -- while
// `DEFAULT_RATES.ats` budgeted a rate for a source that never ran. A1 prefers the
// employer's own ATS over any portal, so this is recall, not hygiene.
import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import { atsAdapter } from '../lib/discovery/ats.js';
import { defaultAdapters } from '../lib/discovery/run.js';
import { RateLimiter, newSourceHealth, newStopToken } from '../lib/ratelimit.js';

const newGuard = () => ({
  limiter: new RateLimiter({ ratePerSec: 100, jitter: 0, random: () => 0 }),
  stop: newStopToken(),
  health: newSourceHealth(),
});

const server = async (routes) => {
  const srv = createServer((req, res) => {
    // Keyed on the path: the real APIs are queried with a `?content=false` /
    // `?mode=json` suffix, and a route table that only matched bare paths would
    // 404 every request and read as "the adapter returns nothing".
    const body = routes[new URL(req.url, 'http://x').pathname];
    if (!body) {
      res.writeHead(404);
      res.end('no');
      return;
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(body));
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  return { url: `http://127.0.0.1:${srv.address().port}`, close: () => new Promise((r) => srv.close(r)) };
};

// ---------------------------------------------------------------------------
// The company name. A board slug is a lowercase identifier, and A4 says
// `Company / Outreach Account` is "l'azienda che assume" -- the value colleagues
// read and the key dedup runs on. A slug reaching it would create a second row
// for an employer already present under its real name, which is the BoF Careers
// failure arriving by a different route.
// ---------------------------------------------------------------------------
{
  const srv = await server({
    '/v1/boards/acme/jobs': {
      jobs: [
        { id: 1, title: 'Service Design Intern', location: { name: 'Milan, Italy' }, absolute_url: 'https://acme.example/1' },
        { id: 2, title: 'Sales Director', location: { name: 'Paris' }, absolute_url: 'https://acme.example/2' },
      ],
    },
  });
  const adapter = atsAdapter([{ kind: 'greenhouse', board: 'acme', company: 'Acme S.p.A.' }], { baseUrl: srv.url });
  const cards = await adapter.discover(['service design stage'], { guard: newGuard(), stop: newStopToken(), cap: 100 });

  assert.equal(cards.length, 1, 'only the role matching the query comes back');
  assert.equal(cards[0].company, 'Acme S.p.A.', 'the display name, never the board slug');
  assert.equal(cards[0].title, 'Service Design Intern');
  assert.equal(cards[0].location, 'Milan, Italy');
  assert.equal(cards[0].source, 'employer');
  assert.equal(cards[0].url, 'https://acme.example/1');
  await srv.close();
}

// ---------------------------------------------------------------------------
// lever, which returns a bare array rather than an object.
// ---------------------------------------------------------------------------
{
  const srv = await server({
    '/v0/postings/beta': [
      { id: 'a', text: 'UX Research Intern', categories: { location: 'Rome, Italy' }, hostedUrl: 'https://beta.example/a' },
    ],
  });
  const adapter = atsAdapter([{ kind: 'lever', board: 'beta', company: 'Beta Srl' }], { baseUrl: srv.url });
  const cards = await adapter.discover(['ux research'], { guard: newGuard(), stop: newStopToken(), cap: 100 });

  assert.equal(cards.length, 1);
  assert.equal(cards[0].company, 'Beta Srl');
  assert.equal(cards[0].title, 'UX Research Intern');
  assert.equal(cards[0].location, 'Rome, Italy');
  await srv.close();
}

// ---------------------------------------------------------------------------
// An unimplemented kind. `kind` used to declare 'ashby' and 'workable' while only
// greenhouse and lever had branches, so a config listing one fell through the
// if/else, returned nothing, and reported nothing -- a source that looks wired
// and delivers silence.
//
// Refused at construction, so a misconfigured run dies before the sweep rather
// than after it.
// ---------------------------------------------------------------------------
assert.throws(
  () => atsAdapter([{ kind: 'workable', board: 'acme', company: 'Acme' }]),
  /workable/,
  'an unimplemented kind must be refused loudly, not silently yield nothing',
);

// ---------------------------------------------------------------------------
// The wiring. `atsAdapter` had no caller, so `defaultAdapters` is where this
// either becomes reachable or stays a library nobody runs.
// ---------------------------------------------------------------------------
{
  const withBoards = defaultAdapters({
    linkedinLocations: ['Milan, Italy'],
    atsBoards: [{ kind: 'greenhouse', board: 'acme', company: 'Acme S.p.A.' }],
  });
  assert.ok(
    withBoards.some((a) => a.id === 'ats'),
    `a configured board must reach the run, got sources: ${withBoards.map((a) => a.id).join(', ')}`,
  );

  const without = defaultAdapters({ linkedinLocations: ['Milan, Italy'] });
  assert.ok(
    !without.some((a) => a.id === 'ats'),
    'no boards means no ats source: it must not spend a rate on a source with nothing to query',
  );
}

console.log('ats-smoke: OK (display name not slug, greenhouse + lever parse, unknown kind refused, wired)');
