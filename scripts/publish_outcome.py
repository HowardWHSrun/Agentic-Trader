"""Append a reviewed, public-only descriptive outcome audit; never edit watch data."""
import json, math, pathlib, re, sys
from datetime import datetime
ROOT = pathlib.Path(__file__).resolve().parents[1]
UNIVERSE = set('AAPL AVGO CRM MSFT NVDA GOOGL META AMZN HD COST KO PG WMT ABBV LLY UNH BAC JPM V CVX XOM CAT DE GE RTX DUK NEE FCX LIN PLD TSLA SPCX'.split())
TOP = set('schema_version id market_date analysis_completed_at analysis_first_published_at website_export_created_at timezone rubric_version weights new_score_assessment summary method primary_publication_id endpoint_source delay benchmark_excess_return benchmark_status official_close_audit limitations endpoint_qa publications closing_review sizing'.split())
ROW = set('symbol score reference_price reference_price_timestamp reference_price_type reference_source reference_to_publication_lag_seconds end_bar_begins_at end_bar_close return_pct post_publication_start_bar post_publication_start_open post_publication_return_pct quote_endpoint_price quote_endpoint_timestamp quote_endpoint_return_pct'.split())
def exact(d, keys):
 if not isinstance(d,dict) or set(d)!=set(keys): raise ValueError('Unexpected or missing fields')
def timestamp(v):
 # Python 3.9 accepts at most six fractional digits; preserve timezone while
 # parsing higher-precision source timestamps without modifying the export.
 if not isinstance(v, str): raise ValueError('Timestamp required')
 value = re.sub(r'(\.\d{6})\d+(?=Z|[+-]\d{2}:\d{2}$)', r'\1', v)
 parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
 if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError('Timezone required')
 return parsed
def validate(d):
 exact_optional(d,TOP,{'official_close_details'} if d.get('schema_version')==2 else set())
 if d['schema_version'] not in (1, 2) or d['new_score_assessment'] is not False: raise ValueError('Not an outcome audit')
 if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[a-z0-9-]+',d['id']): raise ValueError('Invalid ID')
 for k in ['analysis_completed_at','analysis_first_published_at','website_export_created_at']: timestamp(d[k])
 if d['weights']!=[30,25,20,10,15] or d['rubric_version'] not in (('buying-score-v1',) if d['schema_version']==1 else ('buying-score-v1','buying-score-v2')): raise ValueError('Rubric changed')
 if d['sizing']!='Sizing is not provided on this public market-research page.': raise ValueError('Sizing not public')
 exact(d['official_close_audit'],'matured_one_session_n matured_five_session_n spearman mean_return_pct status'.split())
 exact(d['endpoint_qa'],'minute_quote_mismatches genuine_final_bars excluded_interpolated_bars note'.split())
 for r in d['endpoint_qa']['minute_quote_mismatches']: exact(r,'symbol minute_close quote_last_trade quote_timestamp'.split())
 if d['schema_version']==2:
  validate_v2(d)
  return check_privacy(d)
 ids=[]
 for p in d['publications']:
  exact(p,'id published_at cohort original_reference_analysis post_publication_sensitivity rows'.split());timestamp(p['published_at']);ids.append(p['id'])
  if len(p['rows'])!=32 or {r['symbol'] for r in p['rows']}!=UNIVERSE: raise ValueError('All 32 required')
  for analysis in ['original_reference_analysis','post_publication_sensitivity']:
   a=p[analysis];exact(a,'n spearman mean_return_pct buckets'.split());exact(a['buckets'],['0-19','20-39','40-59','60-79','80-100'])
   if a['n']!=32: raise ValueError('Sample mismatch')
   for b in a['buckets'].values():exact(b,'n mean_return_pct positive'.split())
  for r in p['rows']:
   exact(r,ROW)
   if r['score'] not in range(0,101,5): raise ValueError('Score invalid')
   for k in ['reference_price_timestamp','end_bar_begins_at','post_publication_start_bar','quote_endpoint_timestamp']:timestamp(r[k])
   expected=(r['end_bar_close']/r['reference_price']-1)*100
   if abs(expected-r['return_pct'])>1e-8:raise ValueError('Return mismatch')
 if len(ids)!=len(set(ids)) or d['primary_publication_id'] not in ids: raise ValueError('Publication IDs')
 c=d['closing_review'];exact(c,'original_publication_id original_publication_timestamp original_assessment_timestamp annotation_first_published_at new_score_assessment summary corrections records'.split())
 if c['new_score_assessment'] is not False:raise ValueError('Not a new assessment')
 for k in ['original_publication_timestamp','original_assessment_timestamp','annotation_first_published_at']:timestamp(c[k])
 for r in c['corrections']:exact(r,'topic statement sources'.split())
 if len(c['records'])!=32 or {r['symbol'] for r in c['records']}!=UNIVERSE:raise ValueError('Closing coverage')
 for r in c['records']:
  exact(r,'symbol score reference_price status'.split())
  if r['score'] is not None or r['reference_price'] is not None:raise ValueError('Unavailable reference required')
 return check_privacy(d)

