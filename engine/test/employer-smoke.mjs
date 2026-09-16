// node test/employer-smoke.mjs — live Ashby API + employer check (network)
import { strict as assert } from 'node:assert';
import { ashbyBoard, checkEmployerPage } from '../lib/discovery/employer.js';

const cards = await ashbyBoard('veliu', 'Veliu');
assert.ok(cards.length >= 2, `expected >=2 intern cards, got ${cards.length}`);
assert.ok(cards.every((c) => c.source === 'employer' && c.url.startsWith('http')));
console.log(`ashby: OK (${cards.length} intern cards, e.g. "${cards[0].title}")`);

const alive = await checkEmployerPage('https://jobs.ashbyhq.com/veliu');
assert.equal(alive.reachable, true);
assert.equal(alive.hasInternSignal, true); // board lists internships (apply buttons render client-side)
const dead = await checkEmployerPage('https://careers.jakala.com/en_US/careers/JobDetail/Intern-UX-UI-Experience-Design/2352');
assert.equal(dead.reachable, false); // stale detail URL: 302->404
console.log('employer-check: OK');
