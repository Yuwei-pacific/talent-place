// node test/unattended-smoke.mjs — a run nobody is watching.
//
// LinkedIn began answering 429 after about 20 requests in late October, and a run
// stopped there left its later queries unsent until somebody came back to restart
// it. These are the properties that let a run wait instead, without ever pushing
// past what the server said.
import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { linkedinGuestAdapter } from '../lib/discovery/linkedin-guest.js';
import { RateLimiter, newCooldown, newSourceHealth, newStopToken } from '../lib/ratelimit.js';

const card = (id) => `
<li>
  <div data-entity-urn="urn:li:jobPosting:${id}"></div>
  <h3 class="base-search-card__title">Role ${id} Intern</h3>
  <a class="base-search-card__subtitle" href="/co">Co ${id}</a>
  <span class="job-search-card__location">Milan, Italy</span>
  <a class="base-card__full-link" href="https://it.linkedin.com/jobs/view/role-${id}-at-co-${id}?position=1">go</a>
  <time>2 days ago</time>
</li>`;

/** `script(n, url)` answers request number n with a status, or a [status, body]. */
async function serve(script) {
  const seen = [];
  const srv = createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    seen.push({ at: Date.now(), url });
    const out = script(seen.length, url);
    const [status, body] = Array.isArray(out) ? out : [out, status2body(out, seen.length)];
    res.writeHead(status, { 'content-type': 'text/html' });
    res.end(body);
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  return {
    seen,
    base: `http://127.0.0.1:${srv.address().port}`,
    close: () => new Promise((r) => srv.close(r)),
  };
}
const status2body = (status, n) => (status === 200 ? card(1000 + n) : 'no');

const guardWith = (cooldown) => {
  const stop = newStopToken();
  return {
    limiter: new RateLimiter({ ratePerSec: 1000, jitter: 0, random: () => 0 }),
    stop,
    health: newSourceHealth(),
    random: () => 0,
    ...(cooldown ? { cooldown } : {}),
  };
};
const run = (adapter, queries, guard) => adapter.discover(queries, { guard, stop: guard.stop, cap: 5000 });
const QUERIES = ['a', 'b', 'c', 'd', 'e', 'f'];

// The server filters by age, so a request stops paying for roles the run would
// discard anyway. On 2026-11-02, 48 of 109 cards in one batch were older than the
// 7 days the run wanted.
{
  const s = await serve(() => 200);
  await run(linkedinGuestAdapter(['Italy'], { baseUrl: s.base, width: 1, recencyDays: 7 }), ['a'], guardWith());
  assert.equal(s.seen[0].url.searchParams.get('f_TPR'), 'r604800', 'seven days is LinkedIn\'s r604800');
  await run(linkedinGuestAdapter(['Italy'], { baseUrl: s.base, width: 1 }), ['a'], guardWith());
  assert.equal(s.seen[1].url.searchParams.has('f_TPR'), false, 'no recency means no filter');
  await s.close();
  assert.throws(() => linkedinGuestAdapter(['Italy'], { recencyDays: 0 }), RangeError, 'a recency of 0 is a typo, not a filter');
}

// Waiting instead of stopping: nothing is lost, and the wait really happens.
{
  const s = await serve((n) => (n >= 3 && n <= 7 ? 429 : 200));
  const guard = guardWith(newCooldown(60, 3));
  const cards = await run(linkedinGuestAdapter(['Italy'], { baseUrl: s.base, width: 1 }), QUERIES, guard);
  assert.equal(guard.stop.stopped, false, 'a cooldown is not a stop');
  assert.equal(guard.health.cooldowns, 1);
  assert.equal(guard.health.blocked429, 5, 'every 429 stays in the report, including those before the wait');
  assert.equal(new Set(cards.map((c) => c.discoveryQuery)).size, QUERIES.length, 'no query may be lost to the block');
  assert.ok(s.seen[7].at - s.seen[6].at >= 50, `the request after the fifth 429 must wait: ${s.seen[7].at - s.seen[6].at}ms`);
  assert.equal(guard.health.events429.length, 5, 'when each 429 came is what the 2026-11-02 run could not answer');
  assert.ok(!Number.isNaN(Date.parse(guard.health.events429[0])), 'events are timestamps');
  await s.close();
}

// A wait that buys nothing is a block, and pressing on would be the pushing A1 forbids.
{
  const s = await serve((n) => (n === 1 ? 200 : 429));
  const guard = guardWith(newCooldown(20, 10));
  await run(linkedinGuestAdapter(['Italy'], { baseUrl: s.base, width: 1 }), QUERIES, guard);
  assert.equal(guard.stop.kind, 'blocked');
  assert.match(guard.stop.reason, /no success/, 'the report must say why it gave up');
  assert.equal(guard.health.cooldowns, 1);
  assert.equal(s.seen.length, 11, '1 success, 5 x 429, one wait, 5 x 429, then nothing more');
  await s.close();
}

