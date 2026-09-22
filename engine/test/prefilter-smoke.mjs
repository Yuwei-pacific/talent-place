// node test/prefilter-smoke.mjs
import { strict as assert } from 'node:assert';
import { prefilter } from '../lib/prefilter.js';

const cards = [
  { title: 'Service Design Intern — Milan', company: 'ACME', location: 'Milan', url: 'https://x/1', snippet: 'journey mapping, service blueprint, 6-month curricular internship', source: 'linkedin', discoveryQuery: 'service design' },
  { title: 'Senior Service Design Manager', company: 'ACME', location: 'Milan', url: 'https://x/2', snippet: 'lead a team of designers, 8 years experience', source: 'linkedin', discoveryQuery: 'service design' },
  { title: 'Customer Service Agent', company: 'ACME', location: 'Milan', url: 'https://x/3', snippet: 'handle complaints and reception calls', source: 'linkedin', discoveryQuery: 'service design' },
  { title: 'UX Research Intern', company: 'ACME', location: 'Milan', url: 'https://x/4', snippet: 'user interviews, usability testing, wireframes', source: 'linkedin', discoveryQuery: 'ux' },
];
const { kept, dropped, falseFriendHits } = prefilter(cards, {
  falseFriends: ['customer service agent', 'reception'],
  queryTerms: ['service design', 'journey', 'blueprint', 'user research', 'usability'],
  topK: 2,
});
assert.equal(kept.length, 2);
assert.equal(dropped.length, 2);
assert.ok(kept[0].card.title.includes('Intern'), `top kept should be an intern role, got: ${kept[0].card.title}`);
assert.ok(dropped.some((d) => d.card.title.includes('Senior')), 'senior role should be dropped');

// Every term is counted, so a term that matches nothing is visible.
assert.equal(falseFriendHits['customer service agent'], 1, 'one card carries that title');
assert.equal(falseFriendHits['reception'], 1, 'one card mentions reception in its snippet');

// A2 states its false positives as sentences about situations, and a sentence
// wrapped in \b...\b can never match a title or snippet. Populating the list with
// one therefore scores nothing down while looking like it does. The count is what
// turns that from silent into reported.
const sentence = 'Un CX Intern che gestisce chiamate senza analisi è un falso positivo.';
const inert = prefilter(cards, {
  falseFriends: ['customer service agent', sentence],
  queryTerms: ['service design'],
  topK: 4,
});
assert.equal(inert.falseFriendHits[sentence], 0, 'a sentence-shaped entry matches nothing');
assert.equal(inert.falseFriendHits['customer service agent'], 1, 'the term-shaped entry still works');
console.log('prefilter-smoke: OK');
