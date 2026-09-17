// History = canonical Excel/CSV (semicolon-delimited, A4 columns).
// Read-only for search; add-verified is the only writer.
import { readFileSync } from 'node:fs';
import { crossPortalKey, splitColumn } from './normalize.js';

export interface HistoryEntry {
  company: string;
  /** Stored identity, when the `Company ID` column is present. */
  companyId?: string;
  urls: Set<string>;
  keys: Set<string>;
}

function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = '';
  let inQ = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQ) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else inQ = false;
      } else cur += ch;
    } else if (ch === '"') inQ = true;
    else if (ch === ';') {
      out.push(cur);
      cur = '';
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

function normUrl(u: string): string {
  return u.trim().replace(/\/+$/, '').toLowerCase();
}

/** Split CSV text into records, respecting quoted embedded newlines. */
function splitRecords(text: string): string[] {
  const records: string[] = [];
  let cur = '';
  let inQ = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQ) {
      cur += ch;
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cur += '"';
          i++;
        } else inQ = false;
      }
    } else if (ch === '"') {
      inQ = true;
      cur += ch;
    } else if (ch === '\n') {
      if (cur.trim()) records.push(cur);
      cur = '';
    } else if (ch === '\r') {
      continue;
    } else cur += ch;
  }
  if (cur.trim()) records.push(cur);
  return records;
}

export function loadHistory(csvPath: string): Map<string, HistoryEntry> {
  const text = readFileSync(csvPath, 'utf-8').replace(/^﻿/, '');
  const records = splitRecords(text);
  if (records.length === 0) return new Map();
  const hdr = splitCsvLine(records[0]);
  const ci = (name: string): number => hdr.indexOf(name);
  const iCompany = ci('Company / Outreach Account');
  const iTitles = ci('Matching Job Titles');
  const iLinks = ci('Job Links');
  const iLocs = ci('Locations');
  // Appended column; absent until backfill-ids has run.
  const iCompanyId = ci('Company ID');
  const byCompany = new Map<string, HistoryEntry>();
  for (const line of records.slice(1)) {
    const cols = splitCsvLine(line);
    const company = (cols[iCompany] || '').trim();
    if (!company || company === 'Company / Outreach Account') continue;
    // Was `.split('|')`, which silently produced a concatenated multi-URL blob
    // for every row whose cells use embedded newlines (24 of 113 companies),
    // making checkDup unable to ever report a duplicate for them.
    const titles = splitColumn(cols[iTitles] || '', 'Matching Job Titles');
    const links = splitColumn(cols[iLinks] || '', 'Job Links');
    const locs = splitColumn(cols[iLocs] || '', 'Locations');
    const key = company.toLowerCase();
    let entry = byCompany.get(key);
    if (!entry) {
      entry = { company, companyId: iCompanyId >= 0 ? (cols[iCompanyId] || '').trim() || undefined : undefined, urls: new Set(), keys: new Set() };
      byCompany.set(key, entry);
    }
    for (const l of links) entry.urls.add(normUrl(l));
    titles.forEach((t, idx) => {
      if (t) entry!.keys.add(crossPortalKey(company, t, locs[idx] || locs[0] || ''));
    });
  }
  return byCompany;
}

export type DupVerdict = { dup: true; reason: string } | { dup: false; companyKnown: boolean };

export function checkDup(
  history: Map<string, HistoryEntry>,
  company: string,
  title: string,
  location: string,
  url: string,
): DupVerdict {
  const entry = history.get(company.toLowerCase());
  if (!entry) return { dup: false, companyKnown: false };
  if (entry.urls.has(normUrl(url))) return { dup: true, reason: 'same URL in history' };
  if (entry.keys.has(crossPortalKey(company, title, location))) {
    return { dup: true, reason: 'same company+title+location in history' };
  }
  return { dup: false, companyKnown: true };
}
