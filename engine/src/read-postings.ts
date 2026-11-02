// The read step: full posting text for the cards a run decided to read.
//
// It lived in a run-directory script, fetch-descriptions.py, until the 2026-11-02 run,
// where 52 of 59 cards went unread because that script stopped at its second 429 and
// nothing came back to it. It shares discovery's host and so discovery's limit, which
// is why it takes the same guard: it waits the same way, and stops the same way.
//
// A description is written to disk as soon as it is read, keyed by the card's id, so a
// second run asks only for what is missing. Judging the text stays with the agent.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import type { Card } from './types.js';
import type { Guard } from './ratelimit.js';
import { fetchGuarded } from './discovery/http.js';
import { parsePosting } from './discovery/linkedin-guest.js';

export interface ReadPosting extends Card {
  http: number;
  desc: string;
  closedOnPage: boolean | null;
}

export interface ReadReport {
  cards: number;
  read: number;
  gone: number;
  alreadyRead: number;
  withoutId: number;
  unread: number;
}

export async function readPostings(
  cards: Card[],
  outPath: string,
  guard: Guard,
  baseUrl = 'https://www.linkedin.com',
): Promise<ReadReport> {
  const done = new Map<string, ReadPosting>();
  if (existsSync(outPath)) {
    for (const d of JSON.parse(readFileSync(outPath, 'utf-8')) as ReadPosting[]) {
      if (d.sourceJobId) done.set(d.sourceJobId, d);
    }
  }
  const report: ReadReport = { cards: cards.length, read: 0, gone: 0, alreadyRead: 0, withoutId: 0, unread: 0 };
  const save = () => {
    mkdirSync(dirname(outPath), { recursive: true });
    writeFileSync(outPath, JSON.stringify([...done.values()], null, 1));
  };

  for (const card of cards) {
    const id = card.sourceJobId;
    if (!id) {
      report.withoutId++;
      continue;
    }
    if (done.get(id)?.desc || done.get(id)?.http === 404) {
      report.alreadyRead++;
      continue;
    }
    if (guard.stop.stopped) {
      report.unread++;
      continue;
    }
    const res = await fetchGuarded(`${baseUrl}/jobs-guest/jobs/api/jobPosting/${id}`, guard);
    if (res.ok) {
      const { desc, closed } = parsePosting(res.text);
      done.set(id, { ...card, http: res.status, desc, closedOnPage: closed });
      report.read++;
      save();
    } else if (res.kind === 'gone') {
      done.set(id, { ...card, http: res.status ?? 404, desc: '', closedOnPage: null });
      report.gone++;
      save();
    } else {
      report.unread++;
    }
  }
  save();
  return report;
}