def check_privacy(d):
 text=json.dumps(d,allow_nan=False)
 if any(x in text.lower() for x in ['/workspace/','sentinel_','account_id','cost_basis','access_token','private_key','settled_cash']): raise ValueError('Private content detected')
 return d


# Schema 2 keeps all 32 original observations, including unavailable ones.
# Missing values remain null; sample sizes describe score/return pairs, not rows.
V2_ROW = ROW | {'score_status', 'missing_evidence', 'reference_session'}
V2_PUBLICATION = set('id published_at assessment_timestamp cohort rubric_version original_reference_analysis post_publication_sensitivity rows'.split())
BUCKETS = ('0-19', '20-39', '40-59', '60-79', '80-100')

def number(value, name, *, positive=False):
 if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or (positive and value <= 0):
  raise ValueError(f'Invalid {name}')
 return value

def optional_timestamp(value):
 if value is not None: timestamp(value)

def check_return(row, result, numerator, denominator):
 value = row[result]
 if value is None: return
 number(value, result)
 if row[numerator] is None or row[denominator] is None: raise ValueError(f'{result} requires both prices')
 expected = (row[numerator] / row[denominator] - 1) * 100
 if not math.isclose(expected, value, rel_tol=1e-9, abs_tol=1e-8): raise ValueError(f'{result} mismatch')

