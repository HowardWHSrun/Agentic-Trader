import copy
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publish_outcome_v2', ROOT / 'scripts/publish_outcome.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def analysis(values):
    buckets = {key: {'n': 0, 'mean_return_pct': None, 'positive': 0} for key in m.BUCKETS}
    for score, ret in values:
        b = buckets[m.bucket(score)]
        b['n'] += 1
        b['positive'] += ret > 0
    for key, b in buckets.items():
        matching = [ret for score, ret in values if m.bucket(score) == key]
        if matching:
            b['mean_return_pct'] = sum(matching) / len(matching)
    return {'n': len(values), 'spearman': None,
            'mean_return_pct': sum(y for _, y in values) / len(values) if values else None,
            'buckets': buckets}


def audit():
    publications = []
    for i in range(6):
        rows = []
        for symbol in sorted(m.UNIVERSE):
            row = dict.fromkeys(m.V2_ROW)
            row.update(symbol=symbol, score_status='unavailable', missing_evidence=['Original score unavailable'])
            rows.append(row)
        if i >= 2:
            rows[0].update(score=0, score_status='available_provisional', missing_evidence=[],
                           reference_price=100, reference_price_timestamp='2026-10-21T13:00:00Z',
                           reference_price_type='trade', reference_source='public source', reference_session='regular',
                           reference_to_publication_lag_seconds=60, end_bar_begins_at='2026-10-21T19:59:00Z',
                           end_bar_close=110, return_pct=10.0,
                           post_publication_start_bar='2026-10-21T13:02:00Z', post_publication_start_open=100,
                           post_publication_return_pct=10.0, quote_endpoint_price=110,
                           quote_endpoint_timestamp='2026-10-21T19:59:59Z', quote_endpoint_return_pct=10.0)
        values = [] if i < 2 else [(0, 10.0)]
        publications.append(dict(id=str(i), published_at='2026-10-21T13:01:00Z', assessment_timestamp='2026-10-21T13:00:30Z',
                                 cohort='v2-regular', rubric_version='buying-score-v2', rows=rows,
                                 original_reference_analysis=analysis(values), post_publication_sensitivity=analysis(values)))
    return dict(schema_version=2, id='2026-10-21-example', market_date='2026-10-21',
                analysis_completed_at='2026-10-21T20:01:00Z', analysis_first_published_at='2026-10-21T20:02:00Z',
                website_export_created_at='2026-10-21T20:03:00Z', timezone='America/Chicago', rubric_version='buying-score-v2',
                weights=[30,25,20,10,15], new_score_assessment=False, summary='Public research', method='Descriptive',
                primary_publication_id='2', endpoint_source='Final minute, not official auction close', delay='Unknown',
                benchmark_excess_return=None, benchmark_status='Unavailable',
                official_close_audit=dict(matured_one_session_n=0, matured_five_session_n=0, spearman=None, mean_return_pct=None, status='Unavailable'),
                limitations=['Overlapping observations'], endpoint_qa=dict(minute_quote_mismatches=[], genuine_final_bars=0, excluded_interpolated_bars=0, note='Unknown'),
                publications=publications, closing_review=None, sizing='Sizing is not provided on this public market-research page.')


