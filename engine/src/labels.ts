// Explicit mapping from engine decision to A1 qualitative labels.
// A1 rule: pertinente/adiacente only with a read, reliable description;
// score 0-100 is optional and never replaces the label.
import type { A1Label, Decision } from './types.js';

export function decisionToA1(
  decision: Decision,
  hasReliableDescription: boolean,
  score: number | null,
): A1Label {
  if (decision === 'exclude') return 'fuori profilo';
  if (!hasReliableDescription) return 'non_risolto';
  if (score !== null && (score < 0 || score > 100)) {
    throw new Error(`score out of range: ${score}`);
  }
  if (decision === 'shortlist') return 'pertinente';
  return 'adiacente';
}

/** A4 invariant: no score without a reliable description. */
export function assertNoScoreWithoutDescription(hasReliableDescription: boolean, score: number | null): void {
  if (!hasReliableDescription && score !== null) {
    throw new Error('A4 violation: score assigned without a reliable description');
  }
}
