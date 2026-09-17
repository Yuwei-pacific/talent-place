// Core types for poli-job-engine. A1-A4 first: a1Label is a first-class field,
// score stays optional (only with a read description).
import type { Guard, StopToken } from './ratelimit.js';

export type A1Label = 'pertinente' | 'adiacente' | 'fuori profilo' | 'non_risolto';

export type JobSource = 'linkedin' | 'indeed' | 'employer' | string;
export type WorkMode = 'onsite' | 'hybrid' | 'fully_remote' | 'to_verify';
export type Decision = 'shortlist' | 'review' | 'exclude';
export type VerificationState =
  | 'Employer verified active'
  | 'Portal verified'
  | 'Legacy result — recheck'
  | 'Blocked'
  | 'To verify';

export interface Card {
  title: string;
  company: string;
  location: string;
  url: string;
  snippet: string;
  posted?: string;
  sourceJobId?: string;
  source: JobSource;
  discoveryQuery: string;
}

export interface Role {
  company: string;
  brand?: string;
  title: string;
  url: string;
  alternateUrls: string[];
  location: string;
  inItaly: 'Yes' | 'No' | 'Mixed';
  themes: string[];
  workMode: string;
  curricularEvidence: string;
  sources: string[];
  languages?: string;
  postedDate?: string;
  deadline?: string;
  applicationOpen?: boolean;
  responsibilities: string[];
  a1Label: A1Label;
  score: number | null;
  notesReason: string;
  verification: string;
  lastChecked: string;
}

/**
 * What a source needs in order to be polite and to be stoppable.
 *
 * Required, not optional: the context IS the feature. There were zero callers
 * of `discover` before this, so there was nothing to keep compatible.
 * Built fresh per run in run.ts — never a module global, because a global leaks
 * rate and stop state across runs and across tests.
 */
export interface DiscoverContext {
  /** This source's own limiter. One per source, so a throttled source cannot
   *  stall a healthy one. */
  guard: Guard;
  /** This source's own stop state. */
  stop: StopToken;
  /** Cards after which the source stops itself. */
  cap: number;
}

export interface SourceAdapter {
  id: string;
  discover(queries: string[], ctx: DiscoverContext): Promise<Card[]>;
}

export interface ObserveCounters {
  queriesTried: number;
  cardsSeen: number;
  prefilterKept: number;
  prefilterDropped: number;
  detailOpened: number;
  detailOk: number;
  detailFailed: number;
  scored: number;
  excludedPerRule: Record<string, number>;
  indeedX: number;
  indeedY: number;
  indeedZ: number;
  indeedP: number;
  indeedStatus: 'Used' | 'Unavailable';
  indeedNote: string;
}
