// Cheap deterministic relevance pre-filter (no LLM). Runs on title+snippet
// BEFORE any detail fetch so broad query fan-out stays affordable.
// Keeps recall: dropped cards stay in the inbox as lead_only, they just don't
// consume detail/LLM budget.
import type { Card } from './types.js';

const INTERN = /\b(intern|internship|stage|stagista|tirocinio|tirocinante|working student|graduate internship|curricular|praktikant|praktikum|beca|stagiaire)\b/i;
const SENIOR = /\b(senior|manager|director|head of|vice president|\bvp\b|principal)\b/i;
const CLOSED = /no longer accepting|this job is closed|offerta chiusa|position filled|scaduto/i;

export interface PrefilterConfig {
  falseFriends: string[];
  queryTerms: string[];
  topK: number;
}

export interface ScoredCard {
  card: Card;
  score: number; // 0-1
  reasons: string[];
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function prefilter(cards: Card[], config: PrefilterConfig): { kept: ScoredCard[]; dropped: ScoredCard[] } {
  const ffRes = config.falseFriends.filter(Boolean).map((t) => new RegExp(`\\b${escapeRe(t)}\\b`, 'i'));
  const termRes = config.queryTerms.filter(Boolean).map((t) => new RegExp(`\\b${escapeRe(t)}\\b`, 'i'));
  const scored: ScoredCard[] = cards.map((card) => {
    const hay = `${card.title}\n${card.snippet}`;
    const reasons: string[] = [];
    let score = 0.3; // base: discovered at all
    if (INTERN.test(card.title)) {
      score += 0.3;
      reasons.push('intern-signal-in-title');
    } else if (INTERN.test(hay)) {
      score += 0.15;
      reasons.push('intern-signal-in-snippet');
    }
    if (SENIOR.test(card.title) && !INTERN.test(card.title)) {
      score -= 0.5;
      reasons.push('senior-title');
    }
    if (CLOSED.test(hay)) {
      score -= 0.6;
      reasons.push('closed-signal');
    }
    const ffHit = ffRes.find((re) => re.test(hay));
    if (ffHit) {
      score -= 0.25;
      reasons.push(`false-friend:${ffHit.source}`);
    }
    let hits = 0;
    for (const re of termRes) if (re.test(hay)) hits++;
    if (termRes.length > 0) {
      const overlap = hits / termRes.length;
      score += overlap * 0.25;
      if (hits > 0) reasons.push(`query-terms:${hits}/${termRes.length}`);
    }
    return { card, score: Math.max(0, Math.min(1, score)), reasons };
  });
  scored.sort((a, b) => b.score - a.score);
  const kept = scored.slice(0, config.topK);
  const dropped = scored.slice(config.topK);
  return { kept, dropped };
}
