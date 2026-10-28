'use strict';
const elem = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text != null) el.textContent = String(text);
  if (cls) el.className = cls;
  return el;
};
const finite = v => typeof v === 'number' && Number.isFinite(v);
const pct = v => finite(v) ? `${v >= 0 ? '+' : ''}${v.toFixed(3)}%` : 'Unavailable';
const pp = v => finite(v) ? `${v >= 0 ? '+' : ''}${v.toFixed(3)} pp` : 'Unavailable';
const num = v => finite(v) ? v.toFixed(3) : 'Undefined';
const price = v => finite(v) ? `$${v}` : 'Unavailable';
const label = v => v == null || v === '' ? 'Unavailable' : String(v);
const date = v => {
  if (!v || Number.isNaN(Date.parse(v))) return 'Unavailable';
  return new Intl.DateTimeFormat('en-US', {timeZone:'America/Chicago', dateStyle:'medium', timeStyle:'long'}).format(new Date(v));
};
const timestamp = v => v ? `${v} (${date(v)})` : 'Unavailable';
const ordered = rows => [...rows].sort((a,b) => {
  if (finite(a.score) !== finite(b.score)) return finite(a.score) ? -1 : 1;
  return (finite(a.score) ? b.score - a.score : 0) || a.symbol.localeCompare(b.symbol);
});
function paragraph(parent, text, cls) { parent.append(elem('p', text, cls)); }
function table(caption, heads, rows) {
  const wrap = elem('div', null, 'audit-table'), t = elem('table');
  t.append(elem('caption', caption));
  const h = elem('tr');
  heads.forEach(x => { const th = elem('th', x); th.scope = 'col'; h.append(th); });
  const head = elem('thead'); head.append(h); t.append(head);
  const body = elem('tbody');
  rows.forEach(row => { const tr = elem('tr'); row.forEach(x => tr.append(elem('td', x))); body.append(tr); });
  t.append(body); wrap.append(t); return wrap;
}
function bucketTable(p, key, title) {
  const a = p[key];
  return table(title, ['Original score bucket', 'Matched pairs', 'Mean return', 'Positive'],
    Object.entries(a.buckets).map(([k,v]) => [k, v.n, pct(v.mean_return_pct),
      v.n && finite(v.positive) ? `${v.positive} / ${v.n}` : 'Unavailable']));
}
function metric(parent, value, description) {
  const item = elem('div', null, 'audit-metric'); item.append(elem('strong', value), elem('span', description)); parent.append(item);
}
function displayEvidence(v) { return Array.isArray(v) ? (v.length ? v.join('; ') : 'None recorded') : label(v); }
function benchmarkTable(b, title) {
  return table(title, ['Score bucket', 'SPY matched pairs', 'Mean excess vs SPY', 'Sector matched pairs', 'Mean excess vs sector'],
    [['All scores', b.spy.matched_n, pp(b.spy.mean_excess_pp), b.sector.matched_n, pp(b.sector.mean_excess_pp)],
     ...Object.entries(b.buckets).map(([key,v]) => [key,v.spy.matched_n,pp(v.spy.mean_excess_pp),v.sector.matched_n,pp(v.sector.mean_excess_pp)])]);
}
function extraDiagnostics(parent, p) {
  if (p.post_publication_benchmarks) {
    parent.append(benchmarkTable(p.post_publication_benchmarks, 'Post-publication benchmark comparison'));
    paragraph(parent, 'Excess changes are percentage-point differences against matched SPY and sector-proxy windows, not alpha, fills or portfolio returns. Original-reference benchmark comparisons remain unavailable when exact timestamp matching is missing.');
  }
  const a=p.aligned_sensitivity;
  if (a) {
    const duration=(Date.parse(a.end_timestamp)-Date.parse(a.start_timestamp))/60000;
    parent.append(elem('h3',`Aligned ${Number.isFinite(duration)?duration:'unknown'}-minute sensitivity`));
    paragraph(parent, `${timestamp(a.start_timestamp)} to ${timestamp(a.end_timestamp)}. ${a.analysis.n} matched score/return pairs; mean ${pct(a.analysis.mean_return_pct)}; Spearman ${num(a.analysis.spearman)}. This common window is a separate sensitivity, not a replacement for original-reference results.`);
    parent.append(bucketTable({aligned:a.analysis},'aligned','Aligned-window score buckets'));
    parent.append(benchmarkTable(a.benchmarks,'Aligned-window benchmarks'));
  }
}
function renderAudit(d) {
  const root = document.getElementById('audit'); root.replaceChildren(); root.dataset.auditId = d.id;
  const intro = elem('section', null, 'audit-block');
  intro.append(elem('h2', `${d.market_date} · outcome review`));
  paragraph(intro, d.summary, 'audit-summary');
  paragraph(intro, `Analysis completed ${timestamp(d.analysis_completed_at)}. First reported ${timestamp(d.analysis_first_published_at)}. Website export created ${timestamp(d.website_export_created_at)}.`, 'audit-meta');
  paragraph(intro, `Audit ID: ${d.id}. This is not a new score assessment.`);
  paragraph(intro, d.method); paragraph(intro, d.endpoint_source);
  const primary = d.publications.find(p => p.id === d.primary_publication_id);
  if (primary) {
    const a = primary.original_reference_analysis, s = primary.post_publication_sensitivity;
    intro.append(elem('h3', `Primary diagnostic · ${date(primary.published_at)}`));
    paragraph(intro, `Assessment: ${timestamp(primary.assessment_timestamp)}. Publication: ${timestamp(primary.published_at)}. Cohort: ${label(primary.cohort)} · Rubric: ${label(primary.rubric_version || d.rubric_version)}. Scores from different rubrics or reference cohorts are not assumed comparable.`);
    const metrics = elem('div', null, 'audit-metrics');
    metric(metrics, `${a.n} / ${primary.rows.length}`, 'Matched score and return pairs');
    metric(metrics, num(a.spearman), 'Spearman rank correlation');
    metric(metrics, pct(a.mean_return_pct), 'Mean reference return');
    intro.append(metrics);
    paragraph(intro, 'Correlation describes this sample; it does not establish a trading edge. Undefined statistics are shown as such.');
    intro.append(bucketTable(primary, 'original_reference_analysis', 'Original-reference return by score bucket'));
    const lags = primary.rows.map(r => r.reference_to_publication_lag_seconds).filter(finite);
    paragraph(intro, `Original reference-to-publication lag: ${lags.length ? `${Math.min(...lags).toFixed(0)}–${Math.max(...lags).toFixed(0)} seconds (${lags.length} observations)` : 'Unavailable'}. ${label(d.delay)}`);
    paragraph(intro, `Post-publication sensitivity: ${s.n} matched pairs; Spearman ${num(s.spearman)}. This does not replace the original references or imply an executable fill.`);
    intro.append(bucketTable(primary, 'post_publication_sensitivity', 'Post-publication sensitivity by score bucket'));
    extraDiagnostics(intro,primary);
  }
  root.append(intro);
  const cohorts = elem('section', null, 'audit-block'); cohorts.append(elem('h2', 'Publication cohorts'));
  paragraph(cohorts, `${d.publications.length} saved publication windows. Windows for the same stocks may overlap and are not independent trials. Intraday, provisional and official-close cohorts remain distinct.`);
  cohorts.append(table('Saved publications', ['Scheduled target (Chicago)', 'Actual publication (Chicago)', 'Cohort', 'Rubric', 'Matched pairs', 'Reference Spearman', 'Sensitivity pairs', 'Sensitivity Spearman'], d.publications.map(p => [date(p.scheduled_target_houston), date(p.published_at), label(p.cohort), label(p.rubric_version || d.rubric_version), p.original_reference_analysis.n, num(p.original_reference_analysis.spearman), p.post_publication_sensitivity.n, num(p.post_publication_sensitivity.spearman)])));
  for (const p of d.publications) {
    const details = elem('details'); details.append(elem('summary', `${date(p.published_at)} · ${p.rows.length} original observations`));
    paragraph(details, `Assessment: ${timestamp(p.assessment_timestamp)}. Publication: ${timestamp(p.published_at)}. Cohort: ${label(p.cohort)}. Rubric: ${label(p.rubric_version || d.rubric_version)}. Historical observations are not current recommendations.`);
    details.append(bucketTable(p, 'original_reference_analysis', 'Original-reference bucket summary'));
    extraDiagnostics(details,p);
    const grid = elem('div', null, 'audit-card-grid');
    for (const r of ordered(p.rows)) {
      const card = elem('article', null, 'audit-stock');
      card.append(elem('h3', `${r.symbol} · ${finite(r.score) ? `${r.score} / 100` : 'Score unavailable'}`));
      if (finite(r.score) && (r.score_status === 'available_provisional' || (p.rubric_version || d.rubric_version) === 'buying-score-v2')) paragraph(card, 'Provisional evidence-based entry score.');
      if (r.score_status) paragraph(card, `Original score status: ${r.score_status}.`);
      if (p.cohort === 'v2-historical-official-close') paragraph(card, 'Historical observation; not a current entry score.');
      paragraph(card, `${pct(r.return_pct)} · original-reference price return`, finite(r.return_pct) ? (r.return_pct >= 0 ? 'positive' : 'negative') : '');
      paragraph(card, `Original reference ${price(r.reference_price)} · type: ${label(r.reference_price_type)} · source: ${label(r.reference_source)} · session: ${label(r.reference_session)}.`);
      paragraph(card, `Reference time: ${timestamp(r.reference_price_timestamp)}. Publication lag: ${finite(r.reference_to_publication_lag_seconds) ? `${r.reference_to_publication_lag_seconds.toFixed(3)} seconds` : 'Unavailable'}.`);
      paragraph(card, `End bar begins ${timestamp(r.end_bar_begins_at)}; bar close ${price(r.end_bar_close)}.`);
      paragraph(card, `Sensitivity start ${timestamp(r.post_publication_start_bar)}, open ${price(r.post_publication_start_open)}; return ${pct(r.post_publication_return_pct)}. Not an executable fill.`);
      paragraph(card, `Alternate quote endpoint ${price(r.quote_endpoint_price)} at ${timestamp(r.quote_endpoint_timestamp)}; return ${pct(r.quote_endpoint_return_pct)}.`);
      if ('aligned_return_pct' in r) paragraph(card, `Aligned window: ${pct(r.aligned_return_pct)} from ${timestamp(r.aligned_start_bar)} at ${price(r.aligned_start_open)}. Sector proxy: ${label(r.sector_benchmark)}. Post-publication excess: SPY ${pp(r.post_publication_spy_excess_pp)}, sector ${pp(r.post_publication_sector_excess_pp)}. Aligned excess: SPY ${pp(r.aligned_spy_excess_pp)}, sector ${pp(r.aligned_sector_excess_pp)}.`);
      if (r.missing_evidence != null) paragraph(card, `Missing evidence: ${displayEvidence(r.missing_evidence)}.`);
      grid.append(card);
    }
    details.append(grid); cohorts.append(details);
  }
  root.append(cohorts);
  const limits = elem('section', null, 'audit-block'); limits.append(elem('h2', 'Evidence and limitations'));
  paragraph(limits, d.benchmark_status);
  const o = d.official_close_audit;
  if (o) paragraph(limits, `Official-close matured pairs: ${label(o.matured_one_session_n)} for one session, ${label(o.matured_five_session_n)} for five sessions. Mean return ${pct(o.mean_return_pct)}; Spearman ${num(o.spearman)}. ${label(o.status)}`);
  const ledger=d.official_close_details;
  if(ledger){
    paragraph(limits, `${ledger.original_records} immutable official-close observations: ${ledger.valid_reference_n} valid original references, ${ledger.unavailable_original_n} unavailable originals, ${ledger.pending_valid_reference_n} pending valid references. Later prices never repair a missing original.`);
    limits.append(table('Official-close cohorts remain separate',['Rubric','Original dates','Original records','Valid references','Unavailable'],ledger.rubric_cohorts.map(c=>[c.rubric,c.dates.join(', '),c.original_records,c.valid_reference_n,c.unavailable_n])));
    paragraph(limits, `Public-history gap: ${ledger.public_history_gap.record_count} records (${ledger.public_history_gap.dates.join(', ')}). ${ledger.public_history_gap.note}`);
  }
  const ul = elem('ul'); (d.limitations || []).forEach(x => ul.append(elem('li', x))); limits.append(ul);
  const qa = d.endpoint_qa;
  if (qa) {
    paragraph(limits, `Endpoint QA: ${label(qa.genuine_final_bars)} genuine final bars; ${label(qa.excluded_interpolated_bars)} interpolated bars excluded. ${label(qa.note)}`);
    for (const q of qa.minute_quote_mismatches || []) paragraph(limits, `${q.symbol}: minute close ${price(q.minute_close)} versus quote ${price(q.quote_last_trade)} at ${timestamp(q.quote_timestamp)}.`);
  }
  root.append(limits);
  const c = d.closing_review;
  if (c) {
    const close = elem('section', null, 'audit-block'); close.append(elem('h2', 'Closing report · retrospective review'));
    paragraph(close, c.summary, 'audit-summary');
    paragraph(close, `Original assessment ${timestamp(c.original_assessment_timestamp)}; publication ${timestamp(c.original_publication_timestamp)}; later annotation ${timestamp(c.annotation_first_published_at)}. Original records remain unchanged.`, 'audit-meta');
    if (/^[a-zA-Z0-9_-]+$/.test(c.original_publication_id)) { const a = elem('a', 'Read the immutable original closing report'); a.href = `data/watch-history/${c.original_publication_id}.json`; close.append(a); }
    for (const x of c.corrections || []) {
      close.append(elem('h3', x.topic)); paragraph(close, x.statement);
      for (const s of x.sources || []) { try { if (new URL(s).protocol !== 'https:') continue; const link = elem('a', 'Primary source'); link.href = s; link.rel = 'noopener noreferrer'; close.append(link, document.createTextNode(' ')); } catch {} }
    }
    const gaps = elem('details'); gaps.append(elem('summary', `${c.records.length} original closing observations`));
    gaps.append(table('Original closing coverage', ['Ticker', 'Buying score', 'Reference', 'Status'], c.records.map(r => [r.symbol, finite(r.score) ? `${r.score} / 100` : 'Unavailable', price(r.reference_price), label(r.status)])));
    close.append(gaps); root.append(close);
  }
}
let version = 0;
async function loadAudit(item) {
  const v = ++version; document.getElementById('status').textContent = 'Loading saved audit…';
  try {
    if (!item || !/^data\/outcomes\/[a-z0-9-]+\.json$/.test(item.path)) throw Error('Path');
    const response = await fetch(item.path, {cache:'no-store'}); if (!response.ok) throw Error('Unavailable');
    const d = await response.json(); if (![1,2].includes(d.schema_version) || d.id !== item.id) throw Error('Identity');
    if (v !== version) return;
    renderAudit(d); document.getElementById('status').textContent = 'Saved audit loaded. No scores, prices or monitoring timestamps were refreshed.';
  } catch { if (v === version) { clearAudit(); document.getElementById('status').textContent = 'Audit could not be loaded.'; } }
}
function clearAudit() {
  const root = document.getElementById('audit'); root.replaceChildren(); delete root.dataset.auditId;
}
async function init() {
  const select = document.getElementById('audit-date'), status = document.getElementById('status');
  try {
    const response = await fetch('data/outcomes/index.json', {cache:'no-store'}); if (!response.ok) throw Error();
    const data = await response.json(); if (!Array.isArray(data.audits)) throw Error('Invalid catalog');
    const items = [...data.audits].reverse();
    for (const item of items) { const option = elem('option', `${item.market_date} · ${item.id}`); option.value = item.id; select.append(option); }
    if (!items.length) { select.disabled = true; clearAudit(); status.textContent = 'No outcome audits published.'; return; }
    function restoreSelection() {
      const requested = new URL(window.location.href).searchParams.get('audit');
      const item = requested === null ? items[0] : items.find(x => x.id === requested);
      if (!item) {
        ++version; select.value = ''; clearAudit(); status.textContent = 'The requested audit is not in the published catalog.'; return;
      }
      select.value = item.id; loadAudit(item);
    }
    select.addEventListener('change', () => {
      const item = items.find(x => x.id === select.value); if (!item) return;
      const url = new URL(window.location.href); url.searchParams.set('audit', item.id);
      window.history.pushState(null, '', url); loadAudit(item);
    });
    window.addEventListener('popstate', restoreSelection);
    restoreSelection();
  } catch { select.disabled = true; clearAudit(); status.textContent = 'Audit catalog unavailable.'; }
}
init();