def bucket(score):
 return BUCKETS[min(score // 20, 4)]

def ranks(values):
 order=sorted(range(len(values)), key=values.__getitem__)
 result=[0.0]*len(values)
 i=0
 while i<len(order):
  j=i+1
  while j<len(order) and values[order[j]]==values[order[i]]: j+=1
  rank=(i+1+j)/2
  for pos in order[i:j]: result[pos]=rank
  i=j
 return result

def check_analysis(analysis, rows, return_field):
 exact(analysis, 'n spearman mean_return_pct buckets'.split())
 exact(analysis['buckets'], BUCKETS)
 pairs = [(r['score'], r[return_field]) for r in rows if r['score'] is not None and r[return_field] is not None]
 if type(analysis['n']) is not int or analysis['n'] != len(pairs): raise ValueError('Sample mismatch')
 mean = analysis['mean_return_pct']
 if not pairs:
  if mean is not None or analysis['spearman'] is not None: raise ValueError('Empty sample statistics must be null')
 else:
  number(mean, 'mean_return_pct')
  if not math.isclose(mean, sum(y for _,y in pairs)/len(pairs), rel_tol=1e-9, abs_tol=1e-8): raise ValueError('Mean mismatch')
 correlation = analysis['spearman']
 undefined = len(pairs)<2 or len({x for x,_ in pairs})<2 or len({y for _,y in pairs})<2
 if undefined and correlation is not None: raise ValueError('Undefined rank correlation must be null')
 if not undefined and correlation is None: raise ValueError('Defined rank correlation required')
 if correlation is not None:
  if not -1 <= number(correlation, 'spearman') <= 1: raise ValueError('Invalid rank correlation')
  x=ranks([x for x,_ in pairs]); y=ranks([y for _,y in pairs]); xmean=sum(x)/len(x); ymean=sum(y)/len(y)
  num=sum((a-xmean)*(b-ymean) for a,b in zip(x,y))
  den=math.sqrt(sum((a-xmean)**2 for a in x)*sum((b-ymean)**2 for b in y))
  if not math.isclose(correlation, num/den, rel_tol=1e-9, abs_tol=1e-8): raise ValueError('Rank correlation mismatch')
 for name in BUCKETS:
  b=analysis['buckets'][name]; exact(b, 'n mean_return_pct positive'.split())
  values=[y for x,y in pairs if bucket(x)==name]
  if type(b['n']) is not int or b['n'] != len(values): raise ValueError('Bucket sample mismatch')
  if type(b['positive']) is not int or b['positive'] != sum(y>0 for y in values): raise ValueError('Bucket positive mismatch')
  if not values:
   if b['mean_return_pct'] is not None: raise ValueError('Empty bucket mean must be null')
  elif b['mean_return_pct'] is None or not math.isclose(number(b['mean_return_pct'], 'bucket mean'), sum(values)/len(values), rel_tol=1e-9, abs_tol=1e-8): raise ValueError('Bucket mean mismatch')


def exact_optional(d, required, optional):
 if not isinstance(d,dict) or not set(required)<=set(d) or set(d)-set(required)-set(optional): raise ValueError('Unexpected or missing fields')

def check_benchmarks(b, rows, prefix, return_field):
 exact(b,('spy','sector','buckets')); exact(b['buckets'], BUCKETS)
 for name in ('spy','sector'):
  key=prefix+'_'+name+'_excess_pp'
  matched=[r for r in rows if r['score'] is not None and r.get(return_field) is not None and r.get(key) is not None]
  for r in rows:
   if r.get(key) is not None:
    number(r[key],key)
    if r.get(return_field) is None: raise ValueError('Benchmark excess requires stock return')
    if name=='sector' and (not isinstance(r.get('sector_benchmark'),str) or not r['sector_benchmark'].strip()): raise ValueError('Sector proxy required')
  def check_summary(a, selected, full):
   exact(a,('matched_n','missing_n','mean_excess_pp') if full else ('matched_n','mean_excess_pp'))
   if type(a['matched_n']) is not int or a['matched_n']!=len(selected): raise ValueError('Benchmark paired sample mismatch')
   if full and (type(a['missing_n']) is not int or a['missing_n']!=32-len(selected)): raise ValueError('Benchmark missing sample mismatch')
   if not selected:
    if a['mean_excess_pp'] is not None: raise ValueError('Empty benchmark mean must be null')
   elif not math.isclose(number(a['mean_excess_pp'],'benchmark mean'),sum(r[key] for r in selected)/len(selected),abs_tol=1e-8): raise ValueError('Benchmark mean mismatch')
  check_summary(b[name],matched,True)
  for group in BUCKETS:
   exact(b['buckets'][group],('spy','sector'))
   check_summary(b['buckets'][group][name],[r for r in matched if bucket(r['score'])==group],False)

def check_diagnostics(p):
 rows=p['rows']
 if 'post_publication_benchmarks' in p:
  check_benchmarks(p['post_publication_benchmarks'],rows,'post_publication','post_publication_return_pct')
 a=p.get('aligned_sensitivity')
 if a is None: return
 exact(a,('start_timestamp','end_timestamp','analysis','benchmarks'))
 start=timestamp(a['start_timestamp']); end=timestamp(a['end_timestamp'])
 if start<=timestamp(p['published_at']) or end<=start: raise ValueError('Invalid aligned diagnostic window')
 for r in rows:
  if not {'aligned_start_open','aligned_start_bar','aligned_return_pct'}<=set(r): raise ValueError('Aligned row evidence required')
  if r['aligned_start_open'] is not None:
   number(r['aligned_start_open'],'aligned_start_open',positive=True)
   if r['aligned_start_bar'] is None or timestamp(r['aligned_start_bar'])!=start: raise ValueError('Aligned baseline time mismatch')
  if r['aligned_start_bar'] is not None: timestamp(r['aligned_start_bar'])
  check_return(r,'aligned_return_pct','end_bar_close','aligned_start_open')
  if r['aligned_return_pct'] is not None and (r['end_bar_begins_at'] is None or not 0<(end-timestamp(r['end_bar_begins_at'])).total_seconds()<=60): raise ValueError('Aligned endpoint must be final minute of window')
 check_analysis(a['analysis'],rows,'aligned_return_pct')
 check_benchmarks(a['benchmarks'],rows,'aligned','aligned_return_pct')

def check_close_details(o):
 exact(o,('original_records','valid_reference_n','unavailable_original_n','pending_valid_reference_n','rubric_cohorts','public_history_gap'))
 for key in ('original_records','valid_reference_n','unavailable_original_n','pending_valid_reference_n'):
  if type(o[key]) is not int or o[key]<0: raise ValueError('Invalid original-close count')
 if o['valid_reference_n']+o['unavailable_original_n']!=o['original_records'] or o['pending_valid_reference_n']>o['valid_reference_n']: raise ValueError('Original-close count mismatch')
 for c in o['rubric_cohorts']:
  exact(c,('rubric','dates','original_records','valid_reference_n','unavailable_n'))
  if c['rubric'] not in ('buying-score-v1','buying-score-v2'): raise ValueError('Invalid close rubric')
  if not isinstance(c['dates'],list) or any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}',x) for x in c['dates']): raise ValueError('Invalid close dates')
  if any(type(c[k]) is not int or c[k]<0 for k in ('original_records','valid_reference_n','unavailable_n')) or c['valid_reference_n']+c['unavailable_n']!=c['original_records']: raise ValueError('Close cohort count mismatch')
 for total,key in [('original_records','original_records'),('valid_reference_n','valid_reference_n'),('unavailable_original_n','unavailable_n')]:
  if o[total]!=sum(c[key] for c in o['rubric_cohorts']): raise ValueError('Close cohort totals mismatch')
 g=o['public_history_gap'];exact(g,('dates','record_count','note'))
 if type(g['record_count']) is not int or not 0<=g['record_count']<=o['original_records']: raise ValueError('History gap count invalid')
 if not isinstance(g['dates'],list) or any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}',x) for x in g['dates']): raise ValueError('History gap dates invalid')
 if not isinstance(g['note'],str): raise ValueError('History gap explanation required')

