"""CI/package regressions using public source and invented archive members."""
import importlib.util
from pathlib import Path
import tarfile
import io
import tomllib
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools/ci' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_collects_and_runs_every_test_on_both_platforms():
    workflow = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    assert set(workflow['on']) == {'pull_request', 'push', 'workflow_dispatch'}
    assert all(event is None or not isinstance(event, dict) or
               not {'paths', 'paths-ignore'} & event.keys() for event in workflow['on'].values())
    job = workflow['jobs']['test']
    assert set(job['strategy']['matrix']['os']) == {'windows-latest', 'ubuntu-latest'}
    assert set(job['strategy']['matrix']['python']) == {'3.11', '3.12'}
    assert job['strategy']['fail-fast'] == 'false'
    assert int(job['timeout-minutes']) >= 20
    steps = job['steps']
    commands = [s['run'] for s in steps if 'run' in s]
    assert any('install -e ".[test]"' in c for c in commands)
    assert 'python -m pytest --collect-only -q' in commands
    assert any(c.startswith('python -m pytest -ra --junitxml=') for c in commands)
    assert not any('unittest discover' in c or '--ignore' in c or '--deselect' in c or '-k ' in c for c in commands)
    assert any('check_loopback.py' in c for c in commands)
    assert any('verify_distribution.py' in c for c in commands)
    assert any('summarize_tests.py' in c for c in commands)
    assert workflow['permissions'] == {'contents': 'read'}
    assert any('upload-artifact' in s.get('uses', '') and 'cancelled' in s['if'] for s in steps)
    extras = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['optional-dependencies']['test']
    assert any(d.startswith('pytest>=9') for d in extras)
    assert any(d.startswith('build>=') for d in extras)
    assert any(d.startswith('PyYAML>=') for d in extras)


@pytest.mark.parametrize('member', ['p/workspace/private.jsonl', 'p/game.PAK', 'p/foo.LOCA',
    'p/execution.sqlite3', 'p/Divine.exe', 'p/assignments-local-only.jsonl', 'p/responses.jsonl',
    'p/.env', '../escape', '/absolute', 'p\\escape', 'C:/escape',
    'p/tests/fixtures/unreviewed.json', 'p/test.pem'])
def test_archive_privacy_and_member_paths_fail_closed(member):
    tool = load_tool('verify_distribution')
    with pytest.raises(ValueError):
        tool.check_public_paths([member])


def test_public_fixture_inventory_and_duplicate_paths():
    tool = load_tool('verify_distribution')
    actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'tests/fixtures').rglob('*') if p.is_file()}
    assert actual == tool.PUBLIC_FIXTURES
    tool.check_public_paths(['project/' + p for p in actual])
    with pytest.raises(ValueError):
        tool.check_public_paths(['project/README.md', 'project/README.md'])


@pytest.mark.parametrize('kind', ['traversal', 'symlink', 'device'])
def test_unpack_rejects_unsafe_archive_without_writing_outside(tmp_path, kind):
    archive = tmp_path / 'invented.tar.gz'
    with tarfile.open(archive, 'w:gz') as stream:
        member = tarfile.TarInfo('../escape' if kind == 'traversal' else 'project/file')
        if kind == 'symlink':
            member.type = tarfile.SYMTYPE
            member.linkname = '../outside'
        elif kind == 'device':
            member.type = tarfile.CHRTYPE
        else:
            member.size = 1
        stream.addfile(member, io.BytesIO(b'x') if kind == 'traversal' else None)
    with pytest.raises(ValueError):
        load_tool('verify_distribution').unpack_sdist(archive, tmp_path / 'extract')
    assert not (tmp_path / 'escape').exists()


def test_junit_summary_does_not_hide_failures_errors_skips_or_missing_report(tmp_path):
    junit = tmp_path / 'report.xml'
    junit.write_text('<testsuites><testsuite><testcase/><testcase><failure/></testcase>'
                     '<testcase><error/></testcase><testcase><skipped/></testcase></testsuite></testsuites>')
    tool = load_tool('summarize_tests')
    assert tool.summarize(junit) == {'report': 'report.xml', 'status': 'FAIL',
                                    'tests': 4, 'passed': 1, 'failed': 1, 'errors': 1, 'skipped': 1}
    assert tool.summarize(tmp_path / 'missing.xml')['status'] == 'NOT VERIFIED'
    assert tool.main([junit]) == 1


def test_loopback_denial_is_failure_not_pass():
    tool = load_tool('check_loopback')
    exc = OSError('invented socket denial')
    exc.winerror = 10013
    with patch.object(tool, 'ThreadingHTTPServer', side_effect=exc):
        assert tool.main() == 1


def test_manifest_keeps_tests_helpers_and_ci_resources():
    manifest = (ROOT / 'MANIFEST.in').read_text()
    assert 'graft tests' in manifest and 'graft scripts' in manifest
    assert 'graft tools/ci' in manifest and 'include .github/workflows/ci.yml' in manifest
    assert 'prune workspace' in manifest
