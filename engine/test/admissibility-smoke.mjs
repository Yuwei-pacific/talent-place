// node test/admissibility-smoke.mjs
//
// A1 §Ammissibilità. Two things are being asserted, and the second matters more
// than the first:
//
//   1. The four grounds fire. Each case below is a sentence of A1 §44.
//   2. **An undeclared field excludes nothing.** A1 §47 — "Modalità di lavoro,
//      lingua o idoneità curricolare non dichiarate: mantenere l'incertezza" —
//      is what keeps this from becoming a filter that quietly drops the roles
//      nobody could confirm. Most of the cases below are the negative ones.
import { strict as assert } from 'node:assert';
import {
  admissibilityVerdict,
  isWorkMode,
  normLanguage,
  WORK_MODES,
} from '../lib/admissibility.js';

const ground = (fields) => {
  const v = admissibilityVerdict(fields);
  return v.verdict === 'escluso' ? v.ground : 'ammissibile';
};

// ---------------------------------------------------------------------------
// The instance this module exists for: 2026-09-22 Accessory design ED.14.
//
// Zenesis — stage de créateur de bijoux / sourcing éco-responsable was judged
// `pertinente`, score 74, correctly on its merits. Its own verdict then said:
// "Da escludere in ammissibilità: 100% télétravail (A1 esclude il lavoro
// interamente da remoto) e annuncio scaduto il 30/11/2025 con inizio 01/09/2025."
// It reached run.tsv. Only a hand-written gate in build-tsv.py, outside this
// repo, kept it out of Review.xlsx.
// ---------------------------------------------------------------------------
{
  const zenesis = {
    title: 'stage de créateur de bijoux / sourcing éco-responsable',
    workMode: 'fully_remote',
    applicationOpen: false,
  };
  assert.equal(ground(zenesis), 'fully-remote', 'Zenesis must be excluded, not merely doubted');
  const v = admissibilityVerdict(zenesis);
  assert.equal(v.verdict, 'escluso');
  assert.ok(v.detail.length > 0, 'A4 wants a motivated example, so the verdict carries its reason');

  // The same role with the work mode undeclared is NOT excluded — the closed ad
  // is a separate ground and still fires.
  assert.equal(ground({ title: zenesis.title, applicationOpen: false }), 'closed-ad');
  assert.equal(
    ground({ title: zenesis.title }),
    'ammissibile',
    'with nothing declared, A1 §47 keeps the uncertainty rather than excluding',
  );
}

// ---------------------------------------------------------------------------
// §44 "ruoli chiaramente senior/manager/director, salvo esplicita natura di
// stage" — including the escape hatch, which is the whole second half of the
// sentence.
// ---------------------------------------------------------------------------
assert.equal(ground({ title: 'Senior Service Design Manager' }), 'senior-without-stage');
assert.equal(ground({ title: 'Head of Design' }), 'senior-without-stage');
assert.equal(ground({ title: 'Design Director' }), 'senior-without-stage');
assert.equal(
  ground({ title: 'Senior Service Design Intern' }),
  'ammissibile',
  '"salvo esplicita natura di stage": an intern title is the explicit exception',
);
assert.equal(ground({ title: 'Stagista senior — ufficio design' }), 'ammissibile');

// ---------------------------------------------------------------------------
// §44 "lavoro interamente da remoto". Only the declaration fires it, and
// `hybrid` is admissible — the exclusion is for work ENTIRELY remote.
// ---------------------------------------------------------------------------
assert.equal(ground({ title: 'Stage', workMode: 'fully_remote' }), 'fully-remote');
assert.equal(ground({ title: 'Stage', workMode: 'hybrid' }), 'ammissibile');
assert.equal(ground({ title: 'Stage', workMode: 'onsite' }), 'ammissibile');
assert.equal(
  ground({ title: 'Stage', workMode: 'to_verify' }),
  'ammissibile',
  'A1 §47: work mode not established keeps the uncertainty, it does not exclude',
);

// The work mode is a CLOSED set, for the reason `Contact Search Status` is one:
// a free-text value would sit in the run looking like a field that was checked
// while never matching anything. "100% télétravail" is exactly the string that
// started this.
assert.ok(WORK_MODES.includes('to_verify'), 'the not-established value must be a member, not an absence');
assert.equal(isWorkMode('fully_remote'), true);
assert.equal(isWorkMode('100% télétravail'), false, 'free text must be refused rather than silently accepted');
assert.equal(isWorkMode('remote'), false, 'and so must a partial spelling — the exclusion is for ENTIRELY remote');

// ---------------------------------------------------------------------------
// §44 "annuncio chiaramente chiuso". Declared first, cheap signal second.
// ---------------------------------------------------------------------------
assert.equal(ground({ title: 'Stage', applicationOpen: false }), 'closed-ad');
assert.equal(ground({ title: 'Stage', applicationOpen: true }), 'ammissibile');
assert.equal(
  ground({ title: 'Stage', snippet: 'This job is closed — position filled' }),
  'closed-ad',
  'the SERP-level signal fires too, so a closed post is caught without a read',
);

// ---------------------------------------------------------------------------
// §44 "lingua obbligatoria incompatibile con le lingue ammesse e senza
// alternativa" — all three qualifiers matter.
// ---------------------------------------------------------------------------
const IT_EN = ['italiano', 'inglese'];
assert.equal(
  ground({ title: 'Stage', requiredLanguages: ['francese'], admittedLanguages: IT_EN }),
  'mandatory-language',
);
assert.equal(
  ground({ title: 'Stage', requiredLanguages: ['inglese', 'francese'], admittedLanguages: IT_EN }),
  'ammissibile',
  '"senza alternativa": an admitted language among the required ones is the alternative',
);
assert.equal(
  ground({ title: 'Stage', requiredLanguages: ['francese'] }),
  'ammissibile',
  'A1 §47 again — with A3 not declaring its languages, no language can exclude',
);
assert.equal(
  ground({ title: 'Stage', requiredLanguages: ['French'], admittedLanguages: ['italiano', 'inglese'] }),
  'mandatory-language',
  'endonyms and codes fold to one name, so "French" and "francese" cannot disagree',
);
assert.equal(
  ground({ title: 'Stage', requiredLanguages: ['FR'], admittedLanguages: ['francese'] }),
  'ammissibile',
  'a language code must resolve to the same language as its name',
);
assert.equal(
  ground({ title: 'Stage', admittedLanguages: IT_EN }),
  'ammissibile',
  'a preference is not a requirement: no required language means nothing to exclude on',
);

assert.equal(normLanguage('Inglese'), normLanguage('english'));
assert.equal(normLanguage('  Français  '), normLanguage('fr'));

// ---------------------------------------------------------------------------
// An ordinary role is admissible. A gate that only has negative cases cannot be
// told apart from one that excludes everything.
// ---------------------------------------------------------------------------
assert.equal(
  ground({
    title: 'Stage Junior Product Designer',
    workMode: 'hybrid',
    applicationOpen: true,
    requiredLanguages: ['inglese'],
    admittedLanguages: IT_EN,
    snippet: 'collaborerai con il team prodotto',
  }),
  'ammissibile',
);

console.log('admissibility-smoke: OK');
