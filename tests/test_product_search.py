"""첨부 시연 데이터의 품목 구조로 검색→명시적 선택→기존 가격 검증을 확인한다."""
from copy import deepcopy

import pytest

from app.auth.deps import current_user_id
from app.trade.common.product_search import search_products
from tests.test_pi_api import pi_client  # noqa: F401
from tests.test_pi_domain import pi_input


DEMO_NAMES = [f'LOGITECH PRO X SUPERLIGHT2{variant} {color}'
              for variant in ('', ' Compact') for color in ('Black', 'Pink', 'White')]
DEMO_NAMES += ['LOGITECH PRO X 60 - Tactile - Black', 'LOGITECH Pro X HS WL 2 White',
               'LOGITECH G PRO X TKL RAPID(BK)']
PRODUCTS = [dict(id=i, item_name=name, source_code=None, capacity=None)
            for i, name in enumerate(DEMO_NAMES, 1)]


@pytest.mark.parametrize('query', ['슈퍼라이트', '수퍼라이트', 'superlight', 'superligt',
                                  'superligt 2', 'SUPERLIGHT2', '슈퍼라이트 2', '슈퍼 라이트'])
def test_demo_short_names_korean_and_typos_return_all_six(query):
    original = deepcopy(PRODUCTS)
    result = search_products(query, PRODUCTS)
    assert {row['product']['item_name'] for row in result} == set(DEMO_NAMES[:6])
    assert all('Compact' not in row['product']['item_name'] for row in result[:3])
    assert PRODUCTS == original


@pytest.mark.parametrize('query, count', [('슈퍼라이트 블랙', 2), ('superligt 2 compact pink', 1),
                                        ('로지텍 슈퍼라이트2 화이트', 2), ('superlight 3', 0),
                                        ('unrelated', 0), ('', 0), ('x', 0)])
def test_variant_constraints_and_unrelated_queries(query, count):
    assert len(search_products(query, PRODUCTS)) == count


def test_search_deduplicates_catalog_price_rows():
    assert len(search_products('superlight', PRODUCTS + PRODUCTS)) == 6


def seed_demo(client):
    for name in DEMO_NAMES:
        response = client.put('/api/trade/settings/prices', json={
            'item_name': name, 'role': 'sale', 'currency': 'USD', 'unit': 'PCS',
            'unit_price': '160' if 'Compact' in name else '140', 'price_basis': 'PCS'})
        assert response.status_code == 200, response.text


def test_owned_candidates_never_apply_a_price_until_selected_and_revalidated(pi_client):
    client = pi_client
    seed_demo(client)
    path = '/api/trade/settings/products/search'
    response = client.get(path, params={'q': '슈퍼라이트', 'role': 'sale'})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.json()['total'] == 6
    assert all('unit_price' not in row['product'] for row in response.json()['candidates'])
    assert client.get(path, params={'q': '슈퍼라이트', 'role': 'purchase'}).json()['total'] == 0
    assert client.get(path, params={'q': 'x' * 201}).status_code == 422
    client.app.dependency_overrides[current_user_id] = lambda: 2
    assert client.get(path, params={'q': 'superlight'}).json()['candidates'] == []
    client.app.dependency_overrides.pop(current_user_id)
    assert client.get(path, params={'q': 'superlight'}).status_code == 401
    client.app.dependency_overrides[current_user_id] = lambda: 1

    values = pi_input(product_family='other').model_dump(mode='json')
    values['items'][0].update(product_name='superligt 2', capacity=None)
    created = client.post('/api/trade/pi', json=values).json()
    assert created['status'] == 'needs_input'
    assert created['document']['items'][0].get('unit_price') is None
    chosen = response.json()['candidates'][0]['product']
    values['items'][0].update(product_name=chosen['item_name'], product_code=chosen['source_code'],
                              capacity=chosen['capacity'])
    saved = client.put(f"/api/trade/pi/{created['document_id']}", json={
        'revision': created['revision'], 'document': values})
    assert saved.status_code == 200, saved.text
    assert saved.json()['status'] == 'ready', saved.text
    assert saved.json()['document']['items'][0]['quantity'] == '10'
    assert saved.json()['document']['items'][0]['unit_price'] == '140'
    assert saved.json()['document']['total'] == '1400.00'
