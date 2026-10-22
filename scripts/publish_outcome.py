"""Append a reviewed, public-only descriptive outcome audit; never edit watch data."""
import json, pathlib, re, sys
from datetime import datetime
ROOT = pathlib.Path(__file__).resolve().parents[1]
UNIVERSE = set('AAPL AVGO CRM MSFT NVDA GOOGL META AMZN HD COST KO PG WMT ABBV LLY UNH BAC JPM V CVX XOM CAT DE GE RTX DUK NEE FCX LIN PLD TSLA SPCX'.split())
TOP = set('schema_version id market_date analysis_completed_at analysis_first_published_at website_export_created_at timezone rubric_version weights new_score_assessment summary method primary_publication_id endpoint_source delay benchmark_excess_return benchmark_status official_close_audit limitations endpoint_qa publications closing_review sizing'.split())
ROW = set('symbol score reference_price reference_price_timestamp reference_price_type reference_source reference_to_publication_lag_seconds end_bar_begins_at end_bar_close return_pct post_publication_start_bar post_publication_start_open post_publication_return_pct quote_endpoint_price quote_endpoint_timestamp quote_endpoint_return_pct'.split())
def exact(d, keys):
 if not isinstance(d,dict) or set(d)!=set(keys): raise ValueError('Unexpected or missing fields')
def timestamp(v):
 if datetime.fromisoformat(v.replace('Z','+00:00')).tzinfo is None: raise ValueError('Timezone required')
def validate(d):
 exact(d,TOP)
 if d['schema_version']!=1 or d['new_score_assessment'] is not False: raise ValueError('Not an outcome audit')
 if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[a-z0-9-]+',d['id']): raise ValueError('Invalid ID')
 for k in ['analysis_completed_at','analysis_first_published_at','website_export_created_at']: timestamp(d[k])
 if d['weights']!=[30,25,20,10,15] or d['rubric_version']!='buying-score-v1': raise ValueError('Rubric changed')
 if d['sizing']!='Sizing is not provided on this public market-research page.': raise ValueError('Sizing not public')
 exact(d['official_close_audit'],'matured_one_session_n matured_five_session_n spearman mean_return_pct status'.split())
 exact(d['endpoint_qa'],'minute_quote_mismatches genuine_final_bars excluded_interpolated_bars note'.split())
 for r in d['endpoint_qa']['minute_quote_mismatches']: exact(r,'symbol minute_close quote_last_trade quote_timestamp'.split())
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
 text=json.dumps(d,allow_nan=False)
 if any(x in text.lower() for x in ['/workspace/','sentinel_','account_id','cost_basis','access_token','private_key','settled_cash']): raise ValueError('Private content detected')
 return d

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