// The budget of waits is a hard end, whatever happens in between.
{
  const s = await serve((n) => ((n - 1) % 6 === 0 ? 200 : 429));
  const guard = guardWith(newCooldown(5, 2));
  await run(linkedinGuestAdapter(['Italy'], { baseUrl: s.base, width: 1 }), QUERIES, guard);
  assert.equal(guard.stop.kind, 'blocked');
  assert.equal(guard.health.cooldowns, 2);
  assert.match(guard.stop.reason, /2 cooldowns/);
  await s.close();
}

// A 403 is "not for you", and no amount of waiting makes it otherwise.
{
  const s = await serve((n) => (n === 2 ? 403 : 200));
  const guard = guardWith(newCooldown(5, 5));
  await run(linkedinGuestAdapter(['Italy'], { baseUrl: s.base, width: 1 }), QUERIES, guard);
  assert.equal(guard.stop.kind, 'blocked');
  assert.equal(guard.health.cooldowns, 0);
  assert.equal(s.seen.length, 2, 'nothing is sent after a 403');
  await s.close();
}

// Without a cooldown the old stop is untouched: 5 x 429 and the source ends.
{
  const s = await serve(() => 429);
  const guard = guardWith();
  await run(linkedinGuestAdapter(['Italy'], { baseUrl: s.base, width: 1 }), QUERIES, guard);
  assert.match(guard.stop.reason, /5 x HTTP 429/);
  assert.equal(s.seen.length, 5);
  await s.close();
}

