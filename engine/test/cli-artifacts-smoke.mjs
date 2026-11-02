// node test/cli-artifacts-smoke.mjs
//
// The only test that drives the real CLI against a real (local) source. Every
// other smoke test asserts on the library; this one asserts on the FILES a run
// leaves behind.
//
// It exists because a bucket that lives in `PipelineResult` and never reaches
// `dropped.json` is a bucket nobody can act on. The 2026-09-22 run's exclusions
// were real and correct and lived only in a script outside this repo; the
// failure was not that the judgement was wrong but that it was nowhere durable.
// `--linkedin-base` is documented as "only ever set by tests and by an operator
// pointing at a local fixture", and this is the first of those.
import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ENGINE = fileURLToPath(new URL('..', import.meta.url));

/**
 * `spawn`, NOT `spawnSync`, and the difference is load-bearing.
 *
 * The fixture server below runs in THIS process, so `spawnSync` would block the
 * event loop that has to answer the child's request — the run then times out
 * after 20 s with `err 1` and zero cards, which reads as "the parser found
 * nothing" rather than "nobody served the page".
 */
function runCli(args) {
  return new Promise((done) => {
    const p = spawn(process.execPath, args, { cwd: ENGINE });
    let stdout = '';
    let stderr = '';
    p.stdout.on('data', (d) => (stdout += d));
    p.stderr.on('data', (d) => (stderr += d));
    p.on('close', (status) => done({ status, stdout, stderr }));
  });
}

const card = (id, company, title) => `
<li>
  <div data-entity-urn="urn:li:jobPosting:${id}"></div>
  <h3 class="base-search-card__title">${title}</h3>
  <a class="base-search-card__subtitle" href="/co">${company}</a>
  <span class="job-search-card__location">Milan, Italy</span>
  <a class="base-card__full-link" href="https://it.linkedin.com/jobs/view/role-${id}">go</a>
  <time>2 days ago</time>
</li>`;

// One card per outcome, so the run exercises all four exits at once.
const HTML = [
  card(101, 'Italdesign', 'CMF Designer Internship'), // kept
  card(102, 'BoF Careers', 'Stage PRADA Windows Creative Intern'), // unresolved (A1 §Fonti)
  card(103, 'Beta', 'Senior Service Design Manager'), // excluded (A1 §44)
  card(104, 'Alpha', 'Service Design Intern'), // kept
].join('');

