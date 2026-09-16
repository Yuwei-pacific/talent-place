import type { JobLead } from './types.js'

function norm(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

export function normalizedJobKey(job: Pick<JobLead, 'company' | 'title' | 'location' | 'sourceJobId' | 'url'>): string {
  if (job.sourceJobId && /^\d{8,}$/.test(job.sourceJobId)) return `li:${job.sourceJobId}`
  if (job.sourceJobId && /^[a-f0-9]{10,}$/i.test(job.sourceJobId)) return `in:${job.sourceJobId.toLowerCase()}`
  const company = norm(job.company || '')
  const title = norm(job.title || '')
  const location = norm(job.location || '')
  if (company && title) return `ctl:${company}|${title}|${location}`
  return `url:${(job.url || '').replace(/\/+$/, '').toLowerCase()}`
}

export function mergeLeads(existing: JobLead, incoming: JobLead): JobLead {
  const alternates = new Set([
    ...(existing.alternateUrls || []),
    ...(incoming.alternateUrls || []),
    existing.portalUrl,
    incoming.portalUrl,
    existing.url,
    incoming.url,
  ].filter(Boolean) as string[])
  const employer = existing.directEmployerUrl || incoming.directEmployerUrl
  const primary = employer || existing.primaryUrl || incoming.primaryUrl || existing.url
  alternates.delete(primary)
  const richer =
    (incoming.fullDescription || '').length > (existing.fullDescription || '').length ? incoming : existing
  const other = richer === incoming ? existing : incoming
  return {
    ...richer,
    id: existing.id,
    company: richer.company !== 'Unknown company' ? richer.company : other.company,
    title: richer.title || other.title,
    location: richer.location || other.location,
    primaryUrl: primary,
    url: primary,
    alternateUrls: [...alternates],
    discoveryQuery: existing.discoveryQuery || incoming.discoveryQuery,
    overrideDecision: existing.overrideDecision || incoming.overrideDecision,
    existingAccount: existing.existingAccount || incoming.existingAccount,
    selected: existing.selected || incoming.selected,
    normalizedJobKey: existing.normalizedJobKey || incoming.normalizedJobKey || normalizedJobKey(richer),
  }
}

export function dedupLeads(jobs: JobLead[]): JobLead[] {
  const byId = new Map<string, JobLead>()
  const byKey = new Map<string, JobLead>()
  const out: JobLead[] = []

  for (const raw of jobs) {
    const job = { ...raw, normalizedJobKey: raw.normalizedJobKey || normalizedJobKey(raw) }
    const idKey = job.sourceJobId ? `${job.discoverySource || job.source}:${job.sourceJobId}` : ''
    const employer = job.directEmployerUrl?.replace(/\/+$/, '').toLowerCase()
    let existing: JobLead | undefined
    if (idKey) existing = byId.get(idKey)
    if (!existing && employer) existing = byKey.get(`emp:${employer}`)
    if (!existing) existing = byKey.get(job.normalizedJobKey)
    if (!existing) {
      out.push(job)
      if (idKey) byId.set(idKey, job)
      byKey.set(job.normalizedJobKey, job)
      if (employer) byKey.set(`emp:${employer}`, job)
      continue
    }
    const merged = mergeLeads(existing, job)
    const index = out.indexOf(existing)
    if (index >= 0) out[index] = merged
    if (idKey) byId.set(idKey, merged)
    byKey.set(merged.normalizedJobKey || job.normalizedJobKey, merged)
    if (employer) byKey.set(`emp:${employer}`, merged)
  }
  return out
}
