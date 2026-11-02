// What a run has already paid for, on disk.
//
// One line per finished query x location pair, appended as it finishes, so that a
// process killed in hour two costs only the pair it was on. A torn last line is what
// a kill leaves behind and is skipped; only a success is recorded, so a refused pair
// is asked for again on resume.
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
import type { Card } from '../types.js';

export function loadCheckpoint(path: string): Map<string, Card[]> {
  const done = new Map<string, Card[]>();
  if (!existsSync(path)) return done;
  for (const line of readFileSync(path, 'utf-8').split('\n')) {
    if (!line.trim()) continue;
    try {
      const { key, cards } = JSON.parse(line) as { key: string; cards: Card[] };
      done.set(key, cards);
    } catch {
      // A partial write. Its pair simply runs again.
    }
  }
  return done;
}

export function recordCheckpoint(path: string, key: string, cards: Card[]): void {
  appendFileSync(path, JSON.stringify({ key, cards }) + '\n');
}
