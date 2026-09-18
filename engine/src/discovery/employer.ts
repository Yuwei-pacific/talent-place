// L0 employer branch, layer 1+3: Ashby public posting API + generic
// employer-page fetch. No auth anywhere.
//
// - Ashby: GET https://api.ashbyhq.com/posting-api/job-board/<board>
//   (undocumented public endpoint backing jobs.ashbyhq.com/<board>; probed
//   2026-09-10, returns {jobs:[{id,title,location,employmentType,isListed,
//   jobUrl,...}]}). employmentType "Intern" is the intern signal.
// - Generic employer page: fetchText + intern-signal scan + apply-link
//   extraction. Used for verify-first (A1: employer preferred) and for
//   unknown ATS / self-built career pages (layer 3).
import type { Card } from '../types.js';
import type { Guard } from '../ratelimit.js';
import { fetchGuarded, fetchText } from './http.js';

const INTERN_HINT = /\b(intern|internship|stage|stagista|tirocinio|tirocinante|working student|curricular)\b/i;

export async function ashbyBoard(board: string, company: string): Promise<Card[]> {
  const res = await fetchText(`https://api.ashbyhq.com/posting-api/job-board/${board}`);
  if (!res.ok) return [];
  try {
    const data = JSON.parse(res.text) as {
      jobs?: Array<{
        id: string;
        title: string;
        location?: string;
        employmentType?: string;
        isListed?: boolean;
        jobUrl?: string;
        descriptionPlain?: string;
      }>;
    };
    const out: Card[] = [];
    for (const j of data.jobs || []) {
      if (j.isListed === false) continue;
      const hay = `${j.title} ${j.employmentType || ''}`;
      if (!INTERN_HINT.test(hay)) continue;
      out.push({
        title: j.title,
        company,
        location: j.location || 'To verify',
        url: j.jobUrl || `https://jobs.ashbyhq.com/${board}/${j.id}`,
        snippet: (j.descriptionPlain || '').slice(0, 500),
        sourceJobId: `ashby:${j.id}`,
        source: 'employer',
        discoveryQuery: `ashby:${board}`,
      });
    }
    return out;
  } catch {
    return [];
  }
}

export interface EmployerCheck {
  url: string;
  reachable: boolean;
  hasInternSignal: boolean;
  hasApply: boolean;
  title: string;
  detail: string;
  /** Why it was unreachable, when it was. Kept so a caller can tell a refusal
   *  (`blocked`) from a dead posting (`gone`) without parsing `detail`, which
   *  is the same mistake the transport used to make with 403 vs 429. */
  kind?: 'blocked' | 'gone' | 'error';
  /** Wall-clock cost, so a run report can show what verification cost. */
  elapsedMs?: number;
}

/**
 * Generic employer-page check: is the page alive, does it mention a stage, is
 * there an apply path?
 *
 * Measured against the 9 employer pages the 2026-09-17 run verified with a full
 * browser: all 9 answered here in 10.9s total (~1.2s each) with no JS needed,
 * against ~72s per page through the browser. So the browser is the ESCALATION,
 * not the default — pass a `guard` and pace it like any other source.
 */
export async function checkEmployerPage(url: string, guard?: Guard): Promise<EmployerCheck> {
  const t0 = Date.now();
  const res = guard ? await fetchGuarded(url, guard) : await fetchText(url);
  if (!res.ok) {
    return {
      url,
      reachable: false,
      hasInternSignal: false,
      hasApply: false,
      title: '',
      // `res.detail` already names the host and status; prefixing it with the
      // kind made A4's `Blocked — <motivo>` read "Blocked — blocked: HTTP 403",
      // which tells a human nothing the second time. The kind is its own field.
      detail: res.detail,
      kind: res.kind,
      elapsedMs: Date.now() - t0,
    };
  }
  const titleM = res.text.match(/<title>([\s\S]*?)<\/title>/i);
  const title = titleM ? titleM[1].replace(/\s+/g, ' ').trim().slice(0, 120) : '';
  const head = res.text.slice(0, 120000);
  return {
    url,
    reachable: true,
    hasInternSignal: INTERN_HINT.test(head),
    hasApply: /apply|candidati|invia (il tuo )?curriculum|bewerbung/i.test(head),
    title,
    detail: 'page alive',
    elapsedMs: Date.now() - t0,
  };
}
