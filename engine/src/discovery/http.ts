// L0 transport: plain HTTP fetch with a normal browser UA, no auth, no cookies.
// A1 rule: never bypass login/CAPTCHA/rate limits — those classify as 'blocked'
// and the ladder moves on to other sources (L2 declares it, never sneaks past).
import type { Guard } from '../ratelimit.js';
import { backoffMs, stopSource } from '../ratelimit.js';
export type FetchOutcome =
  | { ok: true; status: number; text: string }
  | {
      ok: false;
      kind: 'blocked' | 'gone' | 'error';
      /**
       * The HTTP status, when there was one. Carried so callers can tell a 429
       * ("slow down" — retryable, and the operator is talking to us) from a 403
       * ("not for you" — retrying is circumvention). Both collapse into
       * `kind: 'blocked'`, and the retry policy differs, so the distinction has
       * to survive the transport boundary. Driving that decision by parsing the
       * human-readable `detail` string is not a design.
       */
      status?: number;
      /** `Retry-After` in ms, when the server sent one in a form we understand. */
      retryAfterMs?: number;
      detail: string;
    };

const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';

// Challenge markers must be interstitial-specific, NOT substrings that also
// occur in legit pages: 'captcha' matches grecaptcha-badge CSS on every Ashby
// board; 'enable javascript to' matches the <noscript> on every JS-shell
// career page (Ashby, Workday). False 'blocked' here kills the whole employer
// branch, so keep the list narrow.
const BLOCKED_MARKERS = [
  'cf-challenge',
  'challenge-platform',
  'unusual traffic',
  'access denied',
  'request blocked',
  'just a moment...', // Cloudflare interstitial title (with ellipsis)
  'verifying you are human', // Cloudflare/DDoS-Guard interstitial
];

export async function fetchText(url: string, timeoutMs = 20000): Promise<FetchOutcome> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers: { 'User-Agent': UA, Accept: 'text/html,application/json;q=0.9,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.9,it;q=0.8' },
    });
    if (res.status === 403 || res.status === 429) {
      return {
        ok: false,
        kind: 'blocked',
        status: res.status,
        retryAfterMs: parseRetryAfter(res.headers.get('retry-after')),
        detail: `HTTP ${res.status} on ${hostOf(url)}`,
      };
    }
    if (res.status === 404 || res.status === 410) {
      return { ok: false, kind: 'gone', status: res.status, detail: `HTTP ${res.status} on ${url}` };
    }
    if (!res.ok) return { ok: false, kind: 'error', status: res.status, detail: `HTTP ${res.status} on ${url}` };
    const text = await res.text();
    const lower = text.slice(0, 20000).toLowerCase();
    if (BLOCKED_MARKERS.some((m) => lower.includes(m))) {
      return { ok: false, kind: 'blocked', detail: `challenge/login wall on ${hostOf(url)}` };
    }
    return { ok: true, status: res.status, text };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (/abort/i.test(msg)) return { ok: false, kind: 'error', detail: `timeout ${timeoutMs}ms on ${url}` };
    return { ok: false, kind: 'error', detail: `${msg} on ${url}` };
  } finally {
    clearTimeout(timer);
  }
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * `Retry-After` is either delta-seconds or an HTTP-date. Returns ms, or
 * undefined when absent/unparseable — an unparseable value is not a licence to
 * guess, it just means we fall back to jittered backoff.
 */
export function parseRetryAfter(header: string | null, now = Date.now()): number | undefined {
  if (!header) return undefined;
  const v = header.trim();
  if (/^\d+$/.test(v)) return Number(v) * 1000;
  const at = Date.parse(v);
  if (Number.isNaN(at)) return undefined;
  return Math.max(0, at - now);
}

// ---------------------------------------------------------------------------
// Guarded fetch: the retry policy lives here, not in the adapters.
//
// Every adapter would otherwise re-derive "is this worth retrying", and the
// four of them already disagree (three swallow everything, one throws).
// ---------------------------------------------------------------------------

/**
 * Fetch one URL under a guard.
 *
 * Never rejects — a refusal is a result to be declared, not an exception that
 * takes the run down with it. That is the whole difference between this and the
 * `throw` that used to live in linkedin-guest.
 */
export async function fetchGuarded(url: string, g: Guard, timeoutMs = 20000): Promise<FetchOutcome> {
  const maxRetries = g.maxRetries ?? 2;
  const max429 = g.max429 ?? 5;
  const maxErrors = g.maxConsecutiveErrors ?? 8;
  const random = g.random ?? Math.random;

  for (let attempt = 0; ; attempt++) {
    if (g.stop.stopped) {
      // Draining: the source is already stopped, so this request is never sent.
      return { ok: false, kind: 'error', detail: `source stopped: ${g.stop.reason}` };
    }
    await g.limiter.acquire();
    g.health.requests++;
    const res = await fetchText(url, timeoutMs);

    if (res.ok) {
      g.health.ok++;
      g.health.consecutiveErrors = 0;
      return res;
    }

    if (res.kind === 'gone') {
      g.health.gone++;
      return res; // a dead posting is never a reason to stop the source
    }

    if (res.kind === 'error') {
      g.health.errors++;
      g.health.consecutiveErrors++;
      if (g.health.consecutiveErrors >= maxErrors) {
        stopSource(g.stop, 'error', `${maxErrors} consecutive transport errors on ${hostOf(url)}`);
      }
      return res;
    }

    // kind === 'blocked'
    if (res.status === 429) {
      g.health.blocked429++;
      // Retry-After is the operator's own instruction — obey it verbatim. It is
      // the only adaptivity this engine allows, and it can only slow us down.
      const wait = res.retryAfterMs ?? backoffMs(attempt, random);
      g.limiter.penalize(wait);
      if (g.health.blocked429 >= max429) {
        stopSource(g.stop, 'blocked', `${g.health.blocked429} x HTTP 429 on ${hostOf(url)}`);
        return res;
      }
      if (attempt < maxRetries) continue;
      return res; // gave up on this URL; the source continues at the slower rate
    }

    // 403, or a challenge interstitial: the server declined. A1 says we do not
    // retry our way past a refusal.
    g.health.blocked403++;
    stopSource(g.stop, 'blocked', res.detail);
    return res;
  }
}
