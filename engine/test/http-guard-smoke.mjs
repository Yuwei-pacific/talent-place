// node test/http-guard-smoke.mjs — 429 vs 403, and the policy that separates them.
//
// Uses a real `node:http` server on 127.0.0.1 rather than a fixture file or a
// mocked global fetch, so this exercises the genuine classification path in
// discovery/http.ts — including the `status` field that did not exist before
// and without which the retry decision was undecidable at the adapter layer.
import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import { fetchText, fetchGuarded, parseRetryAfter } from '../lib/discovery/http.js';
import { RateLimiter, newSourceHealth, newStopToken } from '../lib/ratelimit.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Start a one-shot-ish server; returns { url, hits, close }. */
async function serve(handler) {
  let hits = 0;
  const srv = createServer((req, res) => {
    hits++;
    handler(req, res, hits);
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  return {
    url: `http://127.0.0.1:${srv.address().port}`,
    get hits() {
      return hits;
    },
    close: () => new Promise((r) => srv.close(r)),
  };
}

function guard(overrides = {}) {
  const limiter = new RateLimiter({ ratePerSec: 100, jitter: 0, random: () => 0 });
  const stop = newStopToken();
  const health = newSourceHealth();
  return { limiter, stop, health, random: () => 1, ...overrides };
}

// ---------------------------------------------------------------------------
// 1. parseRetryAfter handles both forms and refuses to guess.
// ---------------------------------------------------------------------------
{
  assert.equal(parseRetryAfter('2'), 2000, 'delta-seconds');
  assert.equal(parseRetryAfter('  0 '), 0, 'zero is a real instruction');
  assert.equal(parseRetryAfter(null), undefined, 'absent');
  assert.equal(parseRetryAfter('soon'), undefined, 'unparseable must not be guessed at');
  const future = new Date(Date.now() + 5000).toUTCString();
  const ms = parseRetryAfter(future);
  assert.ok(ms > 3000 && ms <= 5000, `HTTP-date form, got ${ms}`);
  const past = new Date(Date.now() - 5000).toUTCString();
  assert.equal(parseRetryAfter(past), 0, 'a past date means "now", never negative');
}

// ---------------------------------------------------------------------------
// 2. A 429 must carry its status out of the transport.
//    FAILS TODAY: `status` does not exist on the non-ok outcome, so a caller
//    can only tell a 429 from a 403 by parsing the human-readable detail.
// ---------------------------------------------------------------------------
{
  const s = await serve((_req, res) => {
    res.writeHead(429, { 'Retry-After': '3' });
    res.end('slow down');
  });
  const res = await fetchText(s.url + '/jobs');
  assert.equal(res.ok, false);
  assert.equal(res.status, 429, 'the transport must carry the HTTP status');
  assert.equal(res.retryAfterMs, 3000, 'and the Retry-After it came with');
  await s.close();
}

// ---------------------------------------------------------------------------
// 3. 429 is retryable and Retry-After is obeyed verbatim.
// ---------------------------------------------------------------------------
{
  const s = await serve((_req, res, n) => {
    if (n <= 2) {
      res.writeHead(429, { 'Retry-After': '1' });
      res.end('slow down');
      return;
    }
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<h3 class="base-search-card__title">Intern</h3>');
  });
  const g = guard();
  const t0 = Date.now();
  const res = await fetchGuarded(s.url + '/jobs', g);
  const elapsed = Date.now() - t0;
  assert.equal(res.ok, true, 'a 429 is transient — it must be retried');
  assert.equal(s.hits, 3, `expected 2 x 429 then success, server saw ${s.hits} requests`);
  assert.ok(elapsed >= 1800, `Retry-After: 1 twice must cost ~2s, took ${elapsed}ms`);
  assert.equal(g.stop.stopped, false, 'two 429s are not a reason to stop the source');
  assert.equal(g.health.blocked429, 2);
  await s.close();
}

// ---------------------------------------------------------------------------
// 4. 403 is NOT retryable: retrying past a refusal is circumvention (A1).
// ---------------------------------------------------------------------------
{
  const s = await serve((_req, res) => {
    res.writeHead(403);
    res.end('no');
  });
  const g = guard();
  const res = await fetchGuarded(s.url + '/jobs', g);
  assert.equal(res.ok, false);
  assert.equal(res.status, 403);
  assert.equal(g.stop.stopped, true, 'a 403 must stop the source');
  assert.equal(g.stop.kind, 'blocked');
  assert.equal(s.hits, 1, `a 403 must not be retried; server saw ${s.hits} requests`);

  // Draining: later calls return without sending anything.
  const before = s.hits;
  await fetchGuarded(s.url + '/jobs', g);
  await fetchGuarded(s.url + '/other', g);
  await sleep(150);
  assert.equal(s.hits, before, `a stopped source must not keep sending; saw ${s.hits - before} more requests`);
  await s.close();
}

// ---------------------------------------------------------------------------
// 5. Too many 429s stops the source rather than looping forever.
// ---------------------------------------------------------------------------
{
  const s = await serve((_req, res) => {
    res.writeHead(429, { 'Retry-After': '0' });
    res.end('slow down');
  });
  const g = guard({ max429: 3, maxRetries: 0 });
  for (let i = 0; i < 6 && !g.stop.stopped; i++) await fetchGuarded(s.url + '/jobs', g);
  assert.equal(g.stop.stopped, true, 'a source that keeps 429ing must eventually stop');
  assert.equal(g.stop.kind, 'blocked');
  assert.ok(/429/.test(g.stop.reason), `the reason must name the cause, got ${JSON.stringify(g.stop.reason)}`);
  await s.close();
}

// ---------------------------------------------------------------------------
// 6. A 404 is never a reason to stop the source — the posting is just gone.
// ---------------------------------------------------------------------------
{
  const s = await serve((_req, res) => {
    res.writeHead(404);
    res.end('gone');
  });
  const g = guard();
  const res = await fetchGuarded(s.url + '/jobs', g);
  assert.equal(res.ok, false);
  assert.equal(res.kind, 'gone');
  assert.equal(g.stop.stopped, false, 'a dead posting must not take the source down');
  assert.equal(g.stop.kind, 'none');
  await s.close();
}

// ---------------------------------------------------------------------------
// 7. Consecutive transport errors stop the source; a success resets the count.
// ---------------------------------------------------------------------------
{
  let mode = 'fail';
  const s = await serve((_req, res) => {
    if (mode === 'fail') {
      res.destroy();
      return;
    }
    res.writeHead(200);
    res.end('ok');
  });
  const g = guard({ maxConsecutiveErrors: 2 });
  await fetchGuarded(s.url + '/a', g);
  assert.equal(g.health.consecutiveErrors, 1);
  mode = 'ok';
  const okRes = await fetchGuarded(s.url + '/b', g);
  assert.equal(okRes.ok, true);
  assert.equal(g.health.consecutiveErrors, 0, 'a success must reset the consecutive-error count');
  mode = 'fail';
  await fetchGuarded(s.url + '/c', g);
  await fetchGuarded(s.url + '/d', g);
  assert.equal(g.stop.stopped, true, '2 consecutive transport errors must stop the source');
  assert.equal(g.stop.kind, 'error');
  await s.close();
}

console.log('http-guard-smoke: OK (status carried, Retry-After obeyed, 429 retryable, 403 stops, 404 tolerated, error circuit)');
