# Public tests and distribution checks

From a Git checkout or an unpacked source distribution, use a clean virtual
environment and install the test extra:

```text
python -m venv .venv
# Activate .venv using your platform's shell.
python -m pip install -e ".[test]"
python -m pytest --collect-only -q
python -m pytest -ra --junitxml=workspace/tests.xml
python tools/ci/verify_distribution.py --output workspace/distribution-check
```

The distribution checker builds an sdist, rebuilds its wheel, compares runtime
modules and schemas, audits archive paths, installs the wheel in a second fresh
venv, checks its console command and installed schemas from an unrelated working
directory, and collects/runs the complete test suite from the extracted sdist.
It never excludes the HTTP demo or turns an unavailable socket into a PASS.
The output directory must be new or empty; existing evidence is not overwritten.
For offline operation, supply `--wheelhouse` pointing to downloaded compatible
runtime/test/build dependency wheels. This is dependency installation isolation,
not a claim that every dependency version produces byte-identical ZIP/tar headers.

CI runs all pytest tests on Windows and Ubuntu with Python 3.11 and 3.12. All PRs,
pushes and manual dispatches trigger it, including docs/schema/packaging changes.
JUnit, command logs and summary statistics remain available after a failure.
`tools/ci/check_loopback.py` diagnoses real local HTTP before the suite; a denial
fails the step. The complete suite still runs to reveal other failures.

The five JSON/JSONL files in `tests/fixtures/b1_02/` are invented public examples
and frozen fingerprints of invented inputs. They contain no BG3 corpus, PAK,
LOCA, API credentials or hidden assignments. The distribution checker requires
their exact reviewed inventory; new fixtures need an explicit public/synthetic
review and an update to its allowlist. Test code creates other synthetic inputs
in temporary directories. Source archives also include scripts, examples,
runtime schemas and Stage 0 document contracts required by the tests.

All installed JSON schemas receive byte-parity and JSON/schema structure checks.
Three existing `research/research-{mapping,scan,summary}.schema.json` files carry
a UTF-8 BOM: the generic `SchemaStore.load()` does not accept that encoding.
The checker reports this existing limitation, retains all three files, validates
their bytes with a BOM-aware JSON parser, and exercises `SchemaStore` on every
non-BOM runtime resource. It does not modify the schemas or runtime parser.

Tests in `tests/` use mocked/invented archive backends; they do not need Divine
or a BG3 installation. Existing Windows-only mapped-section/reparse/handle tests
retain explicit platform limitations; symlink creation may be unavailable on a
restricted host. These skips are reported. Native LSLib and real-installation
validation remain separate integration work: acquire LSLib independently and
use the documented Windows acceptance workflow with your own lawful game data.
`scripts/test_research_integration.py` is not the official pytest entry point,
and its missing-backend early exit is not evidence of native integration PASS.

A local sandbox may block loopback HTTP (for example WinError 10013). Record the
failed test and environment limitation separately; do not remove it from CI or
claim the full suite passed. GitHub-hosted Windows/Ubuntu success must be observed
on the actual runners. YAML validation alone is not a hosted CI result.
