// Per-stage counters + Indeed accounting (A4: X = Y + Z + P invariant).
import type { ObserveCounters } from './types.js';

export function newCounters(): ObserveCounters {
  return {
    queriesTried: 0,
    cardsSeen: 0,
    prefilterKept: 0,
    prefilterDropped: 0,
    detailOpened: 0,
    detailOk: 0,
    detailFailed: 0,
    scored: 0,
    excludedPerRule: {},
    indeedX: 0,
    indeedY: 0,
    indeedZ: 0,
    indeedP: 0,
    indeedStatus: 'Unavailable',
    indeedNote: '',
  };
}

export function exclude(c: ObserveCounters, rule: string): void {
  c.excludedPerRule[rule] = (c.excludedPerRule[rule] || 0) + 1;
}

/** A4 Indeed line. Throws when X != Y + Z + P so bad arithmetic never ships. */
export function indeedLine(c: ObserveCounters): string {
  const { indeedX: X, indeedY: Y, indeedZ: Z, indeedP: P } = c;
  if (X !== Y + Z + P) {
    throw new Error(`Indeed invariant violated: X(${X}) != Y(${Y}) + Z(${Z}) + P(${P})`);
  }
  const base = `Indeed: ${c.indeedStatus}; candidati unici trovati ${X}; inclusi nel TSV ${Y}; duplicati o esclusi ${Z}`;
  const extra = P > 0 ? `; non risolti ${P}` : '';
  const note = c.indeedNote ? ` (${c.indeedNote})` : '';
  return base + extra + note;
}
