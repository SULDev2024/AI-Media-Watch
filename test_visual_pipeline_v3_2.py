"""Focused offline regressions; synthetic outputs do not prove model reasoning."""
import json,socket,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import agents_v3_2 as agents
from visual_reasoning_v3_2 import consistency_flags

ROOT=Path(__file__).resolve().parent
OLD=ROOT/'reviewer2_issue3_v3_1_auditor_2026-11-08'

class V32Tests(unittest.TestCase):
    def setUp(self):
        p=patch.object(socket.socket,'connect',side_effect=AssertionError('Offline only'))
        p.start();self.addCleanup(p.stop)

    def test_instruction_separates_three_concepts_and_no_forced_score(self):
        for text in ('OBSERVATION','VERIFICATION','CONTEXT','neither safety nor fraud',
                     'Suspicious words alone do not prove fraud','Do not automatically add points',
                     'warning/criticism','uncertainty and final interpretation'):
            self.assertIn(text,agents.AUDITOR_INSTRUCTION)

    def test_missing_verification_explicitly_used_as_safety_is_reviewed(self):
        f=consistency_flags(['Guaranteed Profits'],'Safe because the claims are unverified.','promotion')
        self.assertIn('possible_verification_safety_confusion',[x['code'] for x in f])

    def test_uncertainty_and_warning_are_not_automatically_fraud(self):
        for context,reason in [('promotion','A guarantee is displayed; profits are unverified; risk remains uncertain.'),
                               ('warning','The lesson warns against the quoted guarantee.'),
                               ('reporting','The article neutrally quotes the claim; authenticity is unknown.')]:
            self.assertEqual(consistency_flags(['Guaranteed Profits'],reason,context),[])

    def test_presence_contradiction_still_flagged_in_warning(self):
        self.assertTrue(consistency_flags(['Guaranteed Profits'],'No guarantees are displayed.','warning'))

    def test_actual_saved_claims_preserved_without_new_evidence(self):
        data=json.loads((OLD/'shared_visual_evidence.json').read_text(encoding='utf-8'))
        p,v=agents.build_auditor_prompt('','same transcript',data['raw_report'],'same speech',data['metadata'])
        self.assertTrue(v['can_forward'])
        self.assertEqual(v['parsed_report'],data['validation']['parsed_report'])
        self.assertIn('Guaranteed Profits',p);self.assertIn('100% accurate trading signals',p)
        bad=json.loads(v['normalized_report']);bad['OBSERVED'][0]['frame']=4
        self.assertIsNone(agents.build_auditor_prompt('','',json.dumps(bad),'',data['metadata'])[0])
        self.assertIsNone(agents.build_auditor_prompt('','',data['raw_report'],'',dict(data['metadata'],done_reason='length'))[0])

    def test_prepared_pair_only_visual_differs_and_same_settings(self):
        out=ROOT/'visual_pipeline_v3_2_2026-11-08'
        a=json.loads((out/'speech_only_prepared_request.json').read_text(encoding='utf-8'))
        b=json.loads((out/'speech_plus_video_prepared_request.json').read_text(encoding='utf-8'))
        self.assertEqual({k:v for k,v in a.items() if k!='messages'},{k:v for k,v in b.items() if k!='messages'})
        ap=a['messages'][0]['content'];bp=b['messages'][0]['content']
        self.assertEqual(ap.split('\nVisual: ')[0],bp.split('\nVisual: ')[0])
        self.assertEqual(ap.split('\nSpeech: ')[1],bp.split('\nSpeech: ')[1])
        self.assertNotIn('Human label:',bp)

    def test_output_review_preserves_raw_score_no_adjustment(self):
        d=json.loads((OLD/'shared_visual_evidence.json').read_text(encoding='utf-8'))
        raw=json.dumps({'risk_score':30,'reasoning':'Safe because the claims are unverified.','flags':[]})
        client=Mock();client.chat.return_value={'message':{'content':raw},'done':True,'done_reason':'stop'}
        with patch.object(agents,'_ollama',client):
            r=agents.auditor('','',d['raw_report'],'',d['metadata'])
        self.assertEqual(r['risk_score'],30);self.assertEqual(r['status'],'needs_review')
        self.assertEqual(r['raw_auditor_response'],raw)

if __name__=='__main__':unittest.main()
