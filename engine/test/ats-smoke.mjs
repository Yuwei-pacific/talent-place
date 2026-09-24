// node test/ats-smoke.mjs — the employer-ATS adapter, and the work modes the
// employer APIs do and do not declare.
//
// Wired into `defaultAdapters` only on 2026-09-22. Until then it had no caller,
// so `run.ts`'s docstring ("plus ATS boards when the caller has tokens") described
// an unreachable branch -- the function accepted no boards -- while
// `DEFAULT_RATES.ats` budgeted a rate for a source that never ran. A1 prefers the
// employer's own ATS over any portal, so this is recall, not hygiene.
import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import { atsAdapter, WORK_MODE_DECLARABLE } from '../lib/discovery/ats.js';
import { ashbyBoard } from '../lib/discovery/employer.js';
import { admissibilityVerdict } from '../lib/admissibility.js';
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
  // Greenhouse declares no work mode, so the card must carry none. An absent
  // value is A1 §46's undeclared, which excludes nothing — the safe direction,
  // and the only honest one when the API says nothing.
  assert.equal(cards[0].workMode, undefined, 'greenhouse declares no work mode, so none may be invented');
  assert.equal(WORK_MODE_DECLARABLE.greenhouse, false);
  await srv.close();
}

// ---------------------------------------------------------------------------
// lever, which returns a bare array rather than an object — and which DOES
// declare a work mode. This is the only branch on which A1 §44's `fully-remote`
// ground can fire before a read.
// ---------------------------------------------------------------------------
{
  const srv = await server({
    '/v0/postings/beta': [
      { id: 'a', text: 'UX Research Intern', categories: { location: 'Rome, Italy' }, hostedUrl: 'https://beta.example/a', workplaceType: 'remote' },
      { id: 'b', text: 'UX Design Intern', categories: { location: 'Rome, Italy' }, hostedUrl: 'https://beta.example/b', workplaceType: 'hybrid' },
      // The spec's spelling, in the API's own casing, as an unknown value: it
      // must come back undeclared rather than being coerced to onsite.
      { id: 'c', text: 'UX Brand Intern', categories: { location: 'Rome, Italy' }, hostedUrl: 'https://beta.example/c', workplaceType: 'Flexible' },
      { id: 'd', text: 'UX Motion Intern', categories: { location: 'Rome, Italy' }, hostedUrl: 'https://beta.example/d' },
    ],
  });
  const adapter = atsAdapter([{ kind: 'lever', board: 'beta', company: 'Beta Srl' }], { baseUrl: srv.url });
  // `intern`, not `ux`, and that is not arbitrary: `matchQuery` drops terms of
  // two characters or fewer, so a query of "ux" selects nothing at all — which
  // reads as "the adapter returned no cards" rather than "the query was empty".
  // The query only has to select all four here; the mapping is the subject.
  const cards = await adapter.discover(['intern'], { guard: newGuard(), stop: newStopToken(), cap: 100 });

  const byId = Object.fromEntries(cards.map((c) => [c.sourceJobId, c]));
  assert.equal(cards[0].company, 'Beta Srl');
  assert.equal(cards[0].location, 'Rome, Italy');
  assert.equal(byId.a.workMode, 'fully_remote', "Lever's `remote` IS the fully-remote category — it is one of three exclusive values");
  assert.equal(byId.b.workMode, 'hybrid');
  assert.equal(byId.c.workMode, undefined, 'an unrecognised spelling must not be coerced — especially not to onsite');
  assert.equal(byId.d.workMode, undefined, 'absent is undeclared');
  assert.equal(WORK_MODE_DECLARABLE.lever, true);

  // And the declaration reaches the rule: this is the whole point of carrying it.
  assert.equal(
    admissibilityVerdict(byId.a).verdict,
    'escluso',
    'a Lever `remote` card must be excludable at the card stage, with no read',
  );
  assert.equal(admissibilityVerdict(byId.b).verdict, 'ammissibile');
  assert.equal(admissibilityVerdict(byId.c).verdict, 'ammissibile', 'undeclared keeps the uncertainty');
  await srv.close();
}

// ---------------------------------------------------------------------------
// Ashby — the third employer API, reached through `ashbyBoard` rather than the
// adapter. It declares `workplaceType` AND `isRemote`, and they answer
// DIFFERENT questions. Measured on a live board 2026-09-24: `isRemote` was true
// for 141 of 155 postings while `workplaceType` was Remote for 16, and on
// another board it was true for all 30 including the single Hybrid one.
//
// So `isRemote` means "may work remotely", not "entirely remote" — reading it
// would exclude ~91% of a board under a ground A1 reserves for work
// *interamente* da remoto. That is the failure this test exists to prevent.
// ---------------------------------------------------------------------------
{
  const srv = await server({
    '/posting-api/job-board/gamma': {
      jobs: [
        // The trap, as a card: `isRemote: true` and a Hybrid workplace.
        { id: 'h', title: 'Product Design Intern', employmentType: 'Intern', isListed: true, location: 'Milan', workplaceType: 'Hybrid', isRemote: true, jobUrl: 'https://gamma.example/h' },
        { id: 'r', title: 'Service Design Intern', employmentType: 'Intern', isListed: true, location: 'Milan', workplaceType: 'Remote', isRemote: true, jobUrl: 'https://gamma.example/r' },
        { id: 'n', title: 'Brand Design Intern', employmentType: 'Intern', isListed: true, location: 'Milan', workplaceType: null, isRemote: null, jobUrl: 'https://gamma.example/n' },
      ],
    },
  });
  const cards = await ashbyBoard('gamma', 'Gamma Srl', { baseUrl: srv.url });
  const byId = Object.fromEntries(cards.map((c) => [c.sourceJobId, c]));

  assert.equal(cards.length, 3, 'all three carry an intern signal');
  assert.equal(byId['ashby:h'].workMode, 'hybrid', 'Ashby spells it "Hybrid", not "hybrid"');
  assert.equal(byId['ashby:r'].workMode, 'fully_remote');
  assert.equal(byId['ashby:n'].workMode, undefined, 'a null workplace type is undeclared');

  assert.equal(
    admissibilityVerdict(byId['ashby:h']).verdict,
    'ammissibile',
    'isRemote:true plus workplaceType Hybrid is NOT fully remote — reading isRemote would exclude it',
  );
  assert.equal(admissibilityVerdict(byId['ashby:r']).verdict, 'escluso');
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

console.log(
  'ats-smoke: OK (display name not slug, greenhouse + lever parse, unknown kind refused, wired, ' +
    'work mode declared by lever and ashby but not greenhouse, isRemote is not the field)',
);
