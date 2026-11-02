// node test/admissibility-smoke.mjs
//
// A1 §Ammissibilità. Two things are being asserted, and the second matters more
// than the first:
//
//   1. The four grounds fire. Each case below is a sentence of A1 §44.
//   2. **An undeclared field excludes nothing.** A1 §46 — "Modalità di lavoro,
//      lingua o idoneità curricolare non dichiarate: mantenere l'incertezza" —
//      is what keeps this from becoming a filter that quietly drops the roles
//      nobody could confirm. Most of the cases below are the negative ones.
import { strict as assert } from 'node:assert';
import {
  admissibilityVerdict,
  INTERN_SIGNAL,
  isWorkMode,
  normLanguage,
  workModeFrom,
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
    'with nothing declared, A1 §46 keeps the uncertainty rather than excluding',
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
  'A1 §46: work mode not established keeps the uncertainty, it does not exclude',
);

// The work mode is a CLOSED set, for the reason `Contact Search Status` is one:
// a free-text value would sit in the run looking like a field that was checked
// while never matching anything. "100% télétravail" is exactly the string that
// started this.
assert.ok(WORK_MODES.includes('to_verify'), 'the not-established value must be a member, not an absence');
assert.equal(isWorkMode('fully_remote'), true);
assert.equal(isWorkMode('100% télétravail'), false, 'free text must be refused rather than silently accepted');
assert.equal(isWorkMode('remote'), false, 'and so must a partial spelling — the exclusion is for ENTIRELY remote');

// `workModeFrom` is the other direction: a SOURCE's spelling folded onto the
// canonical set. Lever sends `onsite|hybrid|remote`, Ashby sends
// `OnSite|Hybrid|Remote` and sometimes null, and neither uses our casing.
// Unknown values must come back undeclared, never coerced — an unrecognised
// spelling that fell back to `onsite` would be the opposite error, and nothing
// would report it.
assert.equal(workModeFrom('remote'), 'fully_remote');
assert.equal(workModeFrom('Remote'), 'fully_remote', 'the API casing must not matter');
assert.equal(workModeFrom('OnSite'), 'onsite');
assert.equal(workModeFrom('hybrid'), 'hybrid');
assert.equal(workModeFrom('fully_remote'), 'fully_remote', 'our own value must round-trip');
assert.equal(workModeFrom('  Hybrid  '), 'hybrid');
assert.equal(workModeFrom(null), undefined, 'Ashby sends null for postings it has not classified');
assert.equal(workModeFrom(undefined), undefined);
assert.equal(workModeFrom('Flexible'), undefined, 'an unknown value is undeclared, not a guess');
assert.equal(workModeFrom(3), undefined, 'and a non-string is not a value');
// An undeclared work mode must survive into the rule as `ammissibile`, or the
// mapping and the gate would disagree about what "unknown" means.
assert.equal(ground({ title: 'Stage', workMode: workModeFrom(null) }), 'ammissibile');

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
  'A1 §46 again — with A3 not declaring its languages, no language can exclude',
);
assert.equal(
  ground({ title: 'Stage', requiredLanguages: ['French'], admittedLanguages: ['italiano', 'inglese'] }),
  'mandatory-language',
  'endonyms and codes fold to one name, so "French" and "francese" cannot disagree',
);

