"""Display JUnit statistics even when a preceding pytest command failed."""
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def summarize(path):
    path = Path(path)
    if not path.is_file():
        return {'report': path.name, 'status': 'NOT VERIFIED', 'reason': 'missing JUnit'}
    cases = ET.parse(path).getroot().findall('.//testcase')
    failed = sum(c.find('failure') is not None for c in cases)
    errors = sum(c.find('error') is not None for c in cases)
    skipped = sum(c.find('skipped') is not None for c in cases)
    return {'report': path.name, 'status': 'FAIL' if failed or errors else 'PASS',
            'tests': len(cases), 'passed': len(cases) - failed - errors - skipped,
            'failed': failed, 'errors': errors, 'skipped': skipped}


def main(paths):
    results = [summarize(path) for path in paths]
    print(json.dumps(results, indent=2))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as stream:
            stream.write('### Pytest / clean sdist results\n\n')
            stream.write('```json\n' + json.dumps(results, indent=2) + '\n```\n')
    return int(not results or any(r['status'] != 'PASS' for r in results))


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
