// node test/indeed-smoke.mjs — A4's Indeed line.
//
// `observe.ts::indeedLine` implemented A4's `X = Y + Z + P` invariant and its
// throw-on-mismatch was real, but nothing called it: the line was written by
// hand, so the arithmetic A4 makes mandatory was never actually checked. The
// `indeed` subcommand is its caller. The agent computes the line rather than
// composing it, which is the only arrangement in which the check runs.
import { strict as assert } from 'node:assert';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const CLI = join(dirname(fileURLToPath(import.meta.url)), '..', 'lib', 'cli.js');
const run = (...args) => spawnSync('node', [CLI, 'indeed', ...args], { encoding: 'utf8' });

// A4 §58: the line is Italian, while the Used/Unavailable states stay English.
{
  const p = run('--status', 'Used', '--x', '12', '--y', '5', '--z', '7');
  assert.equal(p.status, 0, p.stderr);
  assert.equal(
    p.stdout.trim(),
    'Indeed: Used; candidati unici trovati 12; inclusi nel TSV 5; duplicati o esclusi 7',
  );
}

// P is the unresolved-outside-the-TSV term, named separately in A4 §60.
{
  const p = run('--status', 'Used', '--x', '12', '--y', '5', '--z', '5', '--p', '2');
  assert.equal(p.status, 0, p.stderr);
  assert.ok(p.stdout.includes('non risolti 2'), p.stdout);
}

// The invariant, which is the whole reason this command exists: arithmetic that
// does not balance must not ship.
{
  const p = run('--status', 'Used', '--x', '12', '--y', '5', '--z', '6');
  assert.equal(p.status, 1, 'bad arithmetic must fail the command, not print a line');
  assert.match(p.stderr, /Indeed invariant violated/);
  assert.match(p.stderr, /X\(12\) != Y\(5\) \+ Z\(6\) \+ P\(0\)/);
}

// Unavailable: A4 asks for the reason, so the note has to survive.
{
  const p = run('--status', 'Unavailable', '--x', '0', '--y', '0', '--z', '0', '--note', '403 dal client');
  assert.equal(p.status, 0, p.stderr);
  assert.ok(p.stdout.startsWith('Indeed: Unavailable;'), p.stdout);
  assert.ok(p.stdout.includes('(403 dal client)'), p.stdout);
}

console.log('indeed-smoke: OK (A4 line format, P term, invariant enforced, note carried)');
