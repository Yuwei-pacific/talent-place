// A1 §Ammissibilità as a function with a caller.
//
// The rule was in the config and in whichever script drove the run. The
// 2026-09-22 Accessory design ED.14 run carried a hand-written
// `work_mode == "remote"` gate — in build-tsv.py, outside this repo — and that
// is the only reason Zenesis, judged `pertinente` at score 74 on its merits,
// did not reach Review.xlsx. Its own verdict recorded why it should not have:
// "Da escludere in ammissibilità: 100% télétravail ... e annuncio scaduto".
// A rule that lives in the driver dies with the driver. This is its home.
//
// A1 §46 governs the whole shape: an UNDECLARED field never excludes. Work mode,
// language and curricular fit that the ad does not state keep the uncertainty,
// and the role stays in the pool to be assessed with its doubts visible. Only a
// declaration can exclude, which is why almost every input below is optional.
//
// `decisionToA1` in labels.ts is the other half of A1 §53 and is deliberately on
// no execution path (the label belongs to the agent). This is the half that must
// be run, because it is mechanical: given a declared work mode, the verdict is
// not a judgement.
import type { Card, WorkMode } from './types.js';

/**
 * A1 §44's grounds, as counter keys and as the reason a row is not admissible.
 *
 * `sede fuori dai limiti` is the fifth ground and is absent here on purpose: it
 * is already a hard gate in `geo.ts`, which runs before this and needs no second
 * implementation.
 */
export type AdmissibilityGround =
  | 'senior-without-stage'
  | 'fully-remote'
  | 'closed-ad'
  | 'mandatory-language';

export type Admissibility =
  | { verdict: 'ammissibile' }
  | { verdict: 'escluso'; ground: AdmissibilityGround; detail: string };

/**
 * The closed set a run writes into `work_mode`.
 *
 * Closed on purpose, and the same shape as `Contact Search Status`: the failure
 * this module exists to prevent is a posting that says "100% télétravail" being
 * invisible to a matcher that only knows "remote". Matching free text would need
 * a marker list that rots — and CLAUDE.md records what a widened marker list did
 * to `BLOCKED_MARKERS`. A run that cannot tell declaration from guesswork writes
 * `to_verify`, which is A1 §46's answer and excludes nothing.
 */
export const WORK_MODES: readonly WorkMode[] = ['onsite', 'hybrid', 'fully_remote', 'to_verify'];

export function isWorkMode(value: string): value is WorkMode {
  return (WORK_MODES as readonly string[]).includes(value);
}

/** The two readings of a language list. Closed for the same reason the work
 *  modes are: a third spelling would be a value nothing understands, sitting in
 *  a run looking like a decision. */
export const LANGUAGE_REQUIREMENTS = ['all', 'any'] as const;
export type LanguageRequirement = (typeof LANGUAGE_REQUIREMENTS)[number];

export function isLanguageRequirement(value: unknown): value is LanguageRequirement {
  return typeof value === 'string' && (LANGUAGE_REQUIREMENTS as readonly string[]).includes(value);
}

/**
 * Map a SOURCE's own spelling onto the canonical set.
 *
 * Two APIs declare this and neither uses our casing: Lever sends
 * `onsite|hybrid|remote`, Ashby sends `OnSite|Hybrid|Remote` and sometimes
 * `null`. So the comparison folds case and separators, and the result is a
 * member of `WORK_MODES` or `undefined`.
 *
 * `undefined` means NOT DECLARED, which A1 §46 keeps uncertain — never "not
 * remote". An unrecognised spelling must not fall back to `onsite`, because that
 * is the opposite error and, unlike a missed exclusion, nothing would report it.
 * Within these vocabularies `remote` is one of three mutually exclusive
 * categories, so it is the fully-remote one; that is why the mapping is safe
 * here and a `location.name` substring test is not.
 */
export function workModeFrom(value: unknown): WorkMode | undefined {
  if (typeof value !== 'string') return undefined;
  const k = value.trim().toLowerCase().replace(/[\s_-]/g, '');
  if (k === 'onsite') return 'onsite';
  if (k === 'hybrid') return 'hybrid';
  if (k === 'remote' || k === 'fullyremote') return 'fully_remote';
  return undefined;
}

/** A1 §44: internship vocabulary. Also the escape hatch in `senior-without-stage`
 *  ("salvo esplicita natura di stage"), and the relevance signal `prefilter`
 *  scores with — one definition so the two cannot drift apart. */
export const INTERN_SIGNAL =
  /\b(intern|internship|stage|stagista|tirocinio|tirocinante|working student|graduate internship|curricular|praktikant|praktikum|beca|stagiaire)\b/i;

/** A1 §44: "ruoli chiaramente senior/manager/director". */
export const SENIOR_SIGNAL = /\b(senior|manager|director|head of|vice president|\bvp\b|principal)\b/i;

/** A1 §44: "annuncio chiaramente chiuso". A cheap card-level signal only — the
 *  authoritative form of this ground is a declared `applicationOpen === false`. */
export const CLOSED_SIGNAL = /no longer accepting|this job is closed|offerta chiusa|position filled|scaduto/i;

/**
 * Endonyms and codes fold to one name so "inglese", "English" and "en" are the
 * same requirement. Mirrors the CITY_ALIASES shape in normalize.ts.
 */
