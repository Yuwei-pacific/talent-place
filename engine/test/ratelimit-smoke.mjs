// node test/ratelimit-smoke.mjs — the limiter actually limits.
//
// Two assertions over the same run, testing two different properties:
//   * first gap  — no two requests leave together (instantaneous spacing)
//   * span       — the aggregate rate is respected over the whole batch
//
// Verified against the wrong implementations rather than assumed: with no
// limiter both fail (firstGap 0ms, span 0ms), and so does a token bucket that
// waits one gap when out of tokens (firstGap 0ms, span ~1 gap, because the
// waiters wait concurrently). So in these cases the two fire together. They are
// kept as a pair because they constrain different things — a limiter that
// spreads the batch correctly but lets the first two out in one tick fails
// only the first, and a limiter that spaces every pair correctly but drifts
// fast over a long batch fails only the second.
import { strict as assert } from 'node:assert';
import { RateLimiter, mulberry32 } from '../lib/ratelimit.js';

// ---------------------------------------------------------------------------
// Invariant 1: N callers in one tick get N slots spaced by the gap.
// ---------------------------------------------------------------------------
{
  const lim = new RateLimiter({ ratePerSec: 20, jitter: 0, random: () => 0 }); // 50ms gap
  const stamps = [];
  // Fire all 9 concurrently from the same tick — the naive implementation this
  // guards against is `await Promise.all(items.map(fn))` with no limiter at all.
  await Promise.all(
    Array.from({ length: 9 }, async () => {
      await lim.acquire();
      stamps.push(Date.now());
    }),
  );
  stamps.sort((a, b) => a - b);
  const firstGap = stamps[1] - stamps[0];
  const span = stamps.at(-1) - stamps[0];
  assert.ok(
    firstGap >= 40,
    `burst detected: first two requests left ${firstGap}ms apart, expected >=40ms. ` +
      `A token bucket with capacity N, or no limiter at all, fails here.`,
  );
  assert.ok(span >= 360, `expected >=360ms of spacing across 9 requests, got ${span}ms`);
}

// ---------------------------------------------------------------------------
// Invariant 2: jitter only ever ADDS to the gap. If it could subtract, the
// configured rate would be a suggestion and the mean would drift above it.
// ---------------------------------------------------------------------------
{
  const lim = new RateLimiter({ ratePerSec: 10, jitter: 0.5, random: () => 1 }); // max jitter
  const t0 = Date.now();
  await lim.acquire();
  await lim.acquire();
  const elapsed = Date.now() - t0;
  assert.ok(elapsed >= 140, `jitter must never shorten the gap; 10/s with max jitter gave ${elapsed}ms for 2 slots`);
}

// ---------------------------------------------------------------------------
// Invariant 3: penalize() only moves the horizon forward, so a Retry-After can
// never be undone by a later acquire().
// ---------------------------------------------------------------------------
{
  const lim = new RateLimiter({ ratePerSec: 100, jitter: 0, random: () => 0 }); // 10ms gap
  lim.penalize(300);
  const t0 = Date.now();
  await lim.acquire();
  const waited = Date.now() - t0;
  assert.ok(waited >= 250, `penalize(300) should have delayed the next acquire by ~300ms, got ${waited}ms`);
}

// ---------------------------------------------------------------------------
// Invariant 4: slowTo() slows but there is no way to speed back up within a
// run — the header of ratelimit.ts argues this is the whole point. If someone
// later adds a ramp, this test is where it should fail first.
// ---------------------------------------------------------------------------
{
  const lim = new RateLimiter({ ratePerSec: 50, jitter: 0, random: () => 0 });
  const before = lim.ratePerSec;
  lim.slowTo(10);
  assert.equal(lim.ratePerSec, 10, 'slowTo must take effect');
  lim.slowTo(1000); // larger rate == shorter gap == "faster"
  assert.equal(lim.ratePerSec, 10, 'slowTo must refuse to speed up; the rate only ever decreases within a run');
  assert.ok(before > lim.ratePerSec);
}

// ---------------------------------------------------------------------------
// Invariant 5: one limiter cannot stall another. This is a per-source property,
// and it is why run.ts builds a limiter per adapter rather than one shared.
// ---------------------------------------------------------------------------
{
  const slow = new RateLimiter({ ratePerSec: 2, jitter: 0, random: () => 0 }); // 500ms
  const fast = new RateLimiter({ ratePerSec: 100, jitter: 0, random: () => 0 }); // 10ms
  const t0 = Date.now();
  const slowJob = (async () => {
    await slow.acquire();
    await slow.acquire();
    return Date.now() - t0;
  })();
  const fastJob = (async () => {
    for (let i = 0; i < 5; i++) await fast.acquire();
    return Date.now() - t0;
  })();
  const [slowMs, fastMs] = await Promise.all([slowJob, fastJob]);
  assert.ok(fastMs < 300, `the fast source must not be held back by the slow one; took ${fastMs}ms`);
  assert.ok(slowMs >= 400, `the slow source must still be slow; took ${slowMs}ms`);
}

// ---------------------------------------------------------------------------
// Invariant 6: the seeded PRNG is deterministic, so timing tests can pin
// jitter rather than hope it averages out.
// ---------------------------------------------------------------------------
{
  const a = mulberry32(42);
  const b = mulberry32(42);
  const seqA = [a(), a(), a()];
  const seqB = [b(), b(), b()];
  assert.deepEqual(seqA, seqB, 'mulberry32 must be reproducible for a given seed');
  assert.ok(seqA.every((v) => v >= 0 && v < 1));
}

console.log('ratelimit-smoke: OK (spacing, first-gap burst guard, jitter direction, penalize, slow-only, per-source isolation)');
