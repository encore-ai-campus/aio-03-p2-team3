"""Offline review of saved reports. Does not call APIs, read keys, or edit sources.

Replays only the known synthetic trade with saved parsed output. Real inputs and
missing output remain unconfirmed. Keeps private inputs outside the repository.
"""
import argparse
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import zipfile

from collect_llm_handoff import discover, inventory, write_json


def safe_quality(value):
    if not isinstance(value, dict):
        return None
    result = {key: value[key] for key in ('passed', 'manual_review_required',
              'model_declared_complete', 'uncertain_count', 'source_conflict_count') if key in value}
    result['checks'] = [{'field': row.get('field'), 'passed': row.get('passed')}
                        for row in value.get('checks', []) if isinstance(row, dict)]
    return result


def review_call(call, case, grade, schema_name, expected_hash):
    row = {key: call.get(key) for key in ('response_id', 'case_id', 'kind', 'model', 'effort', 'status')}
    row['original_quality'] = safe_quality(call.get('quality'))
    row['original_automatic_failure_preserved'] = True
    row['saved_parsed_output_available'] = isinstance(call.get('parsed_output'), dict)
    row['replay'] = 'unconfirmed_missing_saved_output'
    if call.get('kind') != 'trade':
        row['replay'] = 'human_source_comparison_still_required'
    elif call.get('input_sha256') != expected_hash:
        row['replay'] = 'unconfirmed_custom_or_changed_input'
    elif row['saved_parsed_output_available']:
        parsed = deepcopy(call['parsed_output'])
        response = SimpleNamespace(output=[SimpleNamespace(type='function_call', name=schema_name,
                                                           arguments=json.dumps(parsed))])
        try:
            quality, _ = grade(deepcopy(case), response)
            row['replayed_quality'] = safe_quality(quality)
            row['replay'] = 'saved_parsed_result_rechecked_not_original_wire_response'
            # parsed_output already contains source conflicts; replay can append them again.
            row['conflict_count_may_include_replayed_duplicates'] = True
        except Exception as error:
            row['replay'] = 'saved_parsed_result_invalid'
            row['replay_error_type'] = type(error).__name__
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--reports-root', type=Path, action='append', default=[])
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo / 'app/evaluation/model_benchmark.py').is_file():
        parser.error('Existing benchmark source is required; nothing replaced.')
    sys.path.insert(0, str(repo))
    from app.evaluation.model_benchmark import cases, grade, run, wire_schema, PIExtraction
    parent = repo.parent / (repo.name + '-offline-review')
    parent.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=parent))
    private = out / 'private'; private.mkdir()
    paths = discover(repo, args.reports_root, out)
    chosen, no_id = {}, []
    catalogs, unreadable = [], 0
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict):
                continue
            if isinstance(data.get('products'), list) and isinstance(data.get('queries'), list):
                try:
                    selected = [c for c in cases(catalog_input=data) if c['kind'] == 'catalog']
                    if selected:
                        catalogs.append((path, selected))
                except Exception:
                    pass
            for report in data.get('reports', [data]):
                if report.get('mode') != 'live':
                    continue
                for call in report.get('calls', []):
                    rid = call.get('response_id')
                    if not rid:
                        no_id.append(call)
                        continue
                    old = chosen.get(rid)
                    # Prefer saved output and diagnostic checks over sanitized inventories.
                    score = lambda x: (isinstance(x.get('parsed_output'), dict),
                                       bool((x.get('quality') or {}).get('checks')))
                    if old is None or score(call) > score(old):
                        chosen[rid] = call
        except (ValueError, OSError, TypeError, AttributeError):
            unreadable += 1
    case = cases()[0]
    digest = sha256(json.dumps(case['request'], sort_keys=True).encode()).hexdigest()
    rows = [review_call(call, case, grade, wire_schema(PIExtraction).__name__, digest)
            for call in [*chosen.values(), *no_id]]
    catalog_rows = []
    for index, (path, selected) in enumerate(catalogs):
        # Dry plan only, no client is constructed. Actual ownership cannot be proven by a file.
        dry = run(selected, ['gpt-6-luna', 'gpt-6.1-sol'], ['medium'])
        write_json(private / f'catalog-{index:03d}-dry.json', dry)
        catalog_rows.append({'index': index, 'queries': len(selected),
                             'status': 'dry_plan_only_ownership_and_live_quality_unconfirmed'})
    write_json(private / 'catalog-locations.json', [str(path) for path, _ in catalogs])
    summary = {'mode': 'offline', 'api_calls': 0, 'source_files_modified': False,
               'usage_inventory': inventory(paths), 'reviews': rows,
               'catalogs': catalog_rows, 'unreadable_json_files': unreadable,
               'overall_model_setting_approved': False,
               'provider_bill': 'unconfirmed', 'actual_masked_image_ui': 'unconfirmed',
               'per_item_confirmation': 'unconfirmed', 'silent_inference_blocked': 'unconfirmed',
               'missing_inputs_are_not_reprompted': True}
    result = out / 'offline-review.json'; write_json(result, summary)
    archive = out / 'offline-review.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        z.write(result, result.name)
    print('API calls: 0. Existing files preserved. Attach:', archive)
    print('Saved parsed outputs:', sum(r['saved_parsed_output_available'] for r in rows))
    print('Catalog files ready for dry plans:', len(catalogs))
    print('Unavailable outputs, unconfirmed content and reviews remain unconfirmed; no restart required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
