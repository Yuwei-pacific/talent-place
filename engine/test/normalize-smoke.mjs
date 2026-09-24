// node test/normalize-smoke.mjs (run after npm run build)
import { strict as assert } from 'node:assert';
import { normCompany, normTitle, normCity, crossPortalKey } from '../lib/normalize.js';

assert.equal(normCompany('Accenture S.p.A.'), 'accenture');
assert.equal(normCompany('Kering SA'), 'kering');
assert.equal(normCompany('Nestlé'), 'nestle');
assert.equal(normTitle('Stage Innovation Office'), 'intern innovation office');
assert.equal(normTitle('Tirocinio Curricular Internship'), 'intern curricular intern');
assert.equal(normTitle('Praktikant Business Transformation'), 'intern business transformation');
assert.equal(normCity('Milano, Lombardia, Italy'), 'milan');
assert.equal(normCity('Milan, Italy'), 'milan');
const k1 = crossPortalKey('Kering SA', 'CRM & Clienteling Intern', 'Milan, Italy');
const k2 = crossPortalKey('Kering', 'CRM Clienteling Stage', 'Milano, Italia');
assert.equal(k1, k2);

// A parenthetical is a qualifier, not part of the account name (A4 §13). Before
// this, "Miu Miu (Gruppo Prada)" and "Miu Miu" were two keys, so one business
// unit landed on two rows that then could not match each other — YUW-76.
// Ported from the 2026-09-22 run's `build-tsv.py`, which is where the rule
// actually lived while the engine went without it.
assert.equal(normCompany('Miu Miu (Gruppo Prada)'), normCompany('Miu Miu'));
assert.equal(normCompany('Miu Miu (Gruppo Prada)'), 'miu miu');
assert.equal(
  normCompany('Acme (Italia) S.p.A.'),
  'acme',
  'stripped BEFORE the legal suffix, so a parenthetical cannot shield one',
);
assert.equal(normCompany('Studio Rossi (Design) Srl'), 'studio rossi');
// ...and it reaches the dedup key, which is where the split was costing a row.
assert.equal(
  crossPortalKey('Miu Miu (Gruppo Prada)', 'Stage Sviluppo Prodotto', 'Milano'),
  crossPortalKey('Miu Miu', 'Stage Sviluppo Prodotto', 'Milan'),
);

// The cost of the rule, asserted rather than left to be found later: two names
// differing ONLY by a parenthetical, with the same title and the same city, now
// produce ONE role key, so `checkDup` could call the second a duplicate. The
// city being a separate axis is what keeps that narrow. It is narrow, not zero.
assert.equal(
  crossPortalKey('Studio Rossi (Design)', 'Stage UX', 'Milano'),
  crossPortalKey('Studio Rossi', 'Stage UX', 'Milano'),
  'if this ever needs to stop being true, the fix is a scheme that keeps the qualifier',
);

// The two pairs the rule EXISTS to merge, from the 2026-09-22 Accessory design
// run, where each arrived twice and produced two rows for one unit.
assert.equal(normCompany('Miu Miu (Gruppo Prada)'), normCompany('Miu Miu'));
assert.equal(normCompany('Stroili (Gruppo Thom)'), normCompany('Stroili'));

// ...and the merges it must never make. A4 §13 keeps the brand and the business
// unit: Miu Miu, Prada Group and Versace are three accounts of one group, and a
// rule that stripped parentheticals by collapsing GROUPS would satisfy the
// assertions above and fail these. Written down because YUW-76 named this as
// the risk of the very fix it asked for.
assert.notEqual(normCompany('Miu Miu'), normCompany('Prada Group'));
assert.notEqual(normCompany('Miu Miu'), normCompany('Versace'));
assert.notEqual(normCompany('Prada Group'), normCompany('Versace'));
assert.notEqual(normCompany('Stroili'), normCompany('Thom Browne'));

console.log('normalize-smoke: OK');
