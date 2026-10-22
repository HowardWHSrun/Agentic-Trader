import copy, importlib.util,json,pathlib,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('publish_outcome',ROOT/'scripts/publish_outcome.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class OutcomeTests(unittest.TestCase):
 def setUp(self):self.d=json.loads((ROOT/'docs/data/outcomes/2026-10-21-intraday-audit-v1.json').read_text())
 def test_valid(self):m.validate(self.d)
 def test_all_seven_full_universe(self):
  self.assertEqual(len(self.d['publications']),7)
  for p in self.d['publications']:self.assertEqual({r['symbol'] for r in p['rows']},m.UNIVERSE)
 def test_private_field_rejected(self):
  self.d['publications'][0]['rows'][0]['holdings']=42
  with self.assertRaises(ValueError):m.validate(self.d)
 def test_private_narrative_rejected(self):
  self.d['summary']='/workspace/private/report.json'
  with self.assertRaises(ValueError):m.validate(self.d)
 def test_missing_ticker_rejected(self):
  self.d['publications'][0]['rows'].pop()
  with self.assertRaises(ValueError):m.validate(self.d)
 def test_revised_return_rejected(self):
  self.d['publications'][0]['rows'][0]['return_pct']=99
  with self.assertRaises(ValueError):m.validate(self.d)
 def test_not_new_assessment(self):
  self.d['new_score_assessment']=True
  with self.assertRaises(ValueError):m.validate(self.d)
 def test_immutable_and_no_watch_mutation(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);source=root/'input.json';source.write_text(json.dumps(self.d));watch=root/'docs/data/watch.json';watch.parent.mkdir(parents=True);watch.write_text('frozen');m.publish(source,root)
   with self.assertRaises(ValueError):m.publish(source,root)
   self.assertEqual(watch.read_text(),'frozen')
 def test_original_reference_primary_result(self):
  p=next(p for p in self.d['publications'] if p['id']==self.d['primary_publication_id'])
  self.assertAlmostEqual(p['original_reference_analysis']['spearman'],.08611,places=4)
 def test_benchmark_not_zero(self):self.assertIsNone(self.d['benchmark_excess_return'])
 def test_no_official_close_claim(self):self.assertIn('not a verified official',self.d['endpoint_source'])
 def test_frontend_safe_text(self):
  js=(ROOT/'docs/outcomes.js').read_text();self.assertNotIn('innerHTML',js);self.assertIn('textContent',js)
if __name__=='__main__':unittest.main()
