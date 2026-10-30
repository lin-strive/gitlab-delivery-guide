#!/usr/bin/env python3
"""Check report consistency; does not contact GitLab or certify evidence authenticity."""

import argparse
import json
import re
import sys
from pathlib import Path


class ResultError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ResultError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def full_sha(value):
    return isinstance(value, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value) is not None


def names(values, label):
    require(isinstance(values, list) and all(text(v) for v in values), label + ' must be a list of names')
    require(len(values) == len(set(values)), label + ' contains duplicates')
    return set(values)


def passed_checks(values, label):
    require(isinstance(values, list) and bool(values), label + ' is missing or empty')
    require(all(isinstance(v, dict) and text(v.get('name')) and v.get('status') == 'passed' for v in values),
            label + ' contains a missing, skipped or unsuccessful check')
    return names([v['name'] for v in values], label)


def check(project, deployment, acceptance, test_script_sha):
    require(all(isinstance(v, dict) for v in (project, deployment, acceptance)), 'Expected JSON objects')
    source = project.get('project', {})
    target = project.get('deployment', {})
    tests = project.get('acceptance', {})
    require(all(isinstance(v, dict) for v in (source, target, tests)), 'Invalid project sections')
    require(str(source.get('id', '')).isdigit(), 'Project ID is not configured')
    require(text(target.get('environment')), 'Deployment environment is not configured')
    require(full_sha(test_script_sha), 'Actual test checkout must be a full commit ID')
    require(full_sha(deployment.get('application_sha')), 'Application commit is not a full commit ID')
    require(str(deployment.get('pipeline_id', '')).isdigit(), 'Deployment pipeline ID is missing')
    require(text(deployment.get('deployment_id')), 'Deployment ID is missing')
    require(str(deployment.get('project_id')) == str(source['id']), 'Deployment belongs to another project')
    require(deployment.get('environment') == target['environment'], 'Deployment targets another environment')
    for key in ('project_id', 'application_sha', 'pipeline_id', 'deployment_id', 'environment'):
        require(str(acceptance.get(key)) == str(deployment.get(key)), 'Acceptance/deployment identity mismatch: ' + key)
    require(acceptance.get('test_script_sha') == test_script_sha, 'Test script commit does not match the actual checkout')
    require(deployment.get('status') == 'healthy', 'Deployment is not healthy')
    health = passed_checks(deployment.get('health_checks'), 'Deployment health checks')
    require(names(target.get('health_checks', []), 'Required health checks') <= health, 'A required health check is missing')
    digests = deployment.get('artifact_digests')
    require(isinstance(digests, dict) and bool(digests), 'Artifact digests are missing')
    require(all(text(k) and isinstance(v, str) and re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', v)
                for k, v in digests.items()), 'Expected SHA-256 file or image digests')
    require(tests.get('node_kind') in ('vm', 'runner'), 'Test node kind is not configured')
    require(text(tests.get('hostname')), 'Expected test hostname is missing')
    require(str(acceptance.get('hostname', '')).casefold() == tests['hostname'].casefold(), 'Wrong test hostname')
    if tests['node_kind'] == 'vm':
        require(text(tests.get('vm_id')), 'Expected VM ID is missing')
        require(acceptance.get('vm_id') == tests['vm_id'], 'Wrong test VM')
    require(tests.get('mode') in ('visible-browser', 'headless-browser', 'api', 'native-desktop'), 'Test mode is not configured')
    require(acceptance.get('mode') == tests['mode'], 'Wrong test mode')
    if tests['mode'] in ('visible-browser', 'native-desktop'):
        require(acceptance.get('headed') is True, 'Visible tests need an interactive session')
    require(acceptance.get('status') == 'passed', 'Acceptance did not pass')
    checks = passed_checks(acceptance.get('checks'), 'Acceptance checks')
    require(names(tests.get('required_checks', []), 'Required acceptance checks') <= checks, 'A required acceptance check is missing')
    scope = names(acceptance.get('scope', []), 'Acceptance scope')
    require(bool(scope) and names(tests.get('scope', []), 'Configured scope') <= scope, 'Acceptance scope is missing')
    if tests.get('write_tests_enabled') is True:
        require(tests.get('write_tests_authorized') is True, 'Write tests lack recorded authorization')
        require(acceptance.get('cleanup') == 'passed', 'Write test cleanup did not pass')
    else:
        require(acceptance.get('cleanup') in ('passed', 'not-required-readonly'), 'Cleanup did not pass')
    return {'status': 'consistent', 'project_id': str(source['id']), 'application_sha': deployment['application_sha'],
            'test_script_sha': test_script_sha, 'pipeline_id': str(deployment['pipeline_id']),
            'health_check_count': len(health), 'acceptance_check_count': len(checks),
            'limitation': 'Input consistency only; verify the real CI jobs and environment separately.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('project', 'deployment', 'acceptance', 'test-script-sha'):
        parser.add_argument('--' + flag, required=True)
    args = parser.parse_args(argv)
    try:
        data = [json.loads(Path(p).read_text(encoding='utf-8-sig'))
                for p in (args.project, args.deployment, args.acceptance)]
        print(json.dumps(check(*data, args.test_script_sha), ensure_ascii=False, indent=2))
        return 0
    except ResultError as exc:
        print('Result check failed: ' + str(exc), file=sys.stderr)
    except (OSError, ValueError, TypeError, KeyError):
        print('Result check failed: invalid or unreadable input; raw report contents omitted.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
