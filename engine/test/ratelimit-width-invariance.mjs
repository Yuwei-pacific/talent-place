// node test/ratelimit-width-invariance.mjs — width is not a rate.
//
// The whole point of separating the limiter from the pool is that changing how
// many requests are in flight must not change how often one leaves. If that
// separation breaks — the classic way is `await` BEFORE reserving a slot, so N
// workers all read the same `nextAt` — the workload finishes dramatically
// faster and looks like an optimisation. It is not: it is the same run being
// less polite, and nothing else in the suite would notice.
import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import { RateLimiter, mapPool } from '../lib/ratelimit.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// 1. The same work under the same limiter, at width 1 and at width 9.
//    Both must be limiter-bound, so both take the same time.
// ---------------------------------------------------------------------------
{
  const items = Array.from({ length: 9 }, (_, i) => i);
  const run = async (width) => {
    const lim = new RateLimiter({ ratePerSec: 20, jitter: 0, random: () => 0 }); // 50ms gap
    const stamps = [];
    await mapPool(items, width, async () => {
      await lim.acquire();
      stamps.push(Date.now());
    });
    stamps.sort((a, b) => a - b);
    return { span: stamps.at(-1) - stamps[0], firstGap: stamps[1] - stamps[0], stamps };
  };

  const serial = await run(1);
  const pooled = await run(9);

  // 8 gaps x 50ms = 400ms of spacing, asserted with margin.
  assert.ok(serial.span >= 360, `width 1 should take ~400ms, took ${serial.span}ms`);
  assert.ok(
    pooled.span >= 360,
    `width 9 must NOT beat the limiter: expected ~400ms, took ${pooled.span}ms. ` +
      `If this is near zero, the pool is emitting in parallel and the limiter has stopped being the pacing knob.`,
  );

  // And the two must agree, because width is not supposed to change anything.
  const ratio = pooled.span / serial.span;
  assert.ok(
    ratio > 0.5 && ratio < 2,
    `width must not change the achieved rate: width1=${serial.span}ms width9=${pooled.span}ms (ratio ${ratio.toFixed(2)})`,
  );

  // No burst at either width: no two requests left together.
  assert.ok(serial.firstGap >= 40, `width 1 burst: first gap ${serial.firstGap}ms`);
  assert.ok(pooled.firstGap >= 40, `width 9 burst: first gap ${pooled.firstGap}ms`);
}

// ---------------------------------------------------------------------------
// 2. mapPool never exceeds its width, and preserves input order.
//    Order matters downstream: a nondeterministic card order makes every diff
//    of a run's output unreadable.
// ---------------------------------------------------------------------------
{
  let live = 0;
  let peak = 0;
  const out = await mapPool([1, 2, 3, 4, 5, 6, 7, 8], 3, async (n) => {
    live++;
    peak = Math.max(peak, live);
    await sleep(5);
    live--;
    return n * 10;
  });
  assert.equal(peak, 3, `mapPool ran ${peak} jobs at once with width 3`);
  assert.deepEqual(out, [10, 20, 30, 40, 50, 60, 70, 80], 'results must come back in input order');

  // Degenerate cases.
  assert.deepEqual(await mapPool([], 4, async () => 1), []);
  assert.deepEqual(await mapPool([1, 2], 0, async (n) => n), [1, 2], 'width 0 must not deadlock');
}

// ---------------------------------------------------------------------------
// 3. End to end, against a real server: pooling the fetches must not raise the
//    request rate the server sees. This is the assertion the whole design
//    exists to satisfy, so it is checked against real sockets, not a stub.
// ---------------------------------------------------------------------------
{
  let hits = 0;
  const srv = createServer((_req, res) => {
    hits++;
    // A small server-side delay, so a naive `Promise.all` would visibly win.
    setTimeout(() => {
      res.writeHead(200, { 'content-type': 'text/plain' });
      res.end('ok');
    }, 30);
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${srv.address().port}`;

  const measure = async (width) => {
    const lim = new RateLimiter({ ratePerSec: 10, jitter: 0, random: () => 0 }); // 100ms gap
    const t0 = Date.now();
    await mapPool(Array.from({ length: 8 }, (_, i) => i), width, async (i) => {
      await lim.acquire();
      await fetch(`${base}/j/${i}`);
    });
    return Date.now() - t0;
  };

  const w1 = await measure(1);
  const hitsAfterFirst = hits;
  const w8 = await measure(8);

  assert.equal(hits, 16, `server should have seen 16 requests, saw ${hits}`);
  assert.equal(hitsAfterFirst, 8);
  // 7 gaps x 100ms = 700ms. Both widths must be limiter-bound.
  assert.ok(w1 >= 620, `width 1: expected ~700ms, got ${w1}ms`);
  assert.ok(
    w8 >= 620,
    `width 8: expected ~700ms, got ${w8}ms — the server would have seen 8 requests at once, ` +
      `which is the burst the limiter exists to prevent`,
  );
  await new Promise((r) => srv.close(r));
}

console.log('ratelimit-width-invariance: OK (width 1 == width 9, no burst, order preserved, real-socket rate unchanged)');
