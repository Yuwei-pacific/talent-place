// Politeness layer. One limiter per source.
//
// The rate is the ONLY politeness knob: it decides how often a request may
// leave. Anything that decides how MANY are outstanding (a worker pool) is a
// latency-hiding mechanism, not a throttle, and must never be used to set
// politeness. Keeping the two independent is what makes "we are being polite"
// a checkable claim rather than a vibe.
//
// ---------------------------------------------------------------------------
// There is deliberately NO rate ramp-up here, and that absence is load-bearing.
//
// A proposal circulated to start at 0.625 req/s and multiply by 1.5 every 20
// successes up to a 3 req/s ceiling. Two reasons it is not implemented:
//
//  1. The premise is false. This engine has no rate today — `fetchText` has no
//     delay and the adapters `await` serially, so at ~300ms p50 the LinkedIn
//     adapter already runs at ~3.3 req/s. The proposed ceiling sits BELOW the
//     current unthrottled behaviour, so the ramp would start ~5x slower than
//     things already run and accelerate back to roughly where they started.
//
//  2. It optimises the wrong thing. Multiplicative increase with multiplicative
//     decrease oscillates rather than converges — which is exactly why TCP uses
//     ADDITIVE increase with multiplicative decrease. Recovering a halving in
//     one 20-success window means the controller is rewarded for sitting at the
//     429 boundary and punished only briefly. A controller whose objective is
//     "maximise rate subject to not-yet-429" is optimising against the server
//     operator's intent even on runs where it never trips the alarm.
//
// What IS allowed is one-directional adaptivity the operator explicitly asked
// for: a 429 carrying `Retry-After`. That is a per-incident first-party
// instruction, not an inference from silence, and obeying it is MORE compliant
// than any static rate because a static rate ignores what the server just said.
// See `penalize()` and `fetchGuarded` in ./discovery/http.ts.
//
// So: the rate only ever goes down within a run, never up. If a future run
// needs to go faster, that is a policy decision to change a constant — not
// something the code should decide for itself.
// ---------------------------------------------------------------------------

export type Sleep = (ms: number) => Promise<void>;
export type Clock = () => number;

const realSleep: Sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export interface LimiterOptions {
  /** Requests per second. Must be > 0. */
  ratePerSec: number;
  /** Fraction of the gap to randomise, 0..1. Spreads bursts across runs without
   *  changing the mean rate. Default 0.25. */
  jitter?: number;
  /** Refuse to park more than this many waiters (backpressure, not throttling). */
  maxQueue?: number;
  /** Test seams. Production callers omit all three. */
  sleep?: Sleep;
  now?: Clock;
  random?: () => number;
}

export class QueueOverflowError extends Error {
  constructor(readonly queued: number) {
    super(`rate limiter queue full (${queued} waiting)`);
    this.name = 'QueueOverflowError';
  }
}

export class RateLimiter {
  private readonly sleep: Sleep;
  private readonly now: Clock;
  private readonly random: () => number;
  private readonly maxQueue: number;
  private gapMs: number;
  private jitter: number;
  /** Earliest wall-clock time the next request may leave. */
  private nextAt = 0;
  private waiting = 0;

  constructor(opts: LimiterOptions) {
    if (!(opts.ratePerSec > 0)) throw new RangeError(`ratePerSec must be > 0, got ${opts.ratePerSec}`);
    this.sleep = opts.sleep ?? realSleep;
    this.now = opts.now ?? Date.now;
    this.random = opts.random ?? Math.random;
    this.maxQueue = opts.maxQueue ?? 512;
    this.jitter = Math.max(0, Math.min(1, opts.jitter ?? 0.25));
    this.gapMs = 1000 / opts.ratePerSec;
  }

  /** The rate currently in force. Only ever decreases within a run. */
  get ratePerSec(): number {
    return 1000 / this.gapMs;
  }

  /** Waiters parked in acquire() right now. Observable so tests can assert the
   *  pool is not silently growing a queue behind a stopped source. */
  get queued(): number {
    return this.waiting;
  }

