"""Operation-scoped legacy source evidence; uses existing QA/manifest hashes.

No schema, execution identity or persisted fingerprint is introduced. Source
strings are immutable projections; Windows pins deny writes/deletion while an
operation is active. Other hosts recheck bytes/paths before returning/committing.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType

from bg3loc.qa import QaInput, qa_input_hash
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.source_packages import _ReadPins


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate source material JSON field')
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class LegacyQaSource:
    content_uid: str
    batch_id: str
    source_text: str
    category: str

    def input(self, text: str) -> QaInput:
        return QaInput(self.content_uid, self.source_text, text, self.category,
                       tuple(extract_protected_tokens(self.source_text)))


def actual_output_current(text, declared) -> bool:
    return type(text) is str and type(declared) is str and bool(declared) and (
        hashlib.sha256(text.encode('utf-8')).hexdigest() == declared)


class LegacyQaMaterial:
    def __init__(self, database, batch_plan=None, *, connection=None):
        self.database = Path(database).resolve()
        self._pins = _ReadPins()
        self._files = {}
        self._closed = False
        try:
            self._load(batch_plan, connection)
        except Exception as exc:
            self.close()
            raise ValueError('Legacy prepared source material is missing, ambiguous or invalid') from exc

    def _read(self, path):
        path = Path(path).absolute()
        self._pins.add(path)
        raw = path.read_bytes()
        self._files[path] = hashlib.sha256(raw).hexdigest()
        return raw

    def _json(self, path):
        return json.loads(self._read(path).decode('utf-8-sig'), object_pairs_hook=_unique_object)

    def _load(self, supplied, connection):
        marker = self.database.parent / 'production-manifest.json'
        manifest = None
        if marker.exists():
            manifest = self._json(marker)
            if manifest.get('schemaVersion') not in {'1.0', '1.1', '1.2'}:
                raise ValueError('Not a legacy workspace')
            recorded = self.database.parent / manifest['batching']['batchPlan']
            from bg3loc.production_workspace import _workspace_file
            _workspace_file(manifest['batching']['batchPlan'], workspace=self.database.parent, label='QA plan')
            if supplied is not None and Path(supplied).resolve() != recorded.resolve():
                raise ValueError('Batch plan does not belong to prepared workspace')
            self.plan = recorded.absolute()
            # Pin files consumed by the accepted workspace/material validators.
            rules = self.database.parent / manifest['inputs']['ruleset']['path']
            _workspace_file(manifest['inputs']['ruleset']['path'], workspace=self.database.parent, label='QA ruleset')
            self._read(rules)
            if manifest.get('sameEntityContext'):
                _workspace_file(manifest['sameEntityContext']['summaryPath'], workspace=self.database.parent, label='QA summary')
                self._read(self.database.parent / manifest['sameEntityContext']['summaryPath'])
        else:
            candidates = [Path(supplied).absolute()] if supplied is not None else [
                self.database.parent / 'batches/batch-plan.json',
                self.database.parent / 'plan/batch-plan.json',
                self.database.parent / 'batch-plan.json']
            candidates = [p for p in candidates if p.is_file()]
            if len(candidates) != 1:
                raise ValueError('Exactly one prepared batch plan is required')
            self.plan = candidates[0]
        plan = self._json(self.plan)
        if type(plan) is not dict or type(plan.get('batches')) is not list:
            raise ValueError('Invalid batch plan')
        from bg3loc.dialogue_execution_contract import guard_material_family
        from bg3loc.production_context import context_from_material
        rows, batches = {}, set()
        for batch in plan['batches']:
            name, category = batch.get('batchId'), batch.get('primaryCategory')
            if type(name) is not str or not name or Path(name).name != name or '\\' in name or ':' in name or name in batches:
                raise ValueError('Invalid/duplicate batch identity')
            if type(category) is not str or not category:
                raise ValueError('Missing material category')
            batches.add(name)
            material = self.plan.parent / 'materials' / f'{name}.jsonl'
            lines = self._read(material).decode('utf-8-sig').splitlines()
            count = 0
            for line in lines:
                if not line.strip():
                    continue
                row = json.loads(line, object_pairs_hook=_unique_object)
                if type(row) is not dict:
                    raise ValueError('Invalid source material row')
                guard_material_family(row, None if manifest is None else manifest['schemaVersion'])
                uid, source = row.get('contentUid', row.get('ContentUid')), row.get('sourceText', row.get('SourceText'))
                if type(uid) is not str or not uid or uid in rows or type(source) is not str:
                    raise ValueError('Missing/duplicate target or source text')
                if ('ContentUid' in row and row['ContentUid'] != uid) or ('SourceText' in row and row['SourceText'] != source):
                    raise ValueError('Conflicting source field aliases')
                if row.get('batchId', name) != name or row.get('primaryCategory', category) != category:
                    raise ValueError('Target batch/category mismatch')
                context_from_material(row)  # Existing strict HSE decoder/target binding.
                rows[uid] = LegacyQaSource(uid, name, source, category)
                count += 1
            if type(batch.get('recordCount')) is not int or count != batch['recordCount']:
                raise ValueError('Incomplete source batch')
        self.rows = MappingProxyType(rows)
        if manifest is not None:
            from bg3loc.production_workspace import verify_production_workspace
            binding = verify_production_workspace(self.database.parent)
            if binding.database.resolve() != self.database or binding.batch_plan.resolve() != self.plan.resolve():
                raise ValueError('Prepared database/material path mismatch')
        with closing(sqlite3.connect(self.database)) if connection is None else _borrow(connection) as conn:
            if Path(next(r[2] for r in conn.execute('PRAGMA database_list') if r[1] == 'main')).resolve() != self.database:
                raise ValueError('Foreign source database connection')
            metadata = dict(conn.execute('SELECT key,value FROM metadata'))
            if manifest is None and metadata.get('executionContextContractFingerprint'):
                raise ValueError('Context material requires its sealed workspace')
            self.inputs = MappingProxyType({uid: (batch, value) for uid, batch, value in conn.execute(
                'SELECT content_uid,batch_id,input_hash FROM content_state')})
        if set(self.inputs) != set(rows) or any(self.inputs[k][0] != rows[k].batch_id for k in rows):
            raise ValueError('Prepared material/database inventory mismatch')
        self.check()

    def source(self, uid, state):
        if self._closed:
            raise ValueError('Legacy source snapshot is closed')
        row = self.rows[uid]
        if (state['batch_id'], state['input_hash']) != self.inputs[uid]:
            raise ValueError('Current input/material binding changed')
        return row

    def current(self, uid, state, stored_qa_hash):
        if not actual_output_current(state['translated_text'], state['output_hash']):
            return False
        return qa_input_hash(self.source(uid, state).input(state['translated_text'])) == stored_qa_hash

    def check(self):
        if self._closed:
            raise ValueError('Legacy source snapshot is closed')
        self._pins.check()
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != expected for p, expected in self._files.items()):
            raise ValueError('Legacy prepared source material changed')

    def close(self):
        self._pins.close()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.check()
        finally:
            self.close()


def _borrow(connection):
    from contextlib import nullcontext
    return nullcontext(connection)
