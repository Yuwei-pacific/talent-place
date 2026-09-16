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
import { fetchText } from './http.js';

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
}

/** Generic employer-page check: is the page alive, does it mention a stage, is there an apply path? */
export async function checkEmployerPage(url: string): Promise<EmployerCheck> {
  const res = await fetchText(url);
  if (!res.ok) {
    return { url, reachable: false, hasInternSignal: false, hasApply: false, title: '', detail: `${res.kind}: ${res.detail}` };
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
  };
}
