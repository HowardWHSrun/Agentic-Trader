'use strict';
const byId=id=>document.getElementById(id);
const el=(tag,value,cls)=>{const n=document.createElement(tag);if(value!=null)n.textContent=value;if(cls)n.className=cls;return n;};
function timestamp(value){const d=new Date(value);return value&&Number.isFinite(d.getTime())?new Intl.DateTimeFormat('en-US',{timeZone:'America/Chicago',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZoneName:'short'}).format(d):'Not published';}
function safeUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:null;}catch{return null;}}
let rows=[], latestReview=null, selectedId=null, loadVersion=0;
const reviews=new Map();
function evidenceSummary(record) {
  if (record.rubric_version !== 'buying-score-v2') return null;
  try { return BuyingScoreV2.summarize(record.evidence_checks); } catch { return null; }
}
function scoreValue(record) {
  if (record.rubric_version !== 'buying-score-v2') return record.score;
  const summary=evidenceSummary(record);
  return record.score!==null && summary && record.score===summary.score ? summary.score : null;
}
const sortedRecords=records=>[...records].sort((a,b)=>(scoreValue(a)===null)-(scoreValue(b)===null)||(scoreValue(b)??0)-(scoreValue(a)??0)||a.symbol.localeCompare(b.symbol));
function reviewCounts(review){const n=review.records.filter(r=>scoreValue(r)!==null).length;return n+(review.rubric_version==='buying-score-v2'?' provisionally scored · ':' scored · ')+(review.records.length-n)+' unavailable';}
function cohortLabel(value){return String(value||'Unspecified cohort').replaceAll('_',' ').replaceAll('-',' ');}
function selectReview(review){
  selectedId=review.id;rows=sortedRecords(review.records);const historical=review.id!==latestReview?.id;
  byId('view-label').textContent=historical?'Historical assessment · original evidence':'Latest published assessment';
  byId('assessment-title').textContent=cohortLabel(review.cohort);
  byId('view-context').textContent=(historical?'Historical snapshot. Not a current entry recommendation. ':'Saved snapshot, not live prices. ')+'Published '+timestamp(review.publication_timestamp)+' · Assessed '+timestamp(review.assessment_snapshot)+' · '+reviewCounts(review)+' · '+review.rubric_version+'. Each price retains its own original time and session.'+(review.rubric_version==='buying-score-v2'?' Provisional evidence-based entry scores; not directly comparable with v1 or probabilities of profit.':'')+(review.cohort==='v2-historical-official-close'?' Historical observation assessed now from a dated official close; no current-entry implication.':'');
  byId('view-context').classList.toggle('historical',historical);
  byId('return-latest').hidden=!historical;byId('summary').textContent=review.summary;
  for(const button of byId('history').querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.reviewId===selectedId));
  cards();
}
async function historyEntry(item,version){
  if(!/^data\/watch-history\/[A-Za-z0-9_-]+\.json$/.test(item.path))return;
  const entry=el('article',null,'history-entry');const button=el('button',null,'history-select');button.dataset.reviewId=item.id;button.setAttribute('aria-pressed',String(item.id===selectedId));
  button.append(el('strong',timestamp(item.publication_timestamp)),el('span','Loading original review…','history-meta'));button.disabled=true;
  const raw=el('a','Original JSON');raw.href=item.path;raw.className='raw-link';entry.append(button,raw);byId('history').append(entry);
  try{let review=reviews.get(item.id);if(!review){const response=await fetch(item.path,{cache:'no-store'});if(!response.ok)throw new Error('History unavailable');review=await response.json();if(review.id!==item.id||!Array.isArray(review.records)||review.publication_timestamp!==item.publication_timestamp)throw new Error('History identity mismatch');reviews.set(item.id,review);}if(version!==loadVersion)return;
    button.lastChild.textContent=cohortLabel(review.cohort)+' · '+[...new Set(review.records.map(r=>r.reference_session).filter(Boolean))].join(' / ')+' · '+reviewCounts(review);button.disabled=false;
    button.addEventListener('click',()=>{selectReview(review);byId('assessment-title').scrollIntoView({behavior:'auto',block:'start'});});
  }catch{if(version===loadVersion)button.lastChild.textContent='Review could not be loaded. Use the original JSON link or refresh.';}
}

