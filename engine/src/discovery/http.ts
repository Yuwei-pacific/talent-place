// L0 transport: plain HTTP fetch with a normal browser UA, no auth, no cookies.
// A1 rule: never bypass login/CAPTCHA/rate limits — those classify as 'blocked'
// and the ladder moves on to other sources (L2 declares it, never sneaks past).
export type FetchOutcome =
  | { ok: true; status: number; text: string }
  | { ok: false; kind: 'blocked' | 'gone' | 'error'; detail: string };

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
      return { ok: false, kind: 'blocked', detail: `HTTP ${res.status} on ${hostOf(url)}` };
    }
    if (res.status === 404 || res.status === 410) {
      return { ok: false, kind: 'gone', detail: `HTTP ${res.status} on ${url}` };
    }
    if (!res.ok) return { ok: false, kind: 'error', detail: `HTTP ${res.status} on ${url}` };
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

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