const dir = mkdtempSync(join(tmpdir(), 'unattended-'));
try {
  // A process can die in hour two. What it already paid for must survive it.
  const path = join(dir, 'checkpoint.jsonl');
  const s = await serve((n, url) => (url.searchParams.get('keywords') === 'c' ? 403 : 200));
  const opts = { baseUrl: s.base, width: 1, checkpoint: path };
  const first = await run(linkedinGuestAdapter(['Italy'], opts), ['a', 'b', 'c', 'd'], guardWith());
  assert.equal(first.length, 2);
  const sent = s.seen.length;
  writeFileSync(path, readFileSync(path, 'utf-8') + '{"key":"half a li', { flag: 'w' });
  const s2 = await serve(() => 200);
  const second = await run(linkedinGuestAdapter(['Italy'], { ...opts, baseUrl: s2.base }), ['a', 'b', 'c', 'd'], guardWith());
  assert.deepEqual(s2.seen.map((x) => x.url.searchParams.get('keywords')), ['c', 'd'], 'finished pairs are not asked for again');
  assert.deepEqual(second.map((c) => c.discoveryQuery.split(' — ')[0]), ['a', 'b', 'c', 'd'], 'results keep input order, and a torn last line is ignored');
  assert.equal(sent, 3);
  await s.close();
  await s2.close();

  // Reading a posting is the same budget on the same host, so it waits the same way.
  const cards = [
    { title: 'One', company: 'A', location: 'Milan', url: 'u1', sourceJobId: '1' },
    { title: 'Two', company: 'B', location: 'Milan', url: 'u2', sourceJobId: '2' },
    { title: 'Gone', company: 'C', location: 'Milan', url: 'u3', sourceJobId: '3' },
    { title: 'No id', company: 'D', location: 'Milan', url: 'u4' },
    { title: 'Past the top', company: 'E', location: 'Milan', url: 'u5', sourceJobId: '5' },
  ];
  const cardsPath = join(dir, 'cards.json');
  writeFileSync(cardsPath, JSON.stringify(cards));
  const out = join(dir, 'read');
  const posting = (t, closed = '') =>
    `<div class="show-more-less-html__markup">${t}<br/>&amp; more</div>${closed}`;
  const r1 = await serve((n, url) => {
    if (url.pathname.endsWith('/1')) return [200, posting('First role', 'No longer accepting applications')];
    if (url.pathname.endsWith('/3')) return [404, 'gone'];
    return n <= 6 ? [429, 'no'] : [200, posting('Second role')];
  });
  const read = (base) =>
    runCli(['lib/cli.js', 'read', '--cards', cardsPath, '--out', out, '--top', '4', '--rate', '1000', '--cooldown-seconds', '0.05', '--max-cooldowns', '3', '--linkedin-base', base]);
  const res = await read(r1.base);
  assert.equal(res.status, 0, res.stderr);
  const got = JSON.parse(readFileSync(join(out, 'descriptions.json'), 'utf-8'));
  const by = Object.fromEntries(got.map((d) => [d.sourceJobId, d]));
  assert.equal(by['1'].desc, 'First role\n& more', 'text comes from the description block, entities decoded');
  assert.equal(by['1'].closedOnPage, true);
  assert.ok(by['2'].desc.startsWith('Second role'), 'a role behind a 429 is read after the wait');
  assert.equal(by['3'].http, 404);
  assert.equal(by['5'], undefined, '--top limits the budget');
  const report = JSON.parse(readFileSync(join(out, 'read-report.json'), 'utf-8'));
  assert.equal(report.read, 2);
  assert.equal(report.withoutId, 1, 'a card with no id is counted, not silently skipped');
  assert.equal(report.health.cooldowns, 1);
  await r1.close();
  const r2 = await serve(() => [200, posting('Should not be fetched')]);
  assert.equal((await read(r2.base)).status, 0);
  assert.equal(r2.seen.length, 0, 'a second run asks only for what it does not have');
  await r2.close();

  // A 200 with no posting in it is not a read: a sign-in wall must not look like success.
  const threeCards = join(dir, 'three.json');
  writeFileSync(threeCards, JSON.stringify(['7', '8', '9'].map((id) => ({ ...cards[0], sourceJobId: id }))));
  const readThree = (base, to) =>
    runCli(['lib/cli.js', 'read', '--cards', threeCards, '--out', join(dir, to), '--rate', '1000', '--linkedin-base', base]);
  const wall = await serve(() => [200, '<html>sign in to continue</html>']);
  const walled = await readThree(wall.base, 'wall');
  assert.equal(walled.status, 0, walled.stderr);
  assert.match(walled.stdout, /read 0 new, 3 empty/);
  const wallReport = JSON.parse(readFileSync(join(dir, 'wall', 'read-report.json'), 'utf-8'));
  assert.equal(wallReport.read, 0);
  assert.equal(wallReport.empty, 3);
  await readThree(wall.base, 'wall');
  assert.equal(wall.seen.length, 6, 'an empty page is asked for again on the next run');
  await wall.close();

  // A posting that is gone stays gone, whichever of the two statuses said so.
  const gone = await serve(() => [410, 'gone']);
  await readThree(gone.base, 'gone');
  await readThree(gone.base, 'gone');
  assert.equal(gone.seen.length, 3, 'a 410 is not asked for twice');
  await gone.close();

  // The CLI: config reaches the source, and an old checkpoint is never picked up by accident.
  const cfgPath = join(dir, 'run.json');
  const runDir = join(dir, 'run');
  writeFileSync(cfgPath, JSON.stringify({
    masterId: 'm', edition: 'E', areas: { One: ['x'] }, internshipTerms: ['stage'], locations: ['Italy'],
    falseFriends: [], topK: 10, recencyDays: 7, cooldownMinutes: 0.001, maxCooldowns: 3, rates: { 'linkedin-guest': 1000 },
  }));
  const c = await serve((n) => (n <= 5 ? 429 : 200));
  const discover = (...more) => runCli(['lib/cli.js', 'discover', '--config', cfgPath, '--out', runDir, '--linkedin-base', c.base, ...more]);
  const d1 = await discover();
  assert.equal(d1.status, 0, d1.stderr);
  assert.equal(c.seen.at(-1).url.searchParams.get('f_TPR'), 'r604800');
  const rep = JSON.parse(readFileSync(join(runDir, 'run-report.json'), 'utf-8'));
  assert.equal(rep.sources[0].status, 'ok');
  assert.equal(rep.sources[0].health.cooldowns, 1);
  assert.ok(existsSync(join(runDir, 'checkpoint.jsonl')));
  const d2 = await discover();
  assert.equal(d2.status, 2, 'reusing a run directory by accident must not mix two runs');
  assert.match(d2.stderr, /--resume/);
  const before = c.seen.length;
  const d3 = await discover('--resume');
  assert.equal(d3.status, 0, d3.stderr);
  assert.equal(c.seen.length, before, 'everything was already done');
  assert.match(d3.stdout, /cards\s+1 seen/, 'restored cards still go through the pipeline');
  await c.close();
} finally {
  rmSync(dir, { recursive: true, force: true });
}

function runCli(args) {
  return new Promise((resolve) => {
    const p = spawn(process.execPath, args, { cwd: fileURLToPath(new URL('..', import.meta.url)) });
    let stdout = '';
    let stderr = '';
    p.stdout.on('data', (d) => (stdout += d));
    p.stderr.on('data', (d) => (stderr += d));
    p.on('close', (status) => resolve({ status, stdout, stderr }));
  });
}

console.log('unattended-smoke: OK (recency filter, cooldown keeps every query, no-progress stop, wait budget, 403 stops, checkpoint resume, read resumes, CLI refuses a stale checkpoint)');
