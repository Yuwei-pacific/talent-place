// Employer-page verification — the cheap probe, run as a batch.
//
// Why this exists rather than "the agent opens a browser": on the 2026-09-17
// Strategic Design run, 15 roles were verified through a full headless browser
// at roughly 72s each (18 minutes). Re-probing the 9 employer pages that run
// had produced, with HEAD-style fetches and no JS, answered ALL 9 in 10.9s —
// about 1.2s each. The browser is the escalation, not the default.
//
// What this does NOT do, and must not be read as doing: it does not judge
// whether a role suits a student. It answers three mechanical questions — is
// the page alive, does it mention a stage, is there an apply path — and renders
// them into A4's closed `Verification Status` vocabulary. The judgement stays
// with the agent.
//
// Running it here rather than in a subagent is what makes it reproducible,
// countable (the run report) and polite (it shares the limiter).
import type { EmployerCheck } from './discovery/employer.js';
import { checkEmployerPage } from './discovery/employer.js';
import { RateLimiter, mapPool, newSourceHealth, newStopToken, type Guard, type SourceHealth } from './ratelimit.js';

export interface VerifyTarget {
  url: string;
  /** Free-form tag echoed back, so a caller can join on its own key. */
  label?: string;
}

export interface VerificationResult {
  url: string;
  label: string;
  /** A4 `Verification Status`: one of its prefixes, optionally `; <detail>`. */
  status: string;
  reachable: boolean;
  hasApply: boolean;
  hasInternSignal: boolean;
  title: string;
  detail: string;
  elapsedMs: number;
}

export interface VerifyOptions {
  ratePerSec?: number;
  width?: number;
  /** Test seam. */
  guardFor?: (limiter: RateLimiter) => Guard;
}

export interface VerifyReport {
  targets: number;
  verifiedActive: number;
  toVerify: number;
  blocked: number;
  elapsedMs: number;
  health: SourceHealth;
}

/**
 * Render a probe into A4's vocabulary.
 *
 * The mapping is not invented here — A4 defines `Employer verified active` as
 * "pagina aziendale/ATS aperta con candidatura visibile", which is exactly
 * `reachable && hasApply`, and requires a motive on every `Blocked`.
 *
 * Everything that is not "verified active" is stated as an open question rather
 * than as a negative: a page that loaded but showed no apply path may still be
 * a real posting behind a JS shell, and calling that "not active" would be a
 * judgement this probe has no standing to make.
 */
export function statusFromCheck(check: EmployerCheck): string {
  if (!check.reachable) {
    const why = check.kind === 'gone' ? `posting removed (${check.detail})` : check.detail;
    return `Blocked — ${why}`;
  }
  if (check.hasApply) return 'Employer verified active';

  // A page can be served with HTTP 200 and still be nothing. Measured, not
  // assumed: careers.kpmg.it answers a nonexistent job with a redirect to
  // `errorpage/?errortype=Exception`, status 200, an EMPTY <title>, and none of
  // the three signals. Reporting that as "apply path not visible" would file a
  // dead posting alongside a live one whose button is JS-rendered.
  //
  // Note the discriminator is all three being absent, not an empty title on its
  // own: avanade.com serves a 194KB page with real content and NO <title> at
  // all (Next.js sets it client-side), and it carries a working apply path.
  if (!check.title && !check.hasInternSignal) {
    return 'To verify — page returned no readable content (soft 404 or JS-rendered shell)';
  }
  return 'To verify — apply path not visible on the employer page (may be JS-rendered)';
}

export async function runVerification(
  targets: VerifyTarget[],
  opts: VerifyOptions = {},
): Promise<{ results: VerificationResult[]; report: VerifyReport }> {
  const t0 = Date.now();
  const limiter = new RateLimiter({ ratePerSec: opts.ratePerSec ?? 2 });
  const stop = newStopToken();
  const health = newSourceHealth();
  const guard: Guard = opts.guardFor?.(limiter) ?? { limiter, stop, health };

  const results = await mapPool(targets, opts.width ?? 4, async (t): Promise<VerificationResult> => {
    // A stopped source drains rather than sending: a refusal is not retried.
    if (stop.stopped) {
      return {
        url: t.url,
        label: t.label ?? '',
        status: `Blocked — ${stop.reason}`,
        reachable: false,
        hasApply: false,
        hasInternSignal: false,
        title: '',
        detail: stop.reason,
        elapsedMs: 0,
      };
    }
    const check = await checkEmployerPage(t.url, guard);
    return {
      url: t.url,
      label: t.label ?? '',
      status: statusFromCheck(check),
      reachable: check.reachable,
      hasApply: check.hasApply,
      hasInternSignal: check.hasInternSignal,
      title: check.title,
      detail: check.detail,
      elapsedMs: check.elapsedMs ?? 0,
    };
  });

  return {
    results,
    report: {
      targets: targets.length,
      verifiedActive: results.filter((r) => r.status.startsWith('Employer verified active')).length,
      toVerify: results.filter((r) => r.status.startsWith('To verify')).length,
      blocked: results.filter((r) => r.status.startsWith('Blocked')).length,
      elapsedMs: Date.now() - t0,
      health,
    },
  };
}

/** Parse a URL list: one per line, optionally `label;url` or `label<TAB>url`.
 *  Blank lines and `#` comments are ignored. */
export function parseTargets(text: string): VerifyTarget[] {
  const out: VerifyTarget[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const m = line.match(/^(.*?)[;\t]\s*(https?:\/\/\S+)$/);
    if (m) out.push({ label: m[1].trim(), url: m[2].trim() });
    else if (/^https?:\/\//.test(line)) out.push({ url: line });
  }
  return out;
}