  /**
   * Reserve the next send slot.
   *
   * The reservation is SYNCHRONOUS — it happens before the first `await`. That
   * ordering is the whole design: N callers arriving in the same tick get N
   * distinct slots spaced by the current gap. Awaiting before reserving is the
   * bug that lets a pool of width N emit N requests simultaneously, which is
   * precisely the burst a guest API punishes.
   */
  async acquire(): Promise<void> {
    if (this.waiting >= this.maxQueue) throw new QueueOverflowError(this.waiting);
    const now = this.now();
    const at = Math.max(now, this.nextAt);
    // Jitter only ever ADDS to the gap, so the mean rate is a floor, never a
    // ceiling. A jitter that could subtract would let the limiter emit faster
    // than its configured rate.
    this.nextAt = at + this.gapMs * (1 + this.jitter * this.random());
    const wait = at - now;
    if (wait <= 0) return;
    this.waiting++;
    try {
      await this.sleep(wait);
    } finally {
      this.waiting--;
    }
  }

  /**
   * Push the horizon out by `ms`. This IS the backoff — there is no separate
   * retry timer, and no way for a penalty to be undone. Only ever moves the
   * horizon forward.
   */
  penalize(ms: number): void {
    const until = this.now() + ms;
    if (until > this.nextAt) this.nextAt = until;
  }

  /**
   * Slow down. Slots already handed out keep their old spacing; new ones use
   * the longer gap. There is intentionally no way to speed up — see the header.
   */
  slowTo(ratePerSec: number): void {
    if (!(ratePerSec > 0)) throw new RangeError(`ratePerSec must be > 0, got ${ratePerSec}`);
    const gap = 1000 / ratePerSec;
    if (gap > this.gapMs) {
      this.gapMs = gap;
      this.nextAt = Math.max(this.nextAt, this.now() + this.gapMs);
    }
  }
}

// ---------------------------------------------------------------------------
// Per-source stop state.
//
// Lives in the run's state, never in a module global: a module global leaks
// across runs and across tests, which is how "it passed yesterday" happens.
// ---------------------------------------------------------------------------

export type StopKind = 'none' | 'blocked' | 'error' | 'cap';

export interface StopToken {
  stopped: boolean;
  kind: StopKind;
  reason: string;
}

export function newStopToken(): StopToken {
  return { stopped: false, kind: 'none', reason: '' };
}

/** First reason wins — a later 'cap' never overwrites an earlier 'blocked',
 *  because the earlier one is the one a human needs to read. */
export function stopSource(t: StopToken, kind: StopKind, reason: string): void {
  if (t.stopped) return;
  t.stopped = true;
  t.kind = kind;
  t.reason = reason;
}

// ---------------------------------------------------------------------------
// Guard: what one source needs to be polite and stoppable.
//
// Lives here rather than in discovery/http.ts so this module stays a leaf —
// types.ts needs the Guard type, and types.ts must not import from discovery/.
// ---------------------------------------------------------------------------

/** Per-source counters. The run report is built from this, so a source that
 *  stopped can declare WHY in the terms A1/A4 ask for. */
export interface SourceHealth {
  requests: number;
  ok: number;
  blocked429: number;
  blocked403: number;
  gone: number;
  errors: number;
  /** Consecutive transport errors, reset by any success. */
  consecutiveErrors: number;
}

export function newSourceHealth(): SourceHealth {
  return { requests: 0, ok: 0, blocked429: 0, blocked403: 0, gone: 0, errors: 0, consecutiveErrors: 0 };
}

export interface Guard {
  limiter: RateLimiter;
  stop: StopToken;
  health: SourceHealth;
  /** Retries for ONE url after a 429. Default 2. */
  maxRetries?: number;
  /** Total 429s before the source stops. Default 5. */
  max429?: number;
  /** Consecutive transport errors before the source stops. Default 8. */
  maxConsecutiveErrors?: number;
  /** Test seam. */
  random?: () => number;
}

/** Full jitter (AWS): random(0, min(cap, base * 2^attempt)). */
export function backoffMs(attempt: number, random: () => number, baseMs = 1000, capMs = 8000): number {
  return Math.floor(random() * Math.min(capMs, baseMs * 2 ** attempt));
}

/** Deterministic 32-bit PRNG for tests. Zero deps, so timing tests can pin
 *  jitter instead of hoping it averages out. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
