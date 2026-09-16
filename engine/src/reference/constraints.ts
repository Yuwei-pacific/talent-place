import type { JobLead, SearchPack } from './types.js'

const INTERN =
  /\b(intern|internship|stage|tirocinio|working student|graduate internship|curricular intern|tirocinante)\b/i
const SENIOR = /\b(senior|manager|director|head of|vice president|\bvp\b|lead engineer|principal)\b/i
const CLOSED = /no longer accepting|this job is closed|non accetta più|offerta chiusa|position filled/i
const THIRD_LANG =
  /\b(german|french|spanish|dutch|polish|portuguese|swedish|danish|finnish|czech|hungarian|russian|chinese|japanese|arabic)\s+(required|mandatory|obbligator|richiest)/i
const THIRD_PREFERRED = /\b(german|french|spanish)\s+preferred\b/i
const EU =
  /\b(italy|italia|milan|milano|rome|roma|eu\b|europe|european union|france|germany|spain|austria|netherlands|belgium|portugal|sweden|denmark|ireland|greece|finland|poland)\b/i
const NON_EU = /\b(united states|\busa\b|united kingdom|\buk\b|india|china|singapore|dubai|uae|canada|australia)\b/i

export function applyHardConstraints(job: JobLead, pack: SearchPack): JobLead {
  const findings: string[] = []
  const title = job.title || ''
  const hay = [
    title,
    job.fullDescription || '',
    job.responsibilities || '',
    job.requirements || '',
    job.employmentType || '',
    job.applicationStatus || '',
    job.location || '',
    job.workMode || '',
  ]
    .join('\n')
    .toLowerCase()

  if (CLOSED.test(hay)) findings.push('job_closed')

  const looksIntern = INTERN.test(title) || INTERN.test(hay)
  if (job.fullDescription && job.fullDescription.length > 80 && !looksIntern) {
    findings.push('not_internship')
  }
  if (SENIOR.test(title) && !INTERN.test(title)) findings.push('senior_or_manager')

  if (job.workMode === 'fully_remote' && !EU.test(`${job.location} ${hay}`)) {
    findings.push('fully_remote_no_eu_workplace')
  }

  // Deterministically exclude any work mode the pack lists in constraints.work_mode.deny
  // (e.g. fully_remote), regardless of whether the posting names an EU workplace. The
  // pack rule "fully_remote is out" must not depend on the LLM's judgment.
  const deniedWorkModes = pack.constraints?.work_mode?.deny || []
  if (job.workMode && deniedWorkModes.includes(job.workMode)) {
    findings.push('denied_work_mode')
  }

  const geo = pack.constraints?.geography
  const italyEu = [...(geo?.primary || []), ...(geo?.allowed || [])].some((item) =>
    /italy|eu|europe|milan/i.test(item),
  )
  if (italyEu && NON_EU.test(job.location) && !EU.test(job.location)) {
    findings.push('outside_italy_eu')
  }

  if (THIRD_LANG.test(hay) && !THIRD_PREFERRED.test(hay)) {
    findings.push('third_language_required')
  }

  const detailEmpty =
    job.verificationStatus === 'detail_failed' ||
    (job.verificationStatus === 'lead_only' && !(job.fullDescription || '').trim())
  if (detailEmpty) findings.push('insufficient_detail_for_shortlist')

  if (!findings.length) {
    return { ...job, hardConstraintFindings: [] }
  }

  const exclude = findings.some((item) => item !== 'insufficient_detail_for_shortlist')
  if (exclude) {
    return {
      ...job,
      hardConstraintFindings: findings,
      decision: 'exclude',
      score: null,
      evaluationStatus: 'skipped',
      selected: false,
    }
  }
  return {
    ...job,
    hardConstraintFindings: findings,
    decision: 'review',
    score: null,
    evaluationStatus: 'insufficient_evidence',
    selected: false,
  }
}
