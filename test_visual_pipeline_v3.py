"""Only offline synthetic/saved-text tests; no real model/video calls."""
import copy
import json
import socket
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
import cv2
import agents_v3 as v3
from visual_reasoning_v3 import validate_visual_report,render_validated_report,consistency_flags

ROOT=Path(__file__).resolve().parent
META={'done_reason':'stop','done':True,'supplied_frame_count':1}


def report(context='promotion',summary='The video promotes a claimed guarantee, not verified profit.',
           quote='Guaranteed Profits',frame=1):
    return json.dumps({'OBSERVED':[{'frame':frame,'text':[quote],'objects':['text slide']}],
                       'INTERPRETATION':{'context':context,'summary':summary},
                       'UNCERTAINTY':['The displayed claim is unverified.']})


class V3Tests(unittest.TestCase):
    def setUp(self):
        p=patch.object(socket.socket,'connect',side_effect=AssertionError('Network prohibited in lightweight tests'))
        p.start();self.addCleanup(p.stop)

    def test_valid_claims_preserved_exactly_not_verified(self):
        raw=report(quote='Guaranteed Profits — 100% accurate trading signals')
        result=validate_visual_report(raw,1,META)
        self.assertTrue(result['can_forward'])
        self.assertEqual(result['raw_report'],raw)
        envelope=json.loads(render_validated_report(result))
        self.assertEqual(envelope['MODEL_REPORT'],json.loads(raw))
        self.assertEqual(envelope['MODEL_REPORT']['OBSERVED'][0]['text'],['Guaranteed Profits — 100% accurate trading signals'])
        self.assertNotIn('risk_score',result)

    def test_visible_guarantee_denied_is_flagged_without_rewriting(self):
        raw=report(summary='No guarantee appears on screen.')
        result=validate_visual_report(raw,1,META)
        self.assertTrue(result['can_forward'])
        self.assertTrue(result['requires_uncertainty'])
        self.assertIn('possible_quote_presence_conflict',[x['code'] for x in result['issues']])
        self.assertEqual(result['parsed_report'],json.loads(raw))

    def test_known_promotional_denial_is_ambiguous_not_auto_resolved(self):
        result=validate_visual_report(report(summary='The service does not provide specific financial claims or guarantees of earnings.'),1,META)
        self.assertIn('possible_promotional_claim_conflict',[x['code'] for x in result['issues']])
        self.assertTrue(result['requires_uncertainty'])

    def test_warning_and_neutral_quotation_are_not_promotion(self):
        for context,summary in [('warning','This warns about the quoted scam. Profits are not guaranteed; do not pay.'),
                                ('reporting','The presenter neutrally quotes another advertiser; it does not make a guarantee.'),
                                ('warning','The video makes no guarantee; it warns about this advertised scam.')]:
            result=validate_visual_report(report(context,summary),1,META)
            self.assertTrue(result['can_forward'])
            self.assertEqual(result['context'],context)
            self.assertEqual(result['issues'],[])
            self.assertNotIn('classification',result)

    def test_doubting_truth_is_not_denying_visible_quote(self):
        self.assertEqual(consistency_flags(['Guaranteed Profits'],
                         'The quote is visible but no guarantee is verified. Returns are not guaranteed.', 'promotion'),[])

    def test_invalid_frame_is_preserved_but_blocks_forwarding(self):
        raw=report(frame=4)
        result=validate_visual_report(raw,3,META)
        self.assertFalse(result['can_forward'])
        self.assertEqual(result['parsed_report']['OBSERVED'][0]['frame'],4)
        self.assertEqual(result['raw_report'],raw)
        self.assertIn('invalid_frame_reference',[x['code'] for x in result['issues']])
        with self.assertRaises(ValueError):render_validated_report(result)

    def test_number_in_visible_educational_quote_is_not_frame_reference(self):
        raw=report('warning','A tutorial screenshot, not an investment promotion.',quote='In tutorial frame 4, do not trust Guaranteed Profits')
        self.assertTrue(validate_visual_report(raw,1,META)['can_forward'])

    def test_missing_duplicate_and_boolean_frame_entries_block(self):
        self.assertFalse(validate_visual_report(report(),2,META)['can_forward'])
        d=json.loads(report());d['OBSERVED'].append(copy.deepcopy(d['OBSERVED'][0]))
        self.assertFalse(validate_visual_report(json.dumps(d),1,META)['can_forward'])
        self.assertFalse(validate_visual_report(report(frame=True),1,META)['can_forward'])

    def test_unknown_frame_count_and_empty_skipped_report_block(self):
        self.assertFalse(validate_visual_report(report(),None,META)['can_forward'])
        client=Mock()
        with patch.object(v3,'_ollama',client):
            result=v3.auditor('','Speech','','Report',{'done_reason':'skipped_no_frames','supplied_frame_count':0})
        client.chat.assert_not_called()
        self.assertIsNone(result['risk_score'])
        self.assertEqual(result['status'],'needs_review')

    def test_malformed_incomplete_and_unknown_generation_block(self):
        for raw,meta in [('not json',META),(report()[:-1],{'done_reason':'length'}),
                         (report(),{'done_reason':'length'}),(report(),{})]:
            result=validate_visual_report(raw,1,meta)
            self.assertFalse(result['can_forward'])
            self.assertEqual(result['raw_report'],raw)

    def test_malformed_schema_types_duplicate_keys_and_nonfinite_json(self):
        values=[{},[],None]
        for context in ([],{},True,None):
            d=json.loads(report());d['INTERPRETATION']['context']=context;values.append(d)
        for d in values:
            result=validate_visual_report(json.dumps(d),1,META)
            self.assertFalse(result['can_forward'])
            self.assertIn('malformed_schema',[i['code'] for i in result['issues']])
        for raw in ('{"OBSERVED":[],"OBSERVED":[1]}','{"x":NaN}'):
            self.assertFalse(validate_visual_report(raw,1,META)['can_forward'])

    def test_actual_saved_v2_failure_is_detected_without_model(self):
        path=ROOT/'reviewer2_issue3_new_video_v2_2026-11-08/vision_request.json'
        q=json.loads(path.read_text(encoding='utf-8'));raw=q['response']['message']['content']
        result=validate_visual_report(raw,len(q['request']['messages'][0]['images']),q['response'])
        codes=[x['code'] for x in result['issues']]
        self.assertIn('generation_incomplete',codes)
        self.assertIn('malformed_report',codes)
        self.assertIn('invalid_frame_heading',codes)
        self.assertIn('possible_unstructured_conflict',codes)
        self.assertFalse(result['can_forward'])
        self.assertEqual(result['raw_report'],raw)

    def test_same_speech_and_instruction_only_visual_differs(self):
        a,_=v3.build_auditor_prompt('','Exact speech','','Shared Mistral')
        b,validation=v3.build_auditor_prompt('','Exact speech',report(),'Shared Mistral',META)
        visual=render_validated_report(validation)
        self.assertEqual(a.replace('Visual: \nSpeech:','Visual: '+visual+'\nSpeech:'),b)
        self.assertIn('Do not automatically raise risk for visuals',a)
        self.assertIn('warning, criticism or neutral quotation',b)

    def test_auditor_settings_equal_and_model_score_not_adjusted(self):
        client=Mock();client.chat.return_value={'message':{'content':'{"risk_score":60,"reasoning":"A displayed claim, not verified truth.","flags":[]}'},'done_reason':'stop'}
        with patch.object(v3,'_ollama',client):
            a=v3.auditor('','Same speech','','Same report')
            b=v3.auditor('','Same speech',report(),'Same report',META)
        ca,cb=[x.kwargs for x in client.chat.call_args_list]
        self.assertEqual(ca['options'],cb['options'])
        self.assertEqual(ca['options'],{'num_ctx':4096,'num_predict':128})
        self.assertEqual(ca['model'],'llama3:latest')
        self.assertEqual(a['risk_score'],60);self.assertEqual(b['risk_score'],60)

    def test_blocked_report_never_calls_llama_and_no_default_score(self):
        client=Mock()
        with patch.object(v3,'_ollama',client):
            result=v3.auditor('','Speech',report(frame=4),'Mistral',dict(META,supplied_frame_count=3))
        client.chat.assert_not_called();self.assertIsNone(result['risk_score'])
        self.assertFalse(result['model_called'])

    def test_post_auditor_conflict_flags_without_changing_raw_score(self):
        client=Mock();raw='{"risk_score":60,"reasoning":"No guarantee appears on screen.","flags":[]}'
        client.chat.return_value={'message':{'content':raw},'done_reason':'stop'}
        with patch.object(v3,'_ollama',client):result=v3.auditor('','Speech',report(),'Mistral',META)
        self.assertEqual(result['risk_score'],60)
        self.assertEqual(result['status'],'needs_review')
        self.assertEqual(result['raw_auditor_response'],raw)
        self.assertTrue(result['reasoning_validation']['flags'])

    def test_oversized_evidence_is_not_silently_excerpted(self):
        raw=report(quote='Guaranteed Profits '+'x'*5000)
        prompt,validation=v3.build_auditor_prompt('','Speech',raw,'Mistral',META)
        self.assertIsNone(prompt)
        self.assertEqual(validation['raw_report'],raw)
        self.assertFalse(validation['can_forward'])

    def test_vision_count_schema_prompt_cpu_and_metadata_with_mock(self):
        frame=np.zeros((180,320,3),np.uint8)
        cv2.putText(frame,'Guaranteed Profits',(5,90),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
        client=Mock();client.chat.return_value={'message':{'content':report()},'done_reason':'stop','done':True,'eval_count':90}
        with patch.object(v3,'_ollama',client):result=v3.vision_eye([frame])
        q=client.chat.call_args.kwargs
        self.assertEqual(len(q['messages'][0]['images']),1)
        self.assertIn('Only 1 images are supplied',q['messages'][0]['content'])
        self.assertEqual(q['options'],{'num_ctx':4096,'num_predict':384,'num_gpu':0})
        self.assertTrue(result['visual_validation']['can_forward'])
        self.assertEqual(result['visual_report'],report())

    def test_warning_and_promotion_keywords_do_not_force_score_increase(self):
        client=Mock();client.chat.return_value={'message':{'content':'{"risk_score":10,"reasoning":"A displayed quote is not verified; context matters.","flags":[]}'},'done_reason':'stop'}
        with patch.object(v3,'_ollama',client):
            warning=v3.auditor('','Speech',report('warning','This warns about a scam; profits are not guaranteed.'),'Mistral',META)
            promotion=v3.auditor('','Speech',report(),'Mistral',META)
        self.assertEqual(warning['risk_score'],10)
        self.assertEqual(promotion['risk_score'],10)

    def test_v3_rerun_requires_approval_and_cannot_run_asr_or_mistral(self):
        import ast
        file=ROOT/'visual_pipeline_v3_2026-11-08/rerun_new_new.py'
        ns=runpy.run_path(str(file),run_name='v3_offline_test')
        with patch.dict(os.environ,{'AI_MEDIA_WATCH_V3_APPROVED':'0'}),self.assertRaises(AssertionError):
            ns['worker']('vision')
        calls=[n.func.attr for n in ast.walk(ast.parse(file.read_text()))
               if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertNotIn('transcribe',calls);self.assertNotIn('speech_analyst',calls)

    def test_v3_rerun_blocked_auditor_saves_no_prediction_without_request_file(self):
        ns=runpy.run_path(str(ROOT/'visual_pipeline_v3_2026-11-08/rerun_new_new.py'),run_name='v3_offline_test')
        finish=ns['finish']
        with tempfile.TemporaryDirectory(dir=ROOT/'visual_pipeline_v3_2026-11-08') as tmp:
            out=Path(tmp)
            self.assertTrue(out.resolve().is_relative_to((ROOT/'visual_pipeline_v3_2026-11-08').resolve()))
            values={'speech_only.json':{'risk_score':60,'classification':'SCAM','prediction_valid':True,'model_called':True},
                    'speech_plus_video.json':{'risk_score':None,'classification':'NEEDS_REVIEW','prediction_valid':False,'model_called':False},
                    'configuration.json':{'video':'not-opened.mp4'},'preservation_before.json':{}}
            for name,value in values.items():(out/name).write_text(json.dumps(value))
            with patch.dict(finish.__globals__,{'OUT':out,'memory':lambda:{}}),patch('builtins.print'):
                finish('needs_review','synthetic timestamp',{},'budget/validation block')
            result=json.loads((out/'result.json').read_text())
            self.assertIsNone(result['score_difference'])
            self.assertFalse(result['paired_inputs_verified'])
            self.assertIsNone(result['speech_plus_video']['risk_score'])

    def test_v3_rerun_wrapper_preserves_same_cpu_sampling_for_both_auditor_calls(self):
        ns=runpy.run_path(str(ROOT/'visual_pipeline_v3_2026-11-08/rerun_new_new.py'),run_name='v3_offline_test')
        cls=ns['RecordedClient'];method=cls.chat
        calls=[]
        with tempfile.TemporaryDirectory(dir=ROOT/'visual_pipeline_v3_2026-11-08') as tmp:
            out=Path(tmp)
            self.assertTrue(out.resolve().is_relative_to((ROOT/'visual_pipeline_v3_2026-11-08').resolve()))
            def fake_api(endpoint,request):
                calls.append(request);return {'message':{'content':'{}'}}
            with patch.dict(method.__globals__,{'OUT':out,'api':fake_api,'memory':lambda:{}}):
                for stage in ('speech_only','speech_plus_video'):
                    cls(stage).chat(model='llama3:latest',messages=[{'role':'user','content':'synthetic'}],
                                    options={'num_ctx':4096,'num_predict':128})
        expected={'num_ctx':4096,'num_predict':128,'num_gpu':0,'temperature':0.8,'seed':42}
        self.assertEqual(calls[0]['options'],expected);self.assertEqual(calls[1]['options'],expected)


if __name__=='__main__':unittest.main()
