import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from app_diagnostics import Trace, start_trace, span, TimedAI, build_identity, _active


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.token = _active.set(None)

    def tearDown(self):
        _active.reset(self.token)

    def test_numeric_trace_does_not_keep_sensitive_arguments(self):
        trace = start_trace()
        client = Mock()
        TimedAI(client).responses.create(input='PRIVATE CLASS DATA', api_key='SECRET',
            text={'format': {'name': 'lesson_resource_batch'}})
        snapshot = trace.snapshot()
        self.assertEqual(snapshot['metrics']['ai.resource_generation']['count'], 1)
        self.assertNotIn('PRIVATE', json.dumps(snapshot))
        self.assertNotIn('SECRET', json.dumps(snapshot))
        self.assertFalse(client.responses.create.call_args.kwargs['store'])

    def test_failure_is_timed_and_original_exception_preserved(self):
        trace = start_trace()
        client = Mock()
        client.responses.create.side_effect = RuntimeError('PRIVATE ERROR')
        with self.assertRaises(RuntimeError):
            TimedAI(client).responses.create(text={'format': {'name': 'lesson_resource_review'}})
        metrics = trace.snapshot()['metrics']['ai.resource_review']
        self.assertEqual(metrics['failures'], 1)
        self.assertNotIn('PRIVATE', json.dumps(trace.snapshot()))

    def test_thread_contexts_do_not_share_metrics(self):
        parent = start_trace()
        def run(name):
            trace = start_trace()
            with span(name):
                pass
            return trace.snapshot()['metrics']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ['one', 'two']))
        self.assertEqual(list(results[0]), ['one'])
        self.assertEqual(list(results[1]), ['two'])
        self.assertEqual(parent.metrics, {})

    def test_build_fingerprint_changes_with_code_but_ignores_data_and_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.py').write_text('version = 1')
            (root / 'requirements.txt').write_text('streamlit')
            first = build_identity(root)
            (root / 'secrets.toml').write_text('SECRET')
            (root / 'backup.json').write_text('PRIVATE')
            self.assertEqual(first, build_identity(root))
            (root / 'app.py').write_text('version = 2')
            self.assertNotEqual(first, build_identity(root))

    def test_explicit_provider_storage_choice_is_not_overwritten(self):
        client = Mock()
        TimedAI(client).responses.create(store=True)
        self.assertTrue(client.responses.create.call_args.kwargs['store'])

    def test_callback_trace_survives_start_of_rerun(self):
        trace = Trace(action=True)
        self.assertIs(start_trace(trace), trace)
        self.assertTrue(trace.action)
