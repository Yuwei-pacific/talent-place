// node test/history-smoke.mjs — history load + dup verdicts against canonical CSV
import { strict as assert } from 'node:assert';
import { loadHistory, checkDup } from '../lib/history.js';

const CSV = '/Users/yuwei/Documents/POLI.design/talent-place/index/Strategic_Design_Company_Index.csv';
const h = loadHistory(CSV);
assert.ok(h.size >= 100, `expected >=100 companies, got ${h.size}`);
// Known company, known role URL -> dup
const accenture = h.get('accenture');
assert.ok(accenture && accenture.urls.size > 0);
const knownUrl = [...accenture.urls][0];
assert.deepEqual(checkDup(h, 'Accenture', 'whatever', 'Milan', knownUrl), { dup: true, reason: 'same URL in history' });
// Known company, new role -> not dup, companyKnown
const v = checkDup(h, 'Accenture', 'Quantum Gardening Intern — Milan', 'Milan, Italy', 'https://example.com/jobs/xyz-999');
assert.equal(v.dup, false);
assert.equal(v.companyKnown, true);
// Unknown company
assert.deepEqual(checkDup(h, 'Nonexistent Corp XYZ', 'Intern', 'Milan', 'https://example.com/1'), { dup: false, companyKnown: false });
console.log(`history-smoke: OK (${h.size} companies)`);
