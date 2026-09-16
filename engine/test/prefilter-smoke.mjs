// node test/prefilter-smoke.mjs
import { strict as assert } from 'node:assert';
import { prefilter } from '../lib/prefilter.js';

const cards = [
  { title: 'Service Design Intern — Milan', company: 'ACME', location: 'Milan', url: 'https://x/1', snippet: 'journey mapping, service blueprint, 6-month curricular internship', source: 'linkedin', discoveryQuery: 'service design' },
  { title: 'Senior Service Design Manager', company: 'ACME', location: 'Milan', url: 'https://x/2', snippet: 'lead a team of designers, 8 years experience', source: 'linkedin', discoveryQuery: 'service design' },
  { title: 'Customer Service Agent', company: 'ACME', location: 'Milan', url: 'https://x/3', snippet: 'handle complaints and reception calls', source: 'linkedin', discoveryQuery: 'service design' },
  { title: 'UX Research Intern', company: 'ACME', location: 'Milan', url: 'https://x/4', snippet: 'user interviews, usability testing, wireframes', source: 'linkedin', discoveryQuery: 'ux' },
];
const { kept, dropped } = prefilter(cards, {
  falseFriends: ['customer service agent', 'reception'],
  queryTerms: ['service design', 'journey', 'blueprint', 'user research', 'usability'],
  topK: 2,
});
assert.equal(kept.length, 2);
assert.equal(dropped.length, 2);
assert.ok(kept[0].card.title.includes('Intern'), `top kept should be an intern role, got: ${kept[0].card.title}`);
assert.ok(dropped.some((d) => d.card.title.includes('Senior')), 'senior role should be dropped');
console.log('prefilter-smoke: OK');
