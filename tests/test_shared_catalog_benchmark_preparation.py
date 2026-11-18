"""No model/API/DB calls: preserve shared SKU scope and price-free source facts."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('prepare_shared',
    Path(__file__).parents[1] / 'scripts/prepare_shared_catalog_cases.py')
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


def snapshot():
    return {'member_check_passed': True, 'status': 'snapshot_collected_queries_unconfirmed',
            'product_count': 1, 'catalog_snapshot_sha256': 'received-source-fingerprint',
            'products': [{'id': 'actual-fixture-sku', 'item_name': 'Mouse White',
                          'brand': 'Example', 'color': 'White', 'switch_type': None,
                          'category': 'mouse', 'unit': 'pcs', 'capacity': 'White'}]}


def queries():
    return [{'id': 'mixed', 'query': '마우스 white', 'expected_ids': ['actual-fixture-sku'],
             'review_status': 'unconfirmed'}]


def test_catalog_facts_reach_model_without_expected_answers_or_alias_dictionary():
    cases, metadata = preparation.prepare(snapshot(), queries())
    payload = json.loads(cases[0]['request']['input'])
    assert payload['catalog'][0]['id'] == 'actual-fixture-sku'
    assert payload['catalog'][0]['brand'] == 'Example'
    assert payload['catalog'][0]['color'] == 'White'
    assert payload['catalog'][0]['item_name'] == 'Mouse White'
    assert 'expected_ids' not in payload and 'review_status' not in payload
    assert metadata['human_ground_truth_confirmed'] is False
    assert metadata['application_authenticated_owner_verified'] is False
    assert metadata['server_id_owner_version_revalidation_verified'] is False


@pytest.mark.parametrize('field,value', [('member_check_passed', False), ('product_count', 2)])
def test_unconfirmed_scope_or_inconsistent_snapshot_is_rejected(field, value):
    data = snapshot(); data[field] = value
    with pytest.raises(ValueError):
        preparation.prepare(data, queries())


@pytest.mark.parametrize('field', ['unit_price', 'aliases'])
def test_aliases_and_prices_cannot_be_accidentally_added_to_model_input(field):
    data = snapshot(); data['products'][0][field] = 'must-not-send'
    with pytest.raises(ValueError):
        preparation.prepare(data, queries())


def test_nonexistent_expected_id_is_rejected_before_any_measurement():
    query = queries(); query[0]['expected_ids'] = ['invented-sku']
    with pytest.raises(ValueError):
        preparation.prepare(snapshot(), query)


def test_prepared_fingerprint_tracks_actual_fact_changes_separately_from_source_fingerprint():
    original = snapshot()
    changed = deepcopy(original); changed['products'][0]['color'] = 'Black'
    _, before = preparation.prepare(original, queries())
    _, after = preparation.prepare(changed, queries())
    assert before['prepared_products_sha256'] != after['prepared_products_sha256']
    assert before['source_snapshot_sha256'] == after['source_snapshot_sha256']