const srv = createServer((_req, res) => {
  res.writeHead(200, { 'content-type': 'text/html' });
  res.end(`<ul>${HTML}</ul>`);
});
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${srv.address().port}`;

const dir = mkdtempSync(join(tmpdir(), 'cli-artifacts-'));
try {
  const cfgPath = join(dir, 'run.json');
  const outDir = join(dir, 'run');
  writeFileSync(
    cfgPath,
    JSON.stringify({
      masterId: 'test-master',
      edition: 'ED.00',
      areas: { 'Area One': ['service design'] },
      internshipTerms: ['stage'],
      locations: ['Milan, Italy'],
      falseFriends: [],
      topK: 10,
    }),
  );

  const res = await runCli([
    'lib/cli.js',
    'discover',
    '--config',
    cfgPath,
    '--out',
    outDir,
    '--linkedin-base',
    base,
  ]);
  assert.equal(res.status, 0, `cli exited ${res.status}\n--- stdout ---\n${res.stdout}\n--- stderr ---\n${res.stderr}`);
  assert.match(res.stdout, /cards\s+4 seen/, 'the fixture must actually have been served — 0 cards would make every assertion below vacuous');

  const read = (f) => JSON.parse(readFileSync(join(outDir, f), 'utf-8'));
  const kept = read('cards.json');
  const dropped = read('dropped.json');
  const report = read('run-report.json');

  // A1 §44: the senior role left by its own exit, with its reason.
  assert.deepEqual(dropped.excluded.map((e) => e.ground), ['senior-without-stage']);
  assert.ok(dropped.excluded[0].detail.length > 0, 'A4 asks for motivated examples, so the file carries the reason');
  assert.equal(dropped.excluded[0].card.company, 'Beta', 'the excluded card is carried, not just counted');

  // A1 §Fonti: the board is recorded as the poster and the role is not attributed.
  assert.equal(dropped.unresolved.length, 1);
  assert.equal(dropped.unresolved[0].company, 'BoF Careers');
  assert.equal(dropped.unresolved[0].poster, 'BoF Careers');

  // And the employers survive: a gate that catches everything protects nothing.
  assert.deepEqual(kept.map((c) => c.company).sort(), ['Alpha', 'Italdesign']);
  assert.ok(
    !kept.some((c) => c.company === 'BoF Careers'),
    'an aggregator must never reach the corpus that becomes Company / Outreach Account',
  );

  // The run-level view, which is what a person reads first.
  assert.deepEqual(report.excludedPerRule, { 'senior-without-stage': 1 });
  assert.equal(report.counters.unresolved, 1);
  assert.equal(report.counters.excluded, 1);
  assert.equal(report.aggregatorHits['bof careers'], 1);
  assert.equal(report.aggregatorTable.missing, false, 'a table that was not read must not report as merely empty');
  assert.equal(
    'adecco' in report.aggregatorHits && report.aggregatorHits['adecco'],
    0,
    'an entry that fired nothing reports 0 rather than being absent — an inert list must be visible',
  );

  // The stdout summary names both new exits, so a run's shape is legible without
  // opening a JSON file.
  assert.match(res.stdout, /unattrib\./);
  assert.match(res.stdout, /excluded\s+1 by A1 §44: senior-without-stage 1/);
} finally {
  srv.close();
  rmSync(dir, { recursive: true, force: true });
}

// ---------------------------------------------------------------------------
// `admit`, through the real CLI. It takes what a read established, so the read
// has to be able to overrule what a title suggests.
// ---------------------------------------------------------------------------
const admit = (fields) => {
  const d = mkdtempSync(join(tmpdir(), 'admit-'));
  try {
    const path = join(d, 'declared.json');
    writeFileSync(path, typeof fields === 'string' ? fields : JSON.stringify(fields));
    const res = spawnSync(process.execPath, ['lib/cli.js', 'admit', '--fields', path, '--out', d], {
      cwd: ENGINE,
      encoding: 'utf-8',
    });
    const out = res.status === 0 ? JSON.parse(readFileSync(join(d, 'exclusions.json'), 'utf-8')) : null;
    return { status: res.status, stderr: res.stderr, out };
  } finally {
    rmSync(d, { recursive: true, force: true });
  }
};
const role = (over) => ({ title: 'Stage', url: 'https://x.example/1', ...over });
{
  const ok = admit({ roles: [role({ title: 'Product Manager', stageNature: true }), role({ title: 'Product Manager' })] });
  assert.equal(ok.status, 0, ok.stderr);
  assert.equal(ok.out.counts.ammissibile, 1, 'a declared stage survives a manager title');
  assert.deepEqual(ok.out.excluded.map((e) => e.ground), ['senior-without-stage']);

  const bad = admit({ roles: [role({ stageNature: 'yes' })] });
  assert.equal(bad.status, 2);
  assert.match(bad.stderr, /roles\[0\]\.stageNature must be true or false/);
}

// ---------------------------------------------------------------------------
// `admit` promises to refuse and to report EVERY problem. Each case below used to
// pass silently or die with a stack trace, and the silent ones are the dangerous
// ones: a run with no admitted list reads as "0 excluded" with its language ground
// switched off.
// ---------------------------------------------------------------------------
{
  const langs = { requiredLanguages: ['Spanish', 'German'], languageRequirement: 'all' };

  // A required language with nothing to compare it against.
  const noList = admit({ roles: [role(langs)] });
  assert.equal(noList.status, 2);
  assert.match(noList.stderr, /roles\[0\]\.requiredLanguages .*admittedLanguages/);

  // Either level can supply the list, and a role with no requirement needs none.
  assert.equal(admit({ admittedLanguages: ['it', 'en'], roles: [role(langs)] }).out.counts.escluso, 1);
  assert.equal(admit({ roles: [role({ ...langs, admittedLanguages: ['it'] })] }).out.counts.escluso, 1);
  assert.equal(admit({ roles: [role({})] }).status, 0);

  // A level is refused here rather than quietly read as undeclared: the operator
  // can fix it, and the message says how.
  const level = admit({
    admittedLanguages: ['it'],
    roles: [role({ requiredLanguages: ['English C1'], languageRequirement: 'any' })],
  });
  assert.equal(level.status, 2);
  assert.match(level.stderr, /roles\[0\]\.requiredLanguages.*"English C1"/);
  assert.match(admit({ admittedLanguages: ['Elvish'], roles: [] }).stderr, /admittedLanguages.*"Elvish"/);

  // Wrong shapes are reported, not thrown.
  const shape = admit({ admittedLanguages: ['it'], roles: [role({ admittedLanguages: 'en', company: 42 })] });
  assert.equal(shape.status, 2);
  assert.match(shape.stderr, /roles\[0\]\.admittedLanguages must be an array/);
  assert.match(shape.stderr, /roles\[0\]\.company must be a string/);
  for (const text of ['null', '[]', '{ not json']) {
    const r = admit(text);
    assert.equal(r.status, 2, text);
    assert.match(r.stderr, /admit refused/, text);
    assert.doesNotMatch(r.stderr, /at .*\.js:\d+/, `no stack trace for ${text}`);
  }

  // Every problem at once, which is the contract.
  const many = admit({ roles: [{ title: '' }, { url: 'x' }] });
  assert.ok((many.stderr.match(/is required/g) ?? []).length >= 3, many.stderr);
}

console.log('cli-artifacts-smoke: OK (real CLI, both gates reach dropped.json + run-report.json)');
