"""Prepare dry benchmark cases from a member-scoped shared catalog snapshot.

Reuses the existing benchmark case/schema/budget/report machinery. No API client,
keys, database writes, production configuration or alias dictionary are used.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys


CATALOG_FIELDS = ('id', 'item_name', 'brand', 'source_code', 'capacity',
                  'category', 'color', 'switch_type', 'unit')


def prepare(snapshot, queries):
    from app.evaluation.model_benchmark import cases
    if snapshot.get('member_check_passed') is not True:
        raise ValueError('Shared catalog membership is unconfirmed')
    if snapshot.get('status') != 'snapshot_collected_queries_unconfirmed':
        raise ValueError('Snapshot is not ready for query preparation')
    products = snapshot['products']
    if len(products) != snapshot.get('product_count'):
        raise ValueError('Snapshot product count mismatch')
    if any('aliases' in row or 'unit_price' in row for row in products):
        raise ValueError('Prices or aliases must not be included')
    safe_products = [{key: row.get(key) for key in CATALOG_FIELDS} for row in products]
    dataset = {'products': safe_products, 'queries': queries}
    selected = [case for case in cases(catalog_input=dataset) if case['kind'] == 'catalog']
    if not selected or len({case['id'] for case in selected}) != len(selected):
        raise ValueError('Unique nonempty query IDs required')
    allowed = {row['id'] for row in safe_products}
    for query in queries:
        expected = query['expected_ids']
        if len(expected) != len(set(expected)) or len(expected) > 20 or not set(expected) <= allowed:
            raise ValueError('Expected IDs must be unique real snapshot IDs')
    for case in selected:
        payload = json.loads(case['request']['input'])
        # Existing case preparation strips metadata. Retain source attributes so
        # the model receives brand/color/switch facts without prices or aliases.
        payload['catalog'] = safe_products
        case['request']['input'] = json.dumps(payload, ensure_ascii=False)
    metadata = {'source_project_ref': snapshot.get('source_project_ref'),
                'source_table': snapshot.get('source_table'),
                'source_snapshot_sha256': snapshot.get('catalog_snapshot_sha256'),
                'prepared_products_sha256': sha256(json.dumps(safe_products, sort_keys=True,
                    ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(),
                'scope': 'shared_reader_membership',
                'application_authenticated_owner_verified': False,
                'server_id_owner_version_revalidation_verified': False,
                'human_ground_truth_confirmed': all(q.get('review_status') == 'confirmed' for q in queries),
                'no_prices_or_aliases': True}
    return selected, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--queries', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new output path; previous reports are preserved')
    sys.path.insert(0, str(args.repo.resolve()))
    from app.evaluation.model_benchmark import run
    snapshot = json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    queries = json.loads(args.queries.read_text(encoding='utf-8-sig'))['queries']
    selected, metadata = prepare(snapshot, queries)
    report = run(selected, ['gpt-6-luna', 'gpt-6.1-sol'], ['medium'], timeout=90,
                 max_output_tokens=2048)
    report['shared_catalog_preparation'] = metadata
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'mode': 'dry_run', 'planned_calls': len(report['calls']),
                      'generation_attempts': 0, 'human_ground_truth_confirmed':
                      metadata['human_ground_truth_confirmed']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