def validate_v2(d):
 if 'official_close_details' in d: check_close_details(d['official_close_details'])
 close = d['official_close_audit']
 for k in ('matured_one_session_n','matured_five_session_n'):
  if type(close[k]) is not int or not 0 <= close[k] <= 32: raise ValueError('Invalid official-close sample size')
 if close['matured_one_session_n']==0 and close['matured_five_session_n']==0 and (close['spearman'] is not None or close['mean_return_pct'] is not None): raise ValueError('Unavailable official-close statistics must be null')
 if len(d['publications']) != 6: raise ValueError('Six scheduled publications required')
 ids=[]
 for p in d['publications']:
  exact_optional(p, V2_PUBLICATION, {'scheduled_target_houston','post_publication_benchmarks','aligned_sensitivity'})
  if 'scheduled_target_houston' in p: timestamp(p['scheduled_target_houston'])
  timestamp(p['published_at']); timestamp(p['assessment_timestamp'])
  if p['rubric_version'] not in ('buying-score-v1','buying-score-v2'): raise ValueError('Invalid publication rubric')
  if not isinstance(p['cohort'], str) or not p['cohort'].strip(): raise ValueError('Cohort required')
  if timestamp(p['assessment_timestamp']) > timestamp(p['published_at']): raise ValueError('Assessment after publication')
  ids.append(p['id'])
  if len(p['rows'])!=32 or {r['symbol'] for r in p['rows']}!=UNIVERSE: raise ValueError('All 32 required')
  for r in p['rows']:
   exact_optional(r,V2_ROW,{'aligned_start_open','aligned_start_bar','aligned_return_pct','sector_benchmark','post_publication_spy_excess_pp','post_publication_sector_excess_pp','aligned_spy_excess_pp','aligned_sector_excess_pp'})
   score=r['score']
   if score is not None and (type(score) is not int or score not in range(0,101,5)): raise ValueError('Score invalid')
   if score is None and r['score_status'] != 'unavailable': raise ValueError('Unavailable score status required')
   if score is not None and r['score_status'] not in ('available','available_provisional'): raise ValueError('Available score status required')
   if p['rubric_version']=='buying-score-v2' and score is not None and r['score_status']!='available_provisional': raise ValueError('V2 score must be provisional')
   if not isinstance(r['missing_evidence'], list) or any(not isinstance(x,str) or not x.strip() for x in r['missing_evidence']): raise ValueError('Missing evidence must be a list of nonempty explanations')
   if score is None and not r['missing_evidence']: raise ValueError('Explain unavailable original score')
   for k in ('reference_price','end_bar_close','post_publication_start_open','quote_endpoint_price'):
    if r[k] is not None: number(r[k], k, positive=True)
   for k in ('reference_price_timestamp','end_bar_begins_at','post_publication_start_bar','quote_endpoint_timestamp'): optional_timestamp(r[k])
   if r['reference_price'] is not None and any(r[k] is None or not isinstance(r[k],str) or not r[k].strip() for k in ('reference_price_timestamp','reference_price_type','reference_source','reference_session')): raise ValueError('Reference provenance required')
   lag=r['reference_to_publication_lag_seconds']
   if r['reference_price_timestamp'] is not None and lag is None: raise ValueError('Reference lag required')
   if lag is not None:
    number(lag,'reference lag')
    if r['reference_price_timestamp'] is None: raise ValueError('Reference lag requires timestamp')
    actual=(timestamp(p['published_at'])-timestamp(r['reference_price_timestamp'])).total_seconds()
    if actual < 0: raise ValueError('Reference follows publication')
    if not math.isclose(actual, lag, abs_tol=1e-5): raise ValueError('Reference lag mismatch')
   for price_key, time_key in (('end_bar_close','end_bar_begins_at'), ('post_publication_start_open','post_publication_start_bar'), ('quote_endpoint_price','quote_endpoint_timestamp')):
    if r[price_key] is not None and r[time_key] is None: raise ValueError(f'{price_key} requires timestamp')
   start=r['post_publication_start_bar']; end=r['end_bar_begins_at']
   if start is not None and timestamp(start) <= timestamp(p['published_at']): raise ValueError('Sensitivity baseline must follow publication')
   if start is not None and end is not None and timestamp(end) < timestamp(start): raise ValueError('Endpoint precedes sensitivity baseline')
   if end is not None and r['reference_price_timestamp'] is not None and timestamp(end) < timestamp(r['reference_price_timestamp']): raise ValueError('Endpoint precedes original reference')
   check_return(r,'return_pct','end_bar_close','reference_price')
   check_return(r,'post_publication_return_pct','end_bar_close','post_publication_start_open')
   check_return(r,'quote_endpoint_return_pct','quote_endpoint_price','reference_price')
  check_analysis(p['original_reference_analysis'],p['rows'],'return_pct')
  check_analysis(p['post_publication_sensitivity'],p['rows'],'post_publication_return_pct')
  check_diagnostics(p)
 if len(ids)!=len(set(ids)) or d['primary_publication_id'] not in ids: raise ValueError('Publication IDs')
 c=d['closing_review']
 if c is not None:
  exact(c,'original_publication_id original_publication_timestamp original_assessment_timestamp annotation_first_published_at new_score_assessment summary corrections records'.split())
  if c['new_score_assessment'] is not False: raise ValueError('Not a new assessment')
  for k in ('original_publication_timestamp','original_assessment_timestamp','annotation_first_published_at'): timestamp(c[k])
  for r in c['corrections']: exact(r,'topic statement sources'.split())
  if len(c['records'])!=32 or {r['symbol'] for r in c['records']}!=UNIVERSE: raise ValueError('Closing coverage')
  for r in c['records']:
   exact(r,'symbol score reference_price status'.split())
   if r['score'] is not None or r['reference_price'] is not None: raise ValueError('Unavailable reference required')

def publish(source,root=ROOT):
 d=validate(json.loads(pathlib.Path(source).read_text()));folder=root/'docs/data/outcomes';folder.mkdir(parents=True,exist_ok=True)
 target=folder/(d['id']+'.json');index=folder/'index.json'
 catalog=json.loads(index.read_text()) if index.exists() else {'schema_version':1,'audits':[]}
 if target.exists() or any(r['id']==d['id'] for r in catalog['audits']):raise ValueError('Immutable audit ID already exists; append a correction with a new ID')
 with target.open('x') as f:json.dump(d,f,indent=2);f.write('\n')
 catalog['audits'].append({'id':d['id'],'market_date':d['market_date'],'path':'data/outcomes/'+target.name})
 index.write_text(json.dumps(catalog,indent=2)+'\n')
 return target
if __name__=='__main__':print(publish(sys.argv[1]))