class OutcomeV2Tests(unittest.TestCase):
    def setUp(self): self.d = audit()
    def test_empty_and_partial_samples_and_real_zero(self): m.validate(self.d)
    def test_six_realistic_cohort_sizes(self):
        for i, n in enumerate((0, 0, 31, 32, 32, 32)):
            p = self.d['publications'][i]
            if n:
                template = p['rows'][0]
                for row in p['rows'][1:n]:
                    symbol = row['symbol']
                    row.update(copy.deepcopy(template), symbol=symbol)
                p['original_reference_analysis'] = analysis([(0, 10.0)] * n)
                p['post_publication_sensitivity'] = analysis([(0, 10.0)] * n)
        m.validate(self.d)
    def test_sample_counts_must_match_pairs(self):
        self.d['publications'][2]['original_reference_analysis']['n'] = 32
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_unavailable_not_zero_or_unexplained(self):
        self.d['publications'][0]['rows'][0]['missing_evidence'] = []
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_sensitivity_and_quote_arithmetic(self):
        for field in ('post_publication_return_pct', 'quote_endpoint_return_pct'):
            d=copy.deepcopy(self.d); d['publications'][2]['rows'][0][field] = 999
            with self.assertRaises(ValueError): m.validate(d)
    def test_undefined_correlation_not_zero(self):
        self.d['publications'][0]['original_reference_analysis']['spearman'] = 0
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_official_close_unavailable_not_zero(self):
        self.d['official_close_audit']['mean_return_pct'] = 0
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_original_32_universe_and_bucket_counts(self):
        self.d['publications'][2]['rows'][1]['symbol'] = self.d['publications'][2]['rows'][0]['symbol']
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_high_precision_zoned_timestamp(self):
        self.assertEqual(m.timestamp('2026-10-21T13:38:19.421622531Z').microsecond, 421622)
        with self.assertRaises(ValueError): m.timestamp('2026-10-21T13:38:19')
    def test_v2_score_is_provisional(self):
        self.d['publications'][2]['rows'][0]['score_status']='available'
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_no_prepublication_sensitivity_baseline(self):
        self.d['publications'][2]['rows'][0]['post_publication_start_bar']='2026-10-21T13:00:00Z'
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_future_original_reference_rejected(self):
        row=self.d['publications'][2]['rows'][0]
        row['reference_price_timestamp']='2026-10-21T13:02:00Z'
        row['reference_to_publication_lag_seconds']=-60
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_missing_evidence_explanations_must_be_text(self):
        self.d['publications'][0]['rows'][0]['missing_evidence']=[{}]
        with self.assertRaises(ValueError): m.validate(self.d)
    def test_defined_correlation_cannot_be_omitted(self):
        rows=[{'score':0,'return_pct':1},{'score':5,'return_pct':2}]
        with self.assertRaises(ValueError): m.check_analysis(analysis([(0,1),(5,2)]),rows,'return_pct')
    def test_optional_benchmark_pair_counts_and_empty_means(self):
        p=self.d['publications'][2]
        for row in p['rows']:
            row.update(sector_benchmark='XLK',post_publication_spy_excess_pp=None,post_publication_sector_excess_pp=None)
        p['rows'][0]['post_publication_spy_excess_pp']=1.0
        b={k:{'matched_n':1 if k=='spy' else 0,'missing_n':31 if k=='spy' else 32,'mean_excess_pp':1.0 if k=='spy' else None} for k in ('spy','sector')}
        b['buckets']={group:{k:{'matched_n':1 if group=='0-19' and k=='spy' else 0,'mean_excess_pp':1.0 if group=='0-19' and k=='spy' else None} for k in ('spy','sector')} for group in m.BUCKETS}
        p['post_publication_benchmarks']=b
        m.validate(self.d)
        b['spy']['matched_n']=32
        with self.assertRaises(ValueError):m.validate(self.d)
    def test_official_original_totals_never_backfilled(self):
        self.d['official_close_details']={'original_records':32,'valid_reference_n':0,'unavailable_original_n':32,'pending_valid_reference_n':0,'rubric_cohorts':[{'rubric':'buying-score-v2','dates':['2026-10-21'],'original_records':32,'valid_reference_n':0,'unavailable_n':32}],'public_history_gap':{'dates':[],'record_count':0,'note':'No gap'}}
        m.validate(self.d)
        self.d['official_close_details']['pending_valid_reference_n']=32
        with self.assertRaises(ValueError):m.validate(self.d)
    def test_six_publications(self):
        self.d['publications'].pop()
        with self.assertRaises(ValueError): m.validate(self.d)

if __name__ == '__main__': unittest.main()