const LANGUAGE_ALIASES: Record<string, string> = {
  it: 'italian', italiano: 'italian', italian: 'italian', italienne: 'italian', italien: 'italian',
  en: 'english', inglese: 'english', english: 'english', anglais: 'english', englisch: 'english',
  fr: 'french', francese: 'french', french: 'french', francais: 'french', franzosisch: 'french',
  de: 'german', tedesco: 'german', german: 'german', deutsch: 'german', allemand: 'german',
  es: 'spanish', spagnolo: 'spanish', spanish: 'spanish', espanol: 'spanish', espagnol: 'spanish',
};

export function normLanguage(value: string): string {
  const key = (value || '')
    .trim()
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z]/g, '');
  return LANGUAGE_ALIASES[key] ?? key;
}

/** The fields A1 §44 names. `Card` satisfies this structurally, so the pipeline
 *  gate and the `admit` caller share one rule rather than two. */
export interface AdmissibilityFields {
  title: string;
  /** Card-level only. The `admit` path has no snippet — it has a read. */
  snippet?: string;
  workMode?: string;
  /** `false` is a declaration that the ad is closed; absent is not a declaration
   *  of anything (A1 §46). */
  applicationOpen?: boolean;
  /** Only the languages the ad MANDATES. A1: "Una terza lingua solo preferita
   *  non impone l'esclusione." */
  requiredLanguages?: string[];
  /**
   * How to read a list of more than one: must the candidate have ALL of them, or
   * is ANY one enough?
   *
   * It is not a detail — the two readings give OPPOSITE answers on the same
   * list. "English or French required" is satisfied by an admitted language and
   * is NOT an incompatibility; "Fluent in English, French and Spanish" demands
   * two languages outside the admitted set and IS one. A flat list cannot say
   * which, so a caller that supplies `requiredLanguages` has to say.
   *
   * Defaults to `any`, deliberately. A1 §46 keeps the uncertainty, and the two
   * errors are not symmetric: `any` under-excludes, which puts a language
   * mismatch in front of a person; `all` over-excludes, which drops a role that
   * an admitted language would have satisfied, silently. `admit` refuses the
   * ambiguity outright, so a run has to choose rather than inherit this default.
   */
  languageRequirement?: 'all' | 'any';
  /** The languages A3 admits. Absent means undeclared, and then no language can
   *  exclude — the rule needs both sides to say anything. */
  admittedLanguages?: string[];
}

/**
 * A1 §44, in the order the sentence gives it.
 *
 * Returns on the first ground that fires, so the recorded reason is one reason
 * and not a pile. Any ordering is defensible; this one puts the grounds that are
 * established without reading the ad first, which is also why A1 can exclude an
 * unread card.
 */
export function admissibilityVerdict(f: AdmissibilityFields): Admissibility {
  const title = f.title ?? '';
  const hay = `${title}\n${f.snippet ?? ''}`;

  // "ruoli chiaramente senior/manager/director, salvo esplicita natura di stage"
  if (SENIOR_SIGNAL.test(title) && !INTERN_SIGNAL.test(title)) {
    return {
      verdict: 'escluso',
      ground: 'senior-without-stage',
      detail: `titolo senior senza natura di stage: "${title}"`,
    };
  }

  // "lavoro interamente da remoto" — only a declaration can fire this. A1 §46
  // keeps the uncertainty for `to_verify`, and `hybrid` is admissible.
  if (f.workMode === 'fully_remote') {
    return { verdict: 'escluso', ground: 'fully-remote', detail: 'modalità dichiarata: interamente da remoto' };
  }

  // "annuncio chiaramente chiuso" — declared first, cheap signal second.
  if (f.applicationOpen === false) {
    return { verdict: 'escluso', ground: 'closed-ad', detail: 'candidatura dichiarata chiusa' };
  }
  if (CLOSED_SIGNAL.test(hay)) {
    return { verdict: 'escluso', ground: 'closed-ad', detail: 'segnale di annuncio chiuso nel testo' };
  }

  // "lingua obbligatoria incompatibile con le lingue ammesse e senza alternativa"
  const required = (f.requiredLanguages ?? []).map(normLanguage).filter(Boolean);
  const admitted = new Set((f.admittedLanguages ?? []).map(normLanguage).filter(Boolean));
  // "e senza alternativa" is the whole question, and it is a question about the
  // AD's shape rather than about any one language. See `languageRequirement`.
  //   all -> satisfiable only if every demanded language is admitted
  //   any -> satisfiable if one of them is; that one IS the alternative
  if (required.length > 0 && admitted.size > 0) {
    const satisfiable =
      f.languageRequirement === 'all'
        ? required.every((l) => admitted.has(l))
        : required.some((l) => admitted.has(l));
    if (!satisfiable) {
      return {
        verdict: 'escluso',
        ground: 'mandatory-language',
        detail:
          `lingue obbligatorie ${required.join(', ')} (richiesta: ` +
          `${f.languageRequirement === 'all' ? 'tutte' : 'almeno una'}) ` +
          `fuori dalle ammesse ${[...admitted].join(', ')}`,
      };
    }
  }

  return { verdict: 'ammissibile' };
}

/** Convenience for the pipeline gate: a Card IS the field set. */
export function admitCard(card: Card): Admissibility {
  return admissibilityVerdict(card);
}
