"""Offline format compatibility tests only; all model calls mocked/forbidden."""
import ast
import copy
import hashlib
import json
import socket
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import agents_v3
import agents_v3_1 as agents
import visual_reasoning_v3 as strict
import visual_reasoning_v3_1 as compat

ROOT=Path(__file__).resolve().parent
META={'done_reason':'stop','done':True,'supplied_frame_count':1}


def sample(objects=True):
    observation={'frame':1,'text':['Guaranteed Profits']}
    if objects:observation['objects']=['Text slide']
    return {'OBSERVED':[observation],
            'INTERPRETATION':{'context':'promotion','summary':'A displayed claim, not verified profits.'},
            'UNCERTAINTY':['The claim is unverified.']}


class CompatTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('No network in offline tests'))
        guard.start();self.addCleanup(guard.stop)

    def test_actual_saved_response_passes_with_four_recorded_normalizations(self):
        p=ROOT/'visual_pipeline_v3_2026-11-08/runs/new_new_v3'
        q=json.loads((p/'vision_request.json').read_text(encoding='utf-8'))
        raw=q['response']['message']['content'];meta=json.loads((p/'vision.json').read_text(encoding='utf-8'))['visual_report_metadata']
        result=compat.validate_visual_report(raw,3,meta)
        self.assertTrue(result['can_forward']);self.assertTrue(result['schema_valid'])
        self.assertEqual(result['issues'],[])
        self.assertEqual(result['raw_report'],raw)
        self.assertEqual(result['raw_sha256'],hashlib.sha256(raw.encode('utf-8')).hexdigest())
        self.assertEqual([n['op'] for n in result['normalizations']],['unwrap_json_fence']+['default_missing_objects']*3)
        source=result['source_parsed_report'];expected=copy.deepcopy(source)
        for o in expected['OBSERVED']:o['objects']=[]
        self.assertEqual(expected,result['parsed_report'])
        self.assertNotIn('objects',source['OBSERVED'][0])
        self.assertIn('Guaranteed Profits',' '.join(expected['OBSERVED'][2]['text']))
        self.assertIn('100% accurate trading signals',' '.join(expected['OBSERVED'][1]['text']))

    def test_clean_existing_json_is_unchanged_with_no_normalization(self):
        raw=json.dumps(sample(),ensure_ascii=False,indent=2)
        a=strict.validate_visual_report(raw,1,META);b=compat.validate_visual_report(raw,1,META)
        self.assertEqual(b['normalizations'],[])
        self.assertEqual(b['normalized_report'],raw)
        for key in ('can_forward','schema_valid','parsed_report','issues','frame_checks'):
            self.assertEqual(a[key],b[key])

    def test_json_and_unlabelled_fences_accept_only_one_complete_document(self):
        for tag in ('json','JSON',''):
            raw=' \n```'+tag+'\n'+json.dumps(sample())+'\n```\n '
            v=compat.validate_visual_report(raw,1,META)
            self.assertTrue(v['can_forward']);self.assertEqual(len(v['normalizations']),1)
            self.assertEqual(v['raw_report'],raw)

    def test_prose_extra_blocks_wrong_language_and_unclosed_fences_fail(self):
        body=json.dumps(sample());good='```json\n'+body+'\n```'
        for raw in ('Here is JSON:\n'+good,good+'\nAnd more prose',good+'\n'+good,
                    '```javascript\n'+body+'\n```','```json\n'+body,good+' trailing'):
            v=compat.validate_visual_report(raw,1,META)
            self.assertFalse(v['can_forward'],raw)
            self.assertIn('malformed_report',[x['code'] for x in v['issues']])

    def test_missing_objects_means_not_supplied_not_absence(self):
        raw=json.dumps(sample(False));v=compat.validate_visual_report(raw,1,META)
        self.assertTrue(v['can_forward']);self.assertEqual(v['parsed_report']['OBSERVED'][0]['objects'],[])
        self.assertTrue(v['requires_uncertainty'])
        envelope=json.loads(compat.render_validated_report(v))
        self.assertEqual(envelope['VALIDATOR']['objects_default_meaning'],'not supplied, not verified absence')
        self.assertEqual(envelope['VALIDATOR']['normalizations'][0]['op'],'default_missing_objects')

    def test_explicit_invalid_objects_are_not_repaired(self):
        for value in (None,'',{},[7]):
            d=sample();d['OBSERVED'][0]['objects']=value;v=compat.validate_visual_report(json.dumps(d),1,META)
            self.assertFalse(v['can_forward'])
            self.assertFalse(any(n['op']=='default_missing_objects' for n in v['normalizations']))
            self.assertEqual(v['parsed_report']['OBSERVED'][0]['objects'],value)

    def test_missing_text_frame_or_extra_evidence_fields_are_not_repaired(self):
        for key in ('text','frame'):
            d=sample(False);del d['OBSERVED'][0][key]
            v=compat.validate_visual_report(json.dumps(d),1,META)
            self.assertFalse(v['can_forward']);self.assertEqual(v['normalizations'],[])
        d=sample(False);d['OBSERVED'][0]['invented_extra']='no'
        self.assertFalse(compat.validate_visual_report(json.dumps(d),1,META)['can_forward'])

    def test_fenced_invalid_frames_still_block_and_keep_all_claims(self):
        d=sample(False);d['OBSERVED'][0]['frame']=4;raw='```json\n'+json.dumps(d)+'\n```'
        v=compat.validate_visual_report(raw,3,META)
        self.assertFalse(v['can_forward'])
        self.assertIn('invalid_frame_reference',[x['code'] for x in v['issues']])
        self.assertEqual(v['parsed_report']['OBSERVED'][0]['frame'],4)
        self.assertEqual(v['parsed_report']['OBSERVED'][0]['text'],['Guaranteed Profits'])

    def test_incomplete_unknown_malformed_and_duplicate_keys_still_block(self):
        raw='```json\n'+json.dumps(sample(False))+'\n```'
        for meta in ({'done_reason':'length'},{},{'done_reason':'stop','done':False}):
            self.assertFalse(compat.validate_visual_report(raw,1,meta)['can_forward'])
        for bad in ('```json\n{"OBSERVED":\n```','```json\n{"OBSERVED":[],"OBSERVED":[]}\n```'):
            self.assertFalse(compat.validate_visual_report(bad,1,META)['can_forward'])

    def test_contradiction_flags_and_warning_context_policy_unchanged(self):
        d=sample(False);d['INTERPRETATION']['summary']='No guarantee appears on screen.'
        raw='```json\n'+json.dumps(d)+'\n```';v=compat.validate_visual_report(raw,1,META)
        self.assertIn('possible_quote_presence_conflict',[x['code'] for x in v['issues']])
        self.assertTrue(v['requires_uncertainty'])
        self.assertEqual(v['parsed_report']['INTERPRETATION'],d['INTERPRETATION'])
        d['INTERPRETATION']={'context':'warning','summary':'This warns about a scam; profits are not guaranteed.'}
        v=compat.validate_visual_report(json.dumps(d),1,META)
        self.assertTrue(v['can_forward']);self.assertEqual(v['issues'],[])
        self.assertEqual(v['context'],'warning')

    def test_prompts_options_and_scoring_agent_functions_unchanged(self):
        self.assertEqual(agents.AUDITOR_INSTRUCTION,agents_v3.AUDITOR_INSTRUCTION)
        self.assertEqual(agents.vision_prompt(3),agents_v3.vision_prompt(3))
        self.assertEqual(agents.VISION_NUM_PREDICT,agents_v3.VISION_NUM_PREDICT)
        a=ast.parse((ROOT/'agents_v3.py').read_text());b=ast.parse((ROOT/'agents_v3_1.py').read_text())
        functions=lambda t:[ast.dump(n) for n in t.body if isinstance(n,ast.FunctionDef)]
        self.assertEqual(functions(a),functions(b))

    def test_actual_report_is_eligible_within_unchanged_prompt_budget_without_model(self):
        p=ROOT/'visual_pipeline_v3_2026-11-08/runs/new_new_v3'
        q=json.loads((p/'vision_request.json').read_text(encoding='utf-8'))
        meta=json.loads((p/'vision.json').read_text(encoding='utf-8'))['visual_report_metadata']
        transcript=json.loads((p/'transcription.json').read_text())['text'];speech=json.loads((p/'speech.json').read_text())['speech_report']
        client=Mock(side_effect=AssertionError('No inference allowed'))
        with patch.object(agents,'_ollama',client):
            a,_=agents.build_auditor_prompt('',transcript,'',speech)
            b,validation=agents.build_auditor_prompt('',transcript,q['response']['message']['content'],speech,meta)
        client.chat.assert_not_called()
        visual=compat.render_validated_report(validation)
        self.assertEqual(a.replace('Visual: \nSpeech:','Visual: '+visual+'\nSpeech:'),b)
        self.assertLessEqual(len(b.encode('utf-8')),agents.PROMPT_MAX_UTF8_BYTES)
        self.assertIn('Guaranteed Profits',b);self.assertIn('100% accurate trading signals',b)

    def test_oversized_raw_report_cannot_shrink_past_original_safety_limit(self):
        raw='```json\n'+' '*33000+json.dumps(sample(False))+'\n```'
        v=compat.validate_visual_report(raw,1,META)
        self.assertFalse(v['can_forward']);self.assertEqual(v['normalizations'],[])
        self.assertIn('oversized_report',[i['code'] for i in v['issues']])

    def test_invalid_report_cannot_call_auditor_even_with_compatibility(self):
        d=sample(False);d['OBSERVED'][0]['frame']=4;client=Mock()
        with patch.object(agents,'_ollama',client):
            r=agents.auditor('','Speech','```json\n'+json.dumps(d)+'\n```','Shared speech',META)
        client.chat.assert_not_called();self.assertIsNone(r['risk_score'])


if __name__=='__main__':unittest.main()
