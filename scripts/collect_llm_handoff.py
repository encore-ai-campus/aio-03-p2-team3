"""Offline recovery only. No API, key reads, checkout, fetch, or source edits.

Run on the existing PC copy before applying changes from another workspace.
The private snapshot stays on the PC; share only source-comparison.zip.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

BASELINE_COMMIT = 'a24e2d5efd02ac9097accaeed132d0719fb669c2'
BASELINE_HASHES = {
    'app/evaluation/model_benchmark.py': '9d7a0ecb0bac5591f60d8f5bb607c2491ec6e5d0cb11f02cfbef14bd3c61739b',
    'tests/test_model_benchmark.py': '3fe84453b3edc427b4b3614896be4f9fb71df8942589d498383d240010354b07',
    'docs/plans/llm-quality-and-cost.md': '0d7bbd89ada746adb3a1561f63de0004014a71dabc674e4f5a40eaee698e8bde',
    'docs/PROJECT_CONTEXT.md': '5c087652c45c15d7b9291e64facad772cd496715dff3ddf922cab8c5a03a2948',
}
CALL_FIELDS = ('case_id', 'kind', 'model', 'effort', 'repeat', 'timeout_seconds',
               'max_output_tokens', 'input_sha256', 'status', 'generation_attempts',
               'preflight_input_tokens', 'reserved_usd', 'provider_status', 'response_id',
               'returned_model', 'returned_service_tier', 'duration_ms', 'validation_error_type')
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens',
                'estimated_usd', 'cache_breakdown_known')


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
    return result.stdout if result.returncode == 0 else None


def sanitized_calls(data):
    """Whitelist usage and identifiers; never copy model text or exceptions."""
    reports = data.get('reports', [data])
    for report in reports:
        if report.get('mode') != 'live':
            continue
        for call in report.get('calls', []):
            row = {key: call[key] for key in CALL_FIELDS if key in call}
            usage = call.get('usage')
            row['usage'] = ({key: usage[key] for key in USAGE_FIELDS if key in usage}
                            if isinstance(usage, dict) else None)
            yield row


def inventory(paths):
    calls, seen, unreadable, unidentified, conflicts = [], {}, 0, 0, 0
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict):
                continue
            for call in sanitized_calls(data):
                response_id = call.get('response_id')
                if response_id:
                    if response_id in seen:
                        if call != seen[response_id]:
                            conflicts += 1
                        continue
                    seen[response_id] = call
                else:
                    # Never silently collapse failed calls or claim they are unique.
                    unidentified += 1
                calls.append(call)
        except (ValueError, OSError, TypeError, AttributeError):
            unreadable += 1
    known, unknown, attempts = Decimal(0), 0, 0
    for call in calls:
        count = call.get('generation_attempts')
        if type(count) is not int or count < 0:
            call['attempt_count_unknown'] = True
            count = 0
        attempts += count
        usage = call.get('usage') or {}
        try:
            amount = Decimal(str(usage['estimated_usd']))
            if not amount.is_finite() or amount < 0:
                raise ValueError('invalid amount')
            # Reasoning is part of output, reservations are not charges.
            known += amount
        except (KeyError, ValueError, ArithmeticError):
            if count or call.get('attempt_count_unknown'):
                unknown += 1
    return {'generation_attempts_in_records': attempts,
            'known_usage_estimated_usd': str(known),
            'generation_records_with_unknown_cost': unknown,
            'records_without_response_id_not_deduplicated': unidentified,
            'unreadable_json_files': unreadable,
            'duplicate_response_id_conflicts': conflicts,
            'provider_bill_verified': False, 'is_complete_app_workflow_cost': False,
            'complete_collection_verified': False, 'calls': calls}


def discover(repo, extra_roots, output):
    # Reuse saved reports; skip dependencies, recovery copies, and arbitrary JSON.
    skip = {'.git', '.venv', 'node_modules', 'dist', '__pycache__', 'llm-handoff'}
    found = set()
    roots = [repo / 'work', repo / 'docs/test-records/llm-benchmark-20261118', *extra_roots]
    for root in roots:
        if not root.is_dir():
            continue
        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                entries = list(directory.iterdir())
            except OSError:
                continue
            for path in entries:
                if path.is_symlink() or path == output:
                    continue
                if path.is_dir() and path.name not in skip:
                    stack.append(path)
                elif path.is_file() and path.suffix.lower() == '.json':
                    try:
                        if path.stat().st_size <= 20 * 1024 * 1024:
                            found.add(path.resolve())
                    except OSError:
                        pass
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(r'C:\work\aio-llm-benchmark'))
    parser.add_argument('--reports-root', type=Path, action='append', default=[])
    args = parser.parse_args()
    repo = args.repo.resolve()
    if git(repo, 'rev-parse', '--show-toplevel') is None:
        parser.error('Existing git repository required. No files changed.')
    # Keep private raw outputs outside the git repository.
    parent = repo.parent / (repo.name + '-handoff')
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=parent))
    private, share = output / 'private', output / 'share'
    private.mkdir(); share.mkdir()
    manifest = {'recorded_at': datetime.now(timezone.utc).isoformat(),
                'cloud_baseline_commit': BASELINE_COMMIT, 'files': [],
                'prior_codex_uncommitted_changes_recovered': False}
    for command, name in [(('rev-parse', 'HEAD'), 'head'),
                          (('branch', '--show-current'), 'branch'),
                          (('status', '--short', '--branch'), 'status')]:
        value = git(repo, *command)
        manifest[name] = value.decode('utf-8', errors='replace').strip() if value is not None else None
    for name, expected in BASELINE_HASHES.items():
        path = repo / name
        row = {'path': name, 'cloud_baseline_text_sha256': expected, 'state': 'missing'}
        if path.is_file():
            for folder in (private, share):
                target = folder / 'sources' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            text = path.read_text(encoding='utf-8-sig')
            actual = hashlib.sha256(text.encode()).hexdigest()
            row.update(local_text_sha256=actual,
                       state='same' if actual == expected else 'differs_review_before_apply')
        manifest['files'].append(row)
    for ref, filename in [('HEAD', 'local-head.patch'), (BASELINE_COMMIT, 'cloud-baseline.patch')]:
        patch = git(repo, 'diff', '--binary', ref, '--', *BASELINE_HASHES)
        if patch is not None:
            (share / filename).write_bytes(patch)
        else:
            manifest[filename] = 'baseline_unavailable_no_fetch_performed'
    # Raw report backup stays private. Share inventory contains no transcription.
    reports = discover(repo, args.reports_root, output)
    backup = private / 'reports'; backup.mkdir()
    for index, path in enumerate(reports):
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(data, dict) and list(sanitized_calls(data)):
                shutil.copy2(path, backup / f'{index:05d}.json')
        except (ValueError, OSError, TypeError, AttributeError):
            pass
    write_json(private / 'report-paths.json', [str(p) for p in reports])
    write_json(share / 'measurement-inventory.json', inventory(reports))
    write_json(share / 'source-manifest.json', manifest)
    write_json(share / 'pending-review.json', {
        'source_reconciliation': 'unconfirmed', 'provider_bill': 'unconfirmed',
        'actual_masked_image_ui': 'unconfirmed', 'per_item_confirmation': 'unconfirmed',
        'silent_inference_blocked': 'unconfirmed', 'catalog_quality': 'unconfirmed'})
    archive = output / 'source-comparison.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(share.rglob('*')):
            if path.is_file():
                z.write(path, path.relative_to(share))
    print('Saved private backups (keep on this PC):', private)
    print('Source comparison and sanitized usage (attach this):', archive)
    print('No API calls, no key input, no source modifications. Unknown reviews remain unconfirmed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
