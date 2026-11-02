// node test/employer-smoke.mjs — live Ashby API + employer check (network)
import { strict as assert } from 'node:assert';
import { ashbyBoard, checkEmployerPage } from '../lib/discovery/employer.js';
import { WORK_MODES } from '../lib/admissibility.js';

const cards = await ashbyBoard('veliu', 'Veliu');
assert.ok(cards.length >= 2, `expected >=2 intern cards, got ${cards.length}`);
assert.ok(cards.every((c) => c.source === 'employer' && c.url.startsWith('http')));

// The one assertion here about the API rather than about our code. Ashby could
// re-case its values or add a fourth category, and `workModeFrom` would return
// undeclared — quietly, and in the safe direction, but quietly. `ats-smoke`
// pins the mapping against fixtures; this pins it against the live spellings,
// so a drift is reported instead of absorbed.
const spellings = [...new Set(cards.map((c) => c.workMode))];
assert.ok(
  spellings.every((w) => w === undefined || WORK_MODES.includes(w)),
  `every work mode must be a member of the canonical set or absent, got ${JSON.stringify(spellings)}`,
);
console.log(
  `ashby: OK (${cards.length} intern cards, e.g. "${cards[0].title}"; ` +
    `work modes ${JSON.stringify(spellings.map((w) => w ?? '<undeclared>'))})`,
);

const alive = await checkEmployerPage('https://jobs.ashbyhq.com/veliu');
assert.equal(alive.reachable, true);
assert.equal(alive.hasInternSignal, true); // board lists internships (apply buttons render client-side)
const dead = await checkEmployerPage('https://careers.jakala.com/en_US/careers/JobDetail/Intern-UX-UI-Experience-Design/2352');
assert.equal(dead.reachable, false); // stale detail URL: 302->404
console.log('employer-check: OK');
