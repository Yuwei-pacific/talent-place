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
console.log('normalize-smoke: OK');
