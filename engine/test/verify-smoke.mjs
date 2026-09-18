// node test/verify-smoke.mjs — the employer probe, offline.
//
// `statusFromCheck` renders a mechanical probe into A4's CLOSED vocabulary, so
// every value it returns has to be one a human can act on without the machine
// having overstated what it knows. The cases below are the ones a real batch
// produced, not invented shapes.
import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import { statusFromCheck, runVerification, parseTargets } from '../lib/verify.js';

const check = (over) => ({
  url: 'https://x.example/1',
  reachable: true,
  hasInternSignal: true,
  hasApply: true,
  title: 'Stage - Junior Innovation Consultant',
  detail: 'page alive',
  ...over,
});

// ---------------------------------------------------------------------------
// 1. A4's definition, taken literally: "pagina aziendale/ATS aperta con
//    candidatura visibile" is exactly reachable && hasApply.
// ---------------------------------------------------------------------------
{
  assert.equal(statusFromCheck(check()), 'Employer verified active');

  // avanade.com: a 194KB Next.js page with a working apply path and NO <title>
  // element at all. Verified by fetching it — the title is set client-side.
  // An empty title must NOT be read as "we learned nothing".
  assert.equal(
    statusFromCheck(check({ title: '', hasInternSignal: false })),
    'Employer verified active',
    'a page with an apply path is verified active even when the title is client-side',
  );
}

// ---------------------------------------------------------------------------
// 2. The soft 404. careers.kpmg.it answers a nonexistent job with a redirect to
//    errorpage/?errortype=Exception, HTTP 200, an empty <title>, and none of the
//    three signals. It must NOT read the same as a live page whose apply button
//    is JS-rendered — that would file a dead posting beside a live one.
// ---------------------------------------------------------------------------
{
  const softFourOhFour = statusFromCheck(check({ title: '', hasInternSignal: false, hasApply: false }));
  const jsRenderedButton = statusFromCheck(check({ hasApply: false }));
  assert.ok(softFourOhFour.startsWith('To verify'), 'a 200 that says nothing is still To verify, not Blocked');
  assert.notEqual(softFourOhFour, jsRenderedButton, 'the two must be distinguishable');
  assert.match(softFourOhFour, /no readable content/);
  assert.match(jsRenderedButton, /apply path not visible/);

  // A page with a title but no apply path is the JS-button case.
  assert.match(statusFromCheck(check({ hasApply: false, title: 'BIP Career Site' })), /apply path not visible/);
}

// ---------------------------------------------------------------------------
// 3. Unreachable is Blocked, with the motive A4 requires, and a dead posting is
//    named as such rather than lumped in with a refusal.
// ---------------------------------------------------------------------------
{
  assert.match(statusFromCheck(check({ reachable: false, kind: 'blocked', detail: 'HTTP 403 on x.example' })), /^Blocked — HTTP 403/);
  assert.match(statusFromCheck(check({ reachable: false, kind: 'gone', detail: 'HTTP 404 on x.example' })), /^Blocked — posting removed/);
}

// ---------------------------------------------------------------------------
// 4. Every status starts with one of A4's prefixes — `validate_rows` refuses
//    the row otherwise, so a new branch must not invent a vocabulary.
// ---------------------------------------------------------------------------
{
  const PREFIXES = ['Employer verified active', 'Portal verified', 'Legacy result', 'Blocked', 'To verify'];
  const shapes = [
    check(),
    check({ hasApply: false }),
    check({ title: '', hasInternSignal: false, hasApply: false }),
    check({ reachable: false, kind: 'blocked', detail: 'd' }),
    check({ reachable: false, kind: 'gone', detail: 'd' }),
    check({ reachable: false, kind: 'error', detail: 'd' }),
  ];
  for (const s of shapes) {
    const status = statusFromCheck(s);
    assert.ok(PREFIXES.some((p) => status.startsWith(p)), `not an A4 value: ${status}`);
    assert.ok(!status.includes('\t') && !status.includes('\n'), 'a status must not break its TSV cell');
  }
}

// ---------------------------------------------------------------------------
// 5. The URL list parser.
// ---------------------------------------------------------------------------
{
  const got = parseTargets(
    ['# a comment', '', 'Cefriel;https://a.example/1', 'Tabbed\thttps://b.example/2', 'https://c.example/3', 'not a url'].join('\n'),
  );
  assert.deepEqual(got, [
    { label: 'Cefriel', url: 'https://a.example/1' },
    { label: 'Tabbed', url: 'https://b.example/2' },
    { url: 'https://c.example/3' },
  ]);
}

// ---------------------------------------------------------------------------
// 6. End to end against a local server: parallel, paced by one limiter, and a
//    refusal stops the batch rather than being retried.
// ---------------------------------------------------------------------------
{
  let hits = 0;
  const srv = createServer((req, res) => {
    hits++;
    if (req.url === '/blocked') {
      res.writeHead(403);
      res.end('no');
      return;
    }
    if (req.url === '/empty') {
      res.writeHead(200, { 'content-type': 'text/html' });
      res.end('<html><head><title></title></head><body></body></html>');
      return;
    }
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<html><head><title>Stage Innovation Intern</title></head><body><a>Apply now</a></body></html>');
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${srv.address().port}`;

  const { results, report } = await runVerification(
    [
      { url: `${base}/a`, label: 'A' },
      { url: `${base}/b`, label: 'B' },
      { url: `${base}/empty`, label: 'Empty' },
    ],
    { ratePerSec: 500, width: 3 },
  );
  assert.equal(results.length, 3);
  assert.equal(results[0].status, 'Employer verified active');
  assert.equal(results[0].label, 'A', 'the caller label must be echoed back');
  assert.equal(results[1].status, 'Employer verified active', 'parallel width must not change the verdict');
  assert.match(results[2].status, /no readable content/);
  assert.equal(report.verifiedActive, 2);
  assert.equal(report.targets, 3);
  assert.ok(report.elapsedMs >= 0);

  // A 403 stops the batch: later targets drain without being sent.
  const before = hits;
  const stopped = await runVerification(
    [{ url: `${base}/blocked` }, { url: `${base}/a` }, { url: `${base}/b` }],
    { ratePerSec: 500, width: 1 },
  );
  assert.match(stopped.results[0].status, /^Blocked — HTTP 403/);
  assert.ok(stopped.results.at(-1).status.startsWith('Blocked'), 'drained targets report the stop, not a verdict');
  assert.ok(hits - before <= 1, `a stopped batch must not keep sending; server saw ${hits - before} more`);

  await new Promise((r) => srv.close(r));
}

console.log('verify-smoke: OK (A4 vocabulary, soft-404 vs JS shell, Blocked motives, URL list, parallel + stop)');