function appendEvidence(card, record, summary, value) {
  const section=el('section',null,'evidence-overview');
  if (!summary) { section.append(el('p','Evidence checklist is invalid or unavailable; no v2 number can be displayed.'));card.append(section);return; }
  section.append(el('strong','Evidence coverage: '+summary.coverage+'% · '+(summary.counts.pass+summary.counts.fail)+'/20 resolved'));
  section.append(el('p',summary.counts.pass+' pass · '+summary.counts.fail+' fail · '+summary.counts.unknown+' unknown · '+summary.unresolved+' unresolved points'));
  if (value!==null) section.append(el('p','Conditional completion range: '+value+'–'+(value+summary.unresolved)+'/100, assuming evaluated checks stay unchanged. Not a confidence interval or probability of profit.'));
  else section.append(el('p',record.score!==null?'Checklist arithmetic does not support the supplied score; numeric display withheld.':summary.score===null?'All twenty checks are unknown; no numeric score.':'A numeric score is withheld by the core evidence gates. Coverage is not entry eligibility.'));
  section.append(el('p','Unknown receives no verified credit and is not a negative business finding. Screening heuristics are not validated edges or personal risk limits.'));
  card.append(section);
}
function appendChecklist(details, record) {
  const list=el('ol',null,'evidence-checks');
  const checks=new Map(record.evidence_checks.map(c=>[c.id,c]));
  for (const definition of BuyingScoreV2.CHECKS) {
    const check=checks.get(definition.id), item=el('li');
    item.append(el('strong',definition.id+' · '+check.status.toUpperCase()),el('p',definition.label),el('p',check.evidence));
    item.append(el('p',check.observed_at?'Observed: '+timestamp(check.observed_at):'Observation time unavailable.','quote'));
    const url=safeUrl(check.source_url);
    if(url){const link=el('a','Check evidence');link.href=url;link.rel='noopener noreferrer';item.append(link);}
    list.append(item);
  }
  details.append(list);
}
function cards(){
  const query=byId('search').value.trim().toLowerCase();let shown=0;byId('scores').replaceChildren();
  for(const r of rows){
    if(query&&!JSON.stringify(r).toLowerCase().includes(query))continue;
    shown++;
    const value=scoreValue(r),v2=r.rubric_version==='buying-score-v2',summary=evidenceSummary(r);
    const provisional=v2||r.score_status==='available_provisional';
    const card=el('article',null,'stock'+(value===null?' unavailable':provisional?' provisional':''));
    const top=el('div',null,'stock-top');
    const score=el('div',value===null?'Unavailable':String(value),'score');
    score.append(el('small',value===null?'No numeric buying score':v2?'/ 100 · Provisional evidence-based entry score':provisional?'/ 100 · Provisional v1 buying score':'/ 100 · buying score'));
    const heading=el('div');heading.append(el('h2',r.symbol),el('p',r.rubric_version+' · '+cohortLabel(r.cohort),'quote'));
    const quote=r.reference_price===null?'No sufficiently current price reference':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(r.reference_price)+' · '+r.reference_price_type;
    heading.append(el('p',quote,'quote'));top.append(score,heading);card.append(top);
    if(r.cohort==='v2-historical-official-close')card.append(el('p','Historical observation. Dated official close; assessed now. Not a current entry score.','view-context historical'));
    card.append(el('p',r.reference_price_timestamp?timestamp(r.reference_price_timestamp)+' · '+r.reference_session+' · '+r.reference_source+' · Delay: '+r.quote_delay:r.missing_evidence,'quote'));
    if(v2)appendEvidence(card,r,summary,value);
    card.append(el('p',r.reason,'reason'));
    const action=el('p',null,'action');action.append(el('strong','Conditional action plan'),document.createTextNode(r.conditional_action));card.append(action);
    if(r.improvement_condition)card.append(el('p','What would improve it: '+r.improvement_condition,'improvement'));
    const details=el('details');details.append(el('summary','Evidence, limitations & sources'));
    if(v2&&summary)appendChecklist(details,r);
    if(r.event)details.append(el('p',typeof r.event==='string'?r.event:'Event: '+Object.entries(r.event).map(([k,v])=>k+': '+v).join(' · ')));
    const components=v2?summary?.component_scores:r.component_scores;
    if(components)details.append(el('p','Components: '+Object.entries(components).map(([k,v])=>k.replaceAll('_',' ')+' '+v).join(' · ')));
    const gaps=el('ul');for(const gap of r.evidence_limitations||[])gaps.append(el('li',gap));
    details.append(gaps,el('p','Sizing: '+r.sizing));
    const sources=el('div',null,'sources');
    for(const [i,s] of (r.sources||[]).entries()){const url=safeUrl(typeof s==='string'?s:s.url);if(url){const a=el('a',typeof s==='string'?'Source '+(i+1):s.title);a.href=url;a.rel='noopener noreferrer';sources.append(a);}}
    details.append(sources);card.append(details);byId('scores').append(card);
  }
  byId('result-count').textContent=shown+' of '+rows.length+' stocks shown · Ranked within this rubric/cohort, unavailable last';
  if(!shown)byId('scores').append(el('p','No stocks match this search. Clear the search to see the full review.','empty'));
}
function render(data){if(data.schema_version!==2)throw new Error('Unsupported schema');const h=data.last_hard_check;const s=data.last_soft_check;latestReview=h;const priorSelection=selectedId;rows=h?sortedRecords(h.records):[];if(h)reviews.set(h.id,h);byId('hard-time').textContent=timestamp(h?.publication_timestamp);byId('hard-detail').textContent=h?'Assessment '+timestamp(h.assessment_snapshot)+'. Price timestamps remain individually labeled below.':'No completed check has been published.';byId('soft-time').textContent=timestamp(s?.checked_at);byId('soft-detail').textContent=s?s.status+' · '+s.summary+' '+s.coverage:'No soft-check timestamp has been published here. This does not establish continuous monitoring.';byId('coverage').textContent=rows.filter(r=>scoreValue(r)!==null).length+' scored / '+rows.length;byId('coverage-detail').textContent=(rows.length-rows.filter(r=>scoreValue(r)!==null).length)+' scores unavailable. '+rows.length+' assessment records; this is not a live-quote coverage count.';byId('summary').textContent=h?.summary||'No published assessment.';byId('schedule').textContent=data.schedule.hard_checks+' Soft checks: '+data.schedule.soft_checks+' '+data.schedule.controller;byId('history').replaceChildren();byId('history-count').textContent=(data.score_history||[]).length+' saved reviews';for(const item of [...(data.score_history||[])].reverse())historyEntry(item,loadVersion);byId('alerts').replaceChildren();byId('alerts-section').hidden=!(data.alerts||[]).length;for(const a of data.alerts||[]){const item=el('article',null,'stock');item.append(el('h2',a.ticker+' · '+a.name),el('p',timestamp(a.published_at),'quote'));for(const key of ['summary','entry','invalidation','risks','conclusion'])if(a[key])item.append(el('p',key+': '+a[key]));for(const source of a.sources||[]){const url=safeUrl(source.url);if(url){const link=el('a',source.title);link.href=url;link.rel='noopener noreferrer';item.append(link);}}byId('alerts').append(item);}byId('load-status').textContent='Loaded saved publication. Refresh does not initiate research or update quote timestamps.';if(h)selectReview(reviews.get(priorSelection)||h);else cards();}
async function load(){loadVersion++;byId('refresh').disabled=true;try{const response=await fetch('data/watch.json',{cache:'no-store'});if(!response.ok)throw new Error('HTTP '+response.status);render(await response.json());}catch{byId('load-status').textContent='Latest published data could not be loaded. Any visible data is from the prior load, not a new check.';}finally{byId('refresh').disabled=false;}}
byId('return-latest').addEventListener('click',()=>{if(latestReview)selectReview(latestReview);});
byId('refresh').addEventListener('click',load);byId('search').addEventListener('input',cards);load();
