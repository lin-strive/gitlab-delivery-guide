"""Offline report invariants using synthetic projects; no network or deployments."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from check_result import ResultError, check, main


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.project = {'project': {'id': 17}, 'deployment': {'environment': 'test', 'health_checks': ['ready']},
                        'acceptance': {'node_kind': 'vm', 'hostname': 'test-vm', 'vm_id': 'vm-a',
                                       'mode': 'visible-browser', 'required_checks': ['query'], 'scope': ['readonly']}}
        self.identity = dict(project_id='17', application_sha='a' * 40, pipeline_id='21', deployment_id='run-21', environment='test')
        self.deployment = dict(self.identity, status='healthy', health_checks=[dict(name='ready', status='passed')],
                               artifact_digests={'bundle': 'sha256:' + 'b' * 64})
        self.acceptance = dict(self.identity, test_script_sha='c' * 40, status='passed', mode='visible-browser',
                               hostname='TEST-VM', vm_id='vm-a', headed=True, scope=['readonly'],
                               checks=[dict(name='query', status='passed')], cleanup='not-required-readonly')

    def check(self):
        return check(self.project, self.deployment, self.acceptance, 'c' * 40)

    def test_valid_reports_and_independent_test_script_version(self):
        self.assertEqual(self.check()['status'], 'consistent')
        self.acceptance['test_script_sha'] = 'a' * 40
        with self.assertRaises(ResultError): self.check()

    def test_all_deployment_identity_mismatches_are_rejected(self):
        original = copy.deepcopy(self.acceptance)
        for key in self.identity:
            self.acceptance = dict(original, **{key: 'different'})
            with self.subTest(key=key), self.assertRaises(ResultError): self.check()

    def test_wrong_node_mode_and_session_are_rejected(self):
        original = copy.deepcopy(self.acceptance)
        for key, value in [('vm_id', 'vm-b'), ('hostname', 'other-vm'), ('mode', 'api'), ('headed', False)]:
            self.acceptance = dict(original, **{key: value})
            with self.subTest(key=key), self.assertRaises(ResultError): self.check()

    def test_missing_skipped_failed_and_duplicate_checks_are_rejected(self):
        for checks in ([], [dict(name='query', status='skipped')], [dict(name='query', status='failed')],
                       [dict(name='other', status='passed')], [dict(name='query', status='passed')] * 2):
            self.acceptance['checks'] = checks
            with self.subTest(checks=checks), self.assertRaises(ResultError): self.check()

    def test_write_cleanup_and_recorded_authorization_are_required(self):
        self.project['acceptance']['write_tests_enabled'] = True
        with self.assertRaises(ResultError): self.check()
        self.project['acceptance']['write_tests_authorized'] = True
        with self.assertRaises(ResultError): self.check()
        self.acceptance['cleanup'] = 'passed'
        self.assertEqual(self.check()['status'], 'consistent')

    def test_unhealthy_missing_health_and_invalid_digest_are_rejected(self):
        original = copy.deepcopy(self.deployment)
        for changes in ({'status': 'failed'}, {'health_checks': []}, {'artifact_digests': {}},
                        {'artifact_digests': {'bundle': 'latest'}}):
            self.deployment = dict(original, **changes)
            with self.subTest(changes=changes), self.assertRaises(ResultError): self.check()

    def test_unconfigured_template_cannot_pass(self):
        template = Path(__file__).resolve().parents[1] / 'assets/project-config.template.json'
        self.project = json.loads(template.read_text(encoding='utf8'))
        with self.assertRaises(ResultError): self.check()

    def test_cli_returns_failure_without_dumping_private_input(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'private.json'
            p.write_text('invalid PRIVATE_INPUT_SENTINEL', encoding='utf8')
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                code = main(['--project', str(p), '--deployment', str(p), '--acceptance', str(p), '--test-script-sha', 'c' * 40])
            self.assertEqual(code, 2)
            self.assertNotIn('PRIVATE_INPUT_SENTINEL', output.getvalue())


if __name__ == '__main__':
    unittest.main()
