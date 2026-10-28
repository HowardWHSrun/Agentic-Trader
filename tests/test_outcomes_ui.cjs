'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.textContent = ''; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
}
const roots = {audit: new Element('main'), status: new Element('p')};
const document = {createElement: tag => new Element(tag), createTextNode: text => ({textContent: text, children: []}), getElementById: id => roots[id]};
const source = fs.readFileSync(path.join(root, 'docs/outcomes.js'), 'utf8').replace(/\ninit\(\);\s*$/, '');
const context = vm.createContext({document, URL});
vm.runInContext(source + '\nthis.renderAudit = renderAudit;', context);
const contents = el => (el.textContent || '') + ' ' + (el.children || []).map(contents).join(' ');
const legacy = JSON.parse(fs.readFileSync(path.join(root, 'docs/data/outcomes/2026-10-21-intraday-audit-v1.json'), 'utf8'));
context.renderAudit(legacy);
let text = contents(roots.audit);
assert.match(text, /7 saved publication windows/);
assert.match(text, /32 \/ 32/);
assert.match(text, /2026-10-21/);
assert.match(text, /Assessment: Unavailable/);
const v2 = JSON.parse(JSON.stringify(legacy));
v2.schema_version = 2;
v2.publications = v2.publications.slice(0, 1);
v2.primary_publication_id = v2.publications[0].id;
const p = v2.publications[0];
p.cohort = 'v2-official-close'; p.rubric_version = 'buying-score-v2'; p.assessment_timestamp = '2026-10-21T13:00:30Z';
p.original_reference_analysis.n = 0; p.original_reference_analysis.spearman = null; p.original_reference_analysis.mean_return_pct = null;
p.post_publication_sensitivity.n = 0; p.post_publication_sensitivity.spearman = null;
for (const b of Object.values(p.original_reference_analysis.buckets)) { b.n = 0; b.positive = null; b.mean_return_pct = null; }
for (const r of p.rows) {
  for (const key of ['score', 'reference_price', 'reference_price_timestamp', 'reference_price_type', 'reference_source', 'reference_to_publication_lag_seconds', 'end_bar_begins_at', 'end_bar_close', 'return_pct', 'post_publication_start_bar', 'post_publication_start_open', 'post_publication_return_pct', 'quote_endpoint_price', 'quote_endpoint_timestamp', 'quote_endpoint_return_pct']) r[key] = null;
  r.score_status = 'unavailable'; r.reference_session = null; r.missing_evidence = ['Reference unavailable'];
}
context.renderAudit(v2); text = contents(roots.audit);
assert.match(text, /0 \/ 32/);
assert.match(text, /Score unavailable/);
assert.match(text, /Reference unavailable/);
assert.match(text, /v2-official-close/);
assert.match(text, /Assessment: 2026-10-21T13:00:30Z/);
assert.doesNotMatch(text, /\$null|NaN/);
console.log('Legacy and nullable v2 outcome rendering passed');
