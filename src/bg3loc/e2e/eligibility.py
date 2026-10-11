"""Basic current eligibility, using existing state/manifest hash meanings.

History references are retained; a current completed stage is required too.
No new persistent fields, state version, execution identity or SQLite policy.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import json

from bg3loc.e2e.state import fingerprint_data, load_state, state_path, sha256_file
from bg3loc.source_packages import _ReadPins


def is_basic(config):
    return config.effective['workflow']['evidenceProfile'] == 'basic'


def revoke_downstream(state, start, message):
    names = ['rebuild', 'install-dry-run', 'install']
    for name in names[names.index(start):]:
        state['stages'][name].update(status='invalidated', artifact=None,
            sha256=None, fingerprint=None, message=message)
    # state.artifacts and bindings retain last successful history references.


def input_bindings(selector):
    from bg3loc.e2e.validate import _expand_input
    files = _expand_input(Path(selector))
    if not files:
        raise ValueError('Validated return files are missing; rerun workflow validate')
    return [{'path': str(p.resolve()), 'sha256': sha256_file(p)} for p in files]


@dataclass(frozen=True)
class ValidationBinding:
    manifest: Path
    manifest_sha: str
    accepted: Path
    accepted_sha: str
    input_fingerprint: str
    selector: str
    rebuild_fingerprint: str


def validation_binding(config, state):
    if state['projectConfigSha256'] != config.sha256:
        raise ValueError('Project binding changed; rerun workflow prepare/validate')
    stage = state['stages']['validate']
    translation = state['stages']['translate']
    if stage['status'] != 'completed' or translation['status'] != 'completed':
        raise ValueError('Current validation has not passed; rerun workflow validate')
    selector = translation.get('artifact')
    if not selector:
        raise ValueError('Validated return location is unknown; rerun workflow validate')
    current_returns = input_bindings(selector)
    current_input = fingerprint_data({
        'packageSha256': state['bindings']['translationPackageSha256'],
        'returns': current_returns,
    })
    if translation.get('fingerprint') != current_input:
        raise ValueError('Return files changed since validation; rerun workflow validate')
    manifest = Path(state['artifacts'].get('validateManifest') or '')
    manifest_sha = state['bindings'].get('validationManifestSha256')
    if (not manifest.is_file() or str(manifest) != stage.get('artifact')
            or stage.get('sha256') != manifest_sha or sha256_file(manifest) != manifest_sha):
        raise ValueError('Current validation manifest binding is stale')
    value = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if value.get('strict') is not True or value.get('summary', {}).get('status') != 'pass':
        raise ValueError('Validation snapshot is not a strict PASS')
    if Path(value['buildManifest']).resolve() != Path(state['artifacts']['translationPackage']).resolve():
        raise ValueError('Validation snapshot belongs to another package')
    accepted = Path(value['accepted']['path'])
    if not accepted.is_absolute():
        accepted = manifest.parent / accepted
    accepted_sha = state['bindings'].get('validationAcceptedSha256')
    if not accepted.is_file() or sha256_file(accepted) != accepted_sha:
        raise ValueError('Accepted validation snapshot changed')
    expected = fingerprint_data({
        'validationManifestSha256': manifest_sha,
        'validationAcceptedSha256': accepted_sha,
        'extractManifestSha256': state['bindings'].get('extractManifestSha256'),
    })
    for item in state['bindings'].get('qaRuleSets', []):
        configured = next((r for r in config.resolved['qa']['ruleSets'] if r['id'] == item['id']), None)
        if configured is None or sha256_file(Path(configured['path'])) != item['sha256']:
            raise ValueError('QA rule material changed; rerun workflow prepare/validate')
    review_sha = state['bindings'].get('reviewIntegrationSha256')
    if review_sha:
        integration = Path(config.resolved['workspace']['root']) / 'e2e/review/e2e-review-integration.json'
        if not integration.is_file() or sha256_file(integration) != review_sha:
            raise ValueError('Review integration changed; rerun workflow validate')
    expected_validation = fingerprint_data({
        'base': fingerprint_data({
            'packageSha256': state['bindings']['translationPackageSha256'],
            'returns': current_returns,
            'reviewGate': True,
        }),
        'reviewIntegrationSha256': review_sha,
    })
    if stage.get('fingerprint') != expected_validation:
        raise ValueError('Current validation fingerprint does not match its inputs/review')
    return ValidationBinding(manifest, manifest_sha, accepted, accepted_sha,
        current_input, selector, expected)


def rebuild_binding(state, validation):
    stage = state['stages']['rebuild']
    path = Path(state['artifacts'].get('rebuildManifest') or '')
    expected = state['bindings'].get('rebuildManifestSha256')
    if (stage['status'] != 'completed' or stage.get('fingerprint') != validation.rebuild_fingerprint
            or str(path) != stage.get('artifact') or stage.get('sha256') != expected
            or not path.is_file() or sha256_file(path) != expected):
        raise ValueError('No current rebuild for this accepted validation snapshot')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if Path(value.get('validateManifest', '')).resolve() != validation.manifest.resolve():
        raise ValueError('Rebuild references another validation snapshot')
    artifacts = []
    if not value.get('artifacts'):
        raise ValueError('Rebuild contains no artifacts')
    for item in value['artifacts']:
        artifact = Path(item['path'])
        if not artifact.is_absolute():
            artifact = path.parent / artifact
        if not artifact.resolve().is_relative_to(path.parent.resolve()):
            raise ValueError('Rebuild artifact is outside its successful snapshot')
        if not artifact.is_file() or sha256_file(artifact) != item['sha256']:
            raise ValueError('Current rebuild artifact hash changed')
        artifacts.append(artifact)
    return path, artifacts


class EligibilitySession:
    def __init__(self, config, state, *, require_rebuild=False):
        self.config = config
        self.pins = _ReadPins()
        self._files = {}
        self.closed = False
        self.require_rebuild = require_rebuild
        try:
            self.validation = validation_binding(config, state)
            for item in input_bindings(self.validation.selector):
                self._pin(Path(item['path']), item['sha256'])
            self._pin(self.validation.manifest, self.validation.manifest_sha)
            self._pin(self.validation.accepted, self.validation.accepted_sha)
            if require_rebuild:
                manifest, artifacts = rebuild_binding(state, self.validation)
                self._pin(manifest, state['bindings']['rebuildManifestSha256'])
                for artifact in artifacts:
                    self._pin(artifact, sha256_file(artifact))
            self.check()
        except BaseException:
            self.close()
            raise

    def _pin(self, path, expected):
        self.pins.add(path)
        if sha256_file(path) != expected:
            raise ValueError('Workflow snapshot changed during preflight')
        self._files[path] = expected

    def check(self):
        if self.closed:
            raise ValueError('Workflow eligibility session is closed')
        self.pins.check()
        for path, expected in self._files.items():
            if sha256_file(path) != expected:
                raise ValueError('Workflow input/artifact changed during operation')
        state = load_state(state_path(self.config))
        if validation_binding(self.config, state) != self.validation:
            raise ValueError('Current validation changed during operation')
        if self.require_rebuild:
            rebuild_binding(state, self.validation)

    def close(self):
        self.pins.close()
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.check()
        finally:
            self.close()


@contextmanager
def current_eligibility(config, state, *, require_rebuild=False):
    if not is_basic(config):
        yield None
        return
    with EligibilitySession(config, state, require_rebuild=require_rebuild) as session:
        yield session
