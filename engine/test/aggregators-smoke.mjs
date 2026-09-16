// node test/aggregators-smoke.mjs — fixture parse, no network
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { parseCercoCards } from '../lib/discovery/aggregators.js';

import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, 'fixtures/cercolavoro-milano.html'), 'utf-8');
const cards = parseCercoCards(html, 'test-query');
assert.ok(cards.length >= 30, `expected >=30 cards, got ${cards.length}`);
const c0 = cards[0];
assert.ok(c0.title.length > 2, 'title parsed');
assert.ok(c0.company.length > 1, 'company parsed');
assert.ok(c0.url.startsWith('https://www.cercolavoro.com/offerta-lavoro-'), 'url parsed');
assert.ok(c0.sourceJobId && c0.sourceJobId.startsWith('cerc:'), 'id parsed');
assert.equal(c0.source, 'cercolavoro');
console.log(`aggregators-smoke: OK (${cards.length} cards, e.g. "${c0.title}" @ ${c0.company})`);