// A list of more than one language is ambiguous, and the two readings give
// OPPOSITE verdicts — so the caller has to say which the ad meant. Found on the
// 2026-09-24 Strategic design run, where a flat list was read as a disjunction
// and "Fluent level of English, French and Spanish" slipped through because
// English is admitted.
const MSX = { title: 'Customer Service Specialist', requiredLanguages: ['inglese', 'francese', 'spagnolo'], admittedLanguages: IT_EN };
assert.equal(
  ground({ ...MSX, languageRequirement: 'all' }),
  'mandatory-language',
  '"Fluent in English, French and Spanish" demands all three, and two are outside the admitted set',
);
assert.equal(
  ground({ ...MSX, languageRequirement: 'any' }),
  'ammissibile',
  'the same list read as "any one is enough" is satisfied by English',
);
// The reading the other way round: an ad that genuinely offers a choice must not
// be excluded just because one option is outside the admitted set.
const CHOICE = { title: 'Stage', requiredLanguages: ['inglese', 'francese'], admittedLanguages: IT_EN };
assert.equal(ground({ ...CHOICE, languageRequirement: 'any' }), 'ammissibile', '"English or French" has an alternative');
assert.equal(ground({ ...CHOICE, languageRequirement: 'all' }), 'mandatory-language', '"English and French" does not');
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

// ---------------------------------------------------------------------------
// A1 §44 says "chiaramente senior/manager/director, salvo esplicita natura di
// stage". Both halves were narrower in the code than in the sentence, and this
// ground fires BEFORE a read, so a miss here is a role nobody ever sees.
// ---------------------------------------------------------------------------
// Inflections and same-meaning words for an internship are a stage in the title.
for (const title of [
  'Brand Manager Interns',
  'Marketing Manager - Stages',
  'Becario Product Manager',
  'Becaria Brand Manager',
  'Stageur Project Manager',
  'Stagiaires Product Manager',
  'Stagisti Project Manager',
  'Tirocinanti Project Manager',
  'Marketing Manager - Stage curriculare',
  'Project Manager Werkstudent',
]) {
  assert.equal(ground({ title }), 'ammissibile', `an internship word in the title: ${title}`);
}

// A qualifier means the title is not CLEARLY manager or director. That is not the
// same as being a stage, which is why this list is not in INTERN_SIGNAL: the read
// decides, and A1 says junior alone does not qualify.
for (const title of [
  'Assistant Product Manager',
  'Junior Art Director',
  'Jr. Project Manager',
  'Product Manager Trainee',
  'Alternant - Assistant manager',
  'Apprenti Chef de Projet Manager',
]) {
  assert.equal(ground({ title }), 'ammissibile', `not clearly senior, so the read decides: ${title}`);
}

// ...but a qualifier cannot launder a role that says senior outright.
for (const title of ['Senior Assistant Manager', 'Junior Head of Design', 'Principal Trainee Consultant']) {
  assert.equal(ground({ title }), 'senior-without-stage', `still clearly senior: ${title}`);
}

// Bare seniority still fires: a gate that catches nothing protects nothing.
for (const title of ['Product Manager', 'Art Director', 'Senior Consultant', 'Head of Design']) {
  assert.equal(ground({ title }), 'senior-without-stage', title);
}

// The escape hatch reads the card's text too, not only its title.
assert.equal(
  ground({ title: 'Product Manager', snippet: 'Stage curriculare di 6 mesi' }),
  'ammissibile',
  'A1: "salvo esplicita natura di stage" does not say where the ad made it explicit',
);

// `admit` has a read and no snippet, so the read has to be able to say so, in
// either direction. Declared beats inferred, as everywhere else in this file.
assert.equal(ground({ title: 'Product Manager', stageNature: true }), 'ammissibile');
assert.equal(
  ground({ title: 'Stage Manager', stageNature: false }),
  'senior-without-stage',
  'the theatre job: the word is in the title and a read says it is not a stage',
);
assert.equal(ground({ title: 'Marketing Assistant', stageNature: false }), 'ammissibile', 'not a senior title at all');

// The vocabulary is shared with the prefilter's relevance boost, so what stays
// OUT of it matters as much. Measured on the 2026-09-24 run: 46 of 698 unique
// titles were trainee or French work-study, mostly unrelated retail sales.
for (const word of ['Trainee', 'Alternance', 'Alternant', 'Apprenti', 'Junior', 'Assistant']) {
  assert.equal(INTERN_SIGNAL.test(`Sales ${word}`), false, `${word} must not earn the internship boost`);
}

console.log('admissibility-smoke: OK');
