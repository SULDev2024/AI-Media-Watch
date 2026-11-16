"""Offline unit tests only: synthetic images, saved text, and mocked model calls.

Run this module explicitly. Do not discover the older integration-test scripts.
"""
import ast
import json
import socket
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import cv2
import numpy as np
import agents
from vision_engine import select_informative_frames
from visual_evidence import prepare_visual_evidence, VISUAL_MAX_UTF8_BYTES, PROMPT_MAX_UTF8_BYTES

ROOT = Path(__file__).resolve().parent


def slide(words, background=0):
    im = np.full((180, 320, 3), background, dtype=np.uint8)
    color = (255, 255, 255) if background < 128 else (0, 0, 0)
    for n, text in enumerate(words):
        cv2.putText(im, text, (8, 35+n*40), cv2.FONT_HERSHEY_SIMPLEX, .6, color, 1, cv2.LINE_AA)
    return im


class VisualV2Tests(unittest.TestCase):
    def setUp(self):
        self.no_network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network prohibited'))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)

    def test_dark_text_slide_survives_and_blank_transitions_do_not(self):
        frames = [np.zeros((180, 320, 3), np.uint8),
                  np.full((180, 320, 3), 16, np.uint8),
                  slide(['Guaranteed Profits', '100% ACCURACY'])]
        indices, data = select_informative_frames(frames)
        self.assertEqual(indices, [2])
        self.assertFalse(data['candidates'][2]['blank'])

    def test_distinct_content_and_temporal_coverage_with_three_budget(self):
        blank = np.zeros((180, 320, 3), np.uint8)
        a = slide(['Guaranteed Profits', 'Return 100%'])
        b = slide(['PAYMENT REQUEST', 'SEND TO WALLET'], 230)
        c = slide(['WARNING: FRAUD', 'Do not send money'])
        frames = [blank, a, a.copy(), blank, b, b.copy(), blank, c, blank]
        indices, data = select_informative_frames(frames)
        self.assertEqual(indices, [1, 4, 7])
        self.assertEqual(data['useful_distinct_count'], 3)

    def test_no_duplicate_padding_when_fewer_useful_frames(self):
        a = slide(['Useful text'])
        indices, _ = select_informative_frames([a, a.copy(), a.copy()])
        self.assertEqual(len(indices), 1)

    def test_empty_all_blank_and_budget_validation(self):
        self.assertEqual(select_informative_frames([])[0], [])
        self.assertEqual(select_informative_frames([np.zeros((30, 30, 3), np.uint8)])[0], [])
        with self.assertRaises(ValueError):
            select_informative_frames([], 0)
        frames = [slide([f'Different {i}', str(i)*10], 20*i) for i in range(5)]
        self.assertLessEqual(len(select_informative_frames(frames, 10)[0]), 3)

    def test_saved_reports_pass_in_full_including_late_claims(self):
        for folder in ('reviewer2_issue3_new_new_2026-11-08',
                       'reviewer2_issue3_crypto_run_2026-11-08'):
            report = json.loads((ROOT/folder/'vision.json').read_text(encoding='utf-8'))['visual_report']
            text, state = prepare_visual_evidence(report, {'done_reason': 'length'})
            self.assertIn(report, text)
            self.assertFalse(state['evidence_truncated'])
            self.assertEqual(state['generation_status'], 'incomplete')
            if 'crypto' in folder:
                self.assertIn('Referral Code 287839925', text)
                self.assertIn('t.me/megvipofficial', text)

    def test_oversized_multilingual_report_has_bounded_head_tail_and_marker(self):
        report = 'Guaranteed Profits\n' + '证据' * 2500 + '\nWallet at end: abc123'
        text, state = prepare_visual_evidence(report, {'done_reason': 'stop'})
        self.assertLessEqual(len(text.encode('utf-8')), VISUAL_MAX_UTF8_BYTES)
        self.assertIn('Guaranteed Profits', text)
        self.assertIn('Wallet at end: abc123', text)
        self.assertIn('omitted by byte budget', text)
        self.assertTrue(state['evidence_truncated'])
        self.assertEqual(state['generation_status'], 'complete')

    def test_unknown_generation_is_explicit_and_tiny_budget_fails(self):
        text, state = prepare_visual_evidence('Observed words')
        self.assertIn('generation: unknown', text)
        with self.assertRaises(ValueError):
            prepare_visual_evidence('X'*1000, available_bytes=20)

    def test_speech_only_prompt_and_auditor_options_unchanged(self):
        folder = ROOT/'reviewer2_issue3_new_new_2026-11-08'
        transcript = json.loads((folder/'transcription.json').read_text())['text']
        speech = json.loads((folder/'speech.json').read_text())['speech_report']
        old = json.loads((folder/'speech_only_request.json').read_text())['request']
        client = Mock()
        client.chat.return_value = {'message': {'content': '{"risk_score":60,"flags":[]}'}}
        with patch.object(agents, '_ollama', client):
            agents.auditor('', transcript, '', speech)
        call = client.chat.call_args.kwargs
        self.assertEqual(call['messages'], old['messages'])
        self.assertEqual(call['model'], old['model'])
        self.assertEqual(call['options'], {'num_ctx':4096,'num_predict':128})

    def test_paired_prompt_only_visual_changes_and_old_late_evidence_reaches_auditor(self):
        client = Mock()
        client.chat.return_value = {'message': {'content':'{"risk_score":60,"flags":[]}'}}
        visual = 'Factual introduction.\n' + 'x'*600 + '\nGuaranteed Profits; t.me/example'
        with patch.object(agents, '_ollama', client):
            agents.auditor('', 'Exact transcript', '', 'Same speech report')
            result = agents.auditor('', 'Exact transcript', visual, 'Same speech report', {'done_reason':'length'})
        a, b = [c.kwargs for c in client.chat.call_args_list]
        pa, pb = [c['messages'][0]['content'] for c in (a,b)]
        actual = pb.split('\nVisual: ',1)[1].split('\nSpeech: ',1)[0]
        self.assertIn('Guaranteed Profits; t.me/example', actual)
        self.assertEqual(pa.replace('Visual: \nSpeech:', 'Visual: '+actual+'\nSpeech:'), pb)
        self.assertEqual(a['options'], b['options'])
        self.assertFalse(result['visual_evidence_status']['evidence_truncated'])
        self.assertEqual(result['visual_evidence_status']['generation_status'], 'incomplete')
        self.assertLessEqual(len(pb.encode('utf-8')), PROMPT_MAX_UTF8_BYTES)

    def test_context_preflight_fails_without_model_call(self):
        client = Mock()
        with patch.object(agents, '_ollama', client), self.assertRaises(ValueError):
            agents.auditor('x'*5000, 'Transcript', 'Evidence', 'Speech')
        client.chat.assert_not_called()

    def test_vision_prompt_metadata_budget_and_cpu_with_mock(self):
        client = Mock()
        client.chat.return_value = {'message':{'content':'Visible quote: Guaranteed Profits'},
                                    'done_reason':'length','done':True,'eval_count':384}
        frames = [slide(['Guaranteed Profits']), np.zeros((180,320,3),np.uint8)]
        with patch.object(agents, '_ollama', client):
            result = agents.vision_eye(frames)
        call = client.chat.call_args.kwargs
        self.assertEqual(len(call['messages'][0]['images']), 1)
        self.assertEqual(call['options'], {'num_ctx':4096,'num_predict':384,'num_gpu':0})
        self.assertIn('Do not treat cryptocurrency or trading alone', call['messages'][0]['content'])
        self.assertEqual(result['visual_report_metadata']['done_reason'], 'length')
        self.assertEqual(result['frame_selection']['selected_indices'], [0])

    def test_all_blank_skips_qwen(self):
        client = Mock()
        with patch.object(agents, '_ollama', client):
            result = agents.vision_eye([np.zeros((30,30,3),np.uint8)])
        client.chat.assert_not_called()
        self.assertEqual(result['visual_report_metadata']['done_reason'], 'skipped_no_informative_frames')

    def test_speech_function_and_original_model_names_preserved(self):
        original = ast.parse((ROOT/'visual_pipeline_v2_2026-11-08/original/agents.py').read_text())
        current = ast.parse((ROOT/'agents.py').read_text())
        fn = lambda tree: next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name=='speech_analyst')
        self.assertEqual(ast.dump(fn(original)), ast.dump(fn(current)))
        self.assertEqual(agents.AUDITOR_MODEL, 'llama3:latest')
        self.assertEqual(agents.SPEECH_MODEL, 'mistral:latest')
        self.assertEqual(agents.VISION_MODEL, 'qwen2.5vl:latest')

    def test_unavailable_and_parse_error_still_record_evidence_status(self):
        text, state = prepare_visual_evidence('No informative frames selected',
                                             {'done_reason':'skipped_no_informative_frames'})
        self.assertEqual(state['generation_status'], 'unavailable')
        client = Mock()
        client.chat.return_value = {'message':{'content':'invalid JSON'}}
        with patch.object(agents, '_ollama', client):
            result = agents.auditor('', '', 'Actual report', '', {'done_reason':'length'})
        self.assertIn('parse_error', result['flags'])
        self.assertEqual(result['visual_evidence_status']['generation_status'], 'incomplete')

    def test_rerun_uses_all_candidates_without_loading_asr_or_speech_model(self):
        namespace = runpy.run_path(str(ROOT/'visual_pipeline_v2_2026-11-08/rerun_new_new.py'), run_name='offline_test')
        worker = namespace['worker']
        with tempfile.TemporaryDirectory(dir=ROOT/'visual_pipeline_v2_2026-11-08') as temp:
            out = Path(temp)
            # Verify the automatic recursive cleanup target stays in our workspace.
            self.assertTrue(out.resolve().is_relative_to((ROOT/'visual_pipeline_v2_2026-11-08').resolve()))
            frames = np.stack([slide([f'Frame {i}']) for i in range(9)])
            np.save(out/'candidate_frames.npy', frames)
            for name, value in [('configuration.json', {'video':'not-opened.mp4','sha256':'mock'}),
                                ('transcription.json', {'text':'Verified speech'}),
                                ('frames.json', {'all_timestamps':list(range(9))})]:
                (out/name).write_text(json.dumps(value))
            original = agents._ollama
            try:
                with patch.dict(worker.__globals__, {'OUT':out,'sha':lambda path:'mock'}), \
                     patch.dict(os.environ, {'AI_MEDIA_WATCH_V2_APPROVED':'1'}), \
                     patch.object(agents,'vision_eye', return_value={'visual_report':'Quoted claim',
                                  'frame_selection':{'selected_indices':[1,4,7]}}) as vision:
                    worker('vision')
                    self.assertEqual(len(vision.call_args.args[0]), 9)
                    result = json.loads((out/'vision.json').read_text())
                    self.assertEqual(result['selected_timestamps'], [1,4,7])
            finally:
                agents._ollama = original

    def test_rerun_rejects_unapproved_worker_and_has_no_asr_call(self):
        file = ROOT/'visual_pipeline_v2_2026-11-08/rerun_new_new.py'
        namespace = runpy.run_path(str(file), run_name='offline_test')
        with patch.dict(os.environ, {'AI_MEDIA_WATCH_V2_APPROVED':'0'}), self.assertRaises(AssertionError):
            namespace['worker']('vision')
        tree = ast.parse(file.read_text())
        calls = [n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertNotIn('speech_analyst', calls)
        self.assertNotIn('transcribe', calls)


if __name__ == '__main__':
    unittest.main()
