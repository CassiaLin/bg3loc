"""Public sdist -> wheel -> isolated install -> full pytest, with no exclusions.

The offline --wheelhouse option uses ordinary downloaded wheels. Failed tests
remain failures; this tool never converts HTTP denial to PASS or SKIP.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile

import build

PUBLIC_FIXTURES = frozenset({
    'tests/fixtures/b1_02/source_rows.jsonl',
    'tests/fixtures/b1_02/portable_source_rows.jsonl',
    'tests/fixtures/b1_02/ruleset.json',
    'tests/fixtures/b1_02/p3-baseline.json',
    'tests/fixtures/b1_02/p4-identity-baseline.json',
})
FORBIDDEN_PARTS = frozenset({'workspace', '.git', '.venv', '__pycache__', 'build', 'dist'})
FORBIDDEN_SUFFIXES = frozenset({'.pak', '.loca', '.sqlite', '.sqlite3', '.db',
                                '.dll', '.exe', '.pyc', '.pyo', '.pem', '.key'})


def check_public_paths(paths):
    """Fail closed on private/binary artifacts and unsafe archive members."""
    seen = set()
    for name in paths:
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name
                or ':' in name or name in seen):
            raise ValueError(f'Unsafe or duplicate archive path: {name}')
        seen.add(name)
        if (FORBIDDEN_PARTS.intersection(p.casefold() for p in path.parts)
                or path.suffix.casefold() in FORBIDDEN_SUFFIXES
                or path.name.casefold() == '.env'
                or path.name.casefold().startswith(('assignments-local-only', 'responses.', 'blind-review-completed'))):
            raise ValueError(f'Private artifact in distribution: {name}')
        if 'tests/fixtures/' in name:
            relative = name[name.index('tests/fixtures/'):]
            if relative not in PUBLIC_FIXTURES:
                raise ValueError(f'Fixture needs explicit public/synthetic review: {relative}')


def unpack_sdist(archive, destination):
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        if any(not (m.isfile() or m.isdir()) for m in members):
            raise ValueError('Source distribution contains non-regular members')
        check_public_paths([m.name for m in members if m.isfile()])
        # Also validate directory paths before extraction (including traversal).
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe source distribution directory')
        stream.extractall(destination, filter='data')
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError('Expected exactly one sdist project root')
    return roots[0]


def verify_contents(source, extracted, wheel):
    fixtures = {p.relative_to(source).as_posix() for p in (source / 'tests/fixtures').rglob('*') if p.is_file()}
    if fixtures != PUBLIC_FIXTURES:
        raise ValueError('Public fixture inventory differs from reviewed allowlist')
    public_files = [*source.glob('tests/*.py'), *source.glob('tests/fixtures/**/*'),
                    *source.glob('scripts/*'), *source.glob('tools/ci/*.py'),
                    *source.glob('docs/research/b1-03-stage0-contracts/*'),
                    source / '.github/workflows/ci.yml', source / 'examples/demo/run_demo.py']
    for path in public_files:
        if path.is_file() and path.read_bytes() != (extracted / path.relative_to(source)).read_bytes():
            raise ValueError(f'Missing/changed sdist test resource: {path.relative_to(source)}')
    runtime = [p for p in (source / 'src/bg3loc').rglob('*') if p.suffix in {'.py', '.ps1'}]
    schemas = list((source / 'schemas').rglob('*.json'))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        check_public_paths(names)
        for path in runtime:
            relative = path.relative_to(source / 'src').as_posix()
            if path.read_bytes() != archive.read(relative):
                raise ValueError(f'Wheel runtime mismatch: {relative}')
            if path.read_bytes() != (extracted / path.relative_to(source)).read_bytes():
                raise ValueError(f'Sdist runtime mismatch: {relative}')
        for path in schemas:
            relative = path.relative_to(source / 'schemas').as_posix()
            matches = [n for n in names if n.endswith('/data/share/bg3loc/schemas/' + relative)]
            if len(matches) != 1 or archive.read(matches[0]) != path.read_bytes():
                raise ValueError(f'Wheel schema mismatch: {relative}')
            if path.read_bytes() != (extracted / path.relative_to(source)).read_bytes():
                raise ValueError(f'Sdist schema mismatch: {relative}')
        metadata = next(n for n in names if n.endswith('.dist-info/entry_points.txt'))
        if b'bg3loc = bg3loc.cli:main' not in archive.read(metadata):
            raise ValueError('Wheel console entry point missing')
    return {'publicFixtures': len(fixtures), 'runtimeFiles': len(runtime),
            'schemas': len(schemas), 'wheelMembers': len(names),
            'fixtureSha256': {p: hashlib.sha256((source / p).read_bytes()).hexdigest() for p in sorted(fixtures)},
            'privacyPathAudit': 'PASS', 'runtimeResourceByteParity': 'PASS'}


def run(command, cwd, env, log):
    print('STEP:', log.name, flush=True)
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    print(f'EXIT: {result.returncode}; log={log}', flush=True)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path)
    args = parser.parse_args(argv)
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Distribution verification requires a fresh output directory')
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for name in ('PYTHONPATH', 'PYTHONHOME', 'BG3LOC_SCHEMA_DIR', 'PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL'):
        env.pop(name, None)
    env['PYTHONUTF8'] = '1'
    env['PIP_CONFIG_FILE'] = os.devnull
    env['TEMP'] = env['TMP'] = str(output / 'tmp')
    (output / 'tmp').mkdir()
    tempfile.tempdir = env['TEMP']
    os.environ['TEMP'] = os.environ['TMP'] = env['TEMP']
    dist = output / 'dist'
    # Backend uses only explicit test/build dependencies; no mutable source import.
    sdist = Path(build.ProjectBuilder(str(source)).build('sdist', str(dist)))
    extracted = unpack_sdist(sdist, output / 'extracted')
    wheel = Path(build.ProjectBuilder(str(extracted)).build('wheel', str(dist)))
    report = verify_contents(source, extracted, wheel)
    report.update({'sdistBytes': sdist.stat().st_size, 'wheelBytes': wheel.stat().st_size,
                   'sdistSha256': hashlib.sha256(sdist.read_bytes()).hexdigest(),
                   'wheelSha256': hashlib.sha256(wheel.read_bytes()).hexdigest()})
    clean = output / 'venv'
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(clean)
    python = clean / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    pip = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check']
    if args.wheelhouse:
        pip += ['--no-index', '--find-links', str(args.wheelhouse.resolve())]
    else:
        pip += ['--index-url', 'https://pypi.org/simple']
    code = run(pip + [str(wheel) + '[test]'], output, env, output / 'install.txt')
    if code:
        report['installExitCode'] = code
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return code
    smoke = output / 'external-cwd'
    smoke.mkdir()
    check = ('import sys,json,bg3loc; from pathlib import Path; from bg3loc.schema import SchemaStore; '
             'from jsonschema import Draft202012Validator; '
             's=SchemaStore(); assert s.root==Path(sys.prefix)/"share/bg3loc/schemas"; '
             'paths=list(s.root.rglob("*.json")); '
             '[Draft202012Validator.check_schema(json.loads(p.read_bytes())) for p in paths]; '
             '[s.load(p.relative_to(s.root).as_posix()) for p in paths if not p.read_bytes().startswith(b"\\xef\\xbb\\xbf")]; '
             'assert sys.prefix!=sys.base_prefix; '
             'assert Path(bg3loc.__file__).resolve().is_relative_to(Path(sys.prefix)); '
             'print(json.dumps({"schemaCount":len(paths),"version":bg3loc.__version__,"installedModule":bg3loc.__file__, '
             '"legacyBomSchemaStoreLimitation":[p.relative_to(s.root).as_posix() for p in paths if p.read_bytes().startswith(b"\\xef\\xbb\\xbf")]}))')
    commands = [[str(python), '-m', 'pip', 'check'], [str(python), '-I', '-c', check],
                [str(python), '-I', '-m', 'bg3loc.cli', '--version'],
                [str(python), '-I', '-m', 'bg3loc.cli', '--help'],
                [str(python), '-I', '-m', 'bg3loc.cli', 'production', '--help'],
                [str(clean / ('Scripts/bg3loc.exe' if os.name == 'nt' else 'bin/bg3loc')), '--version']]
    for index, command in enumerate(commands):
        code = run(command, smoke, env, output / f'smoke-{index}.txt')
        if code:
            report.update({'cleanInstallSmoke': 'FAIL', 'smokeIndex': index, 'smokeExitCode': code})
            (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            return code
    # Tests deliberately import the extracted sdist code, including subprocesses.
    env['PYTHONPATH'] = str(extracted / 'src')
    collection = run([str(python), '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider'],
                     extracted, env, output / 'collection.txt')
    report['collectionExitCode'] = collection
    if collection:
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return collection
    code = run([str(python), '-m', 'pytest', '-ra', '-p', 'no:cacheprovider',
                '--basetemp=' + str(output / 'pytest-tmp'), '--junitxml=' + str(output / 'tests.xml')],
               extracted, env, output / 'tests.txt')
    report.update({'installExitCode': 0, 'cleanInstallSmoke': 'PASS', 'testsExitCode': code})
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
