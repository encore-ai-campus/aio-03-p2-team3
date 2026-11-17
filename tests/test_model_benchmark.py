"""실제 API/키 없이 토큰 계수·과금·예산 중단·후보 ID 제한을 검증한다."""
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from app.evaluation.model_benchmark import cases, cost_usd, grade, main, measured_usage, run


def response(*, usage=True, status='completed', output='{"candidates": ["monitor-white"]}'):
    return SimpleNamespace(status=status, id='fake-response', model='gpt-6-luna', output_text=output,
        usage={'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 200},
               'output_tokens': 300, 'output_tokens_details': {'reasoning_tokens': 120}} if usage else None)


class Client:
    def __init__(self, replies=None, count=1000):
        self.replies = iter(replies or [response()])
        self.requests = []
        self.count = count
        self.responses = SimpleNamespace(input_tokens=SimpleNamespace(count=self.count_input), create=self.create)

    def count_input(self, **request):
        return SimpleNamespace(input_tokens=self.count)

    def create(self, **request):
        self.requests.append(request)
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        return value


def catalog_case():
    return [case for case in cases() if case['id'] == 'catalog-mixed']


def test_cost_counts_cached_input_and_reasoning_only_once():
    usage = measured_usage(response(), 'gpt-6-luna')
    assert usage['reasoning_tokens'] == 120
    assert usage['output_tokens'] == 300
    assert Decimal(usage['estimated_usd']) == Decimal('0.000232')
    assert cost_usd('gpt-6.1-sol', 8000, 0, 3000) == Decimal('0.046')


@pytest.mark.parametrize('values', [(10, 11, 1), (-1, 0, 1), (True, 0, 1), (272001, 0, 1), (1, 0, None)])
def test_invalid_usage_is_not_reported_as_zero_cost(values):
    with pytest.raises(ValueError):
        cost_usd('gpt-6-luna', *values)


def test_dry_run_requires_no_key_and_does_not_construct_client(tmp_path, monkeypatch, capsys):
    import openai
    monkeypatch.setattr(openai, 'OpenAI', lambda **kw: pytest.fail('API client must not be created'))
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-key-must-never-appear')
    out = tmp_path / 'dry.json'
    assert main(['--out', str(out)]) == 0
    report = json.loads(out.read_text())
    assert report['mode'] == 'dry_run' and len(report['calls']) == 4
    assert report['budget_accounted_usd'] == '0'
    assert all(row['generation_attempts'] == 0 for row in report['calls'])
    assert 'fake-key-must-never-appear' not in out.read_text() + capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(['--out', str(out)])  # 백업 결과를 덮어쓰지 않는다.


def test_live_uses_preflight_reservation_and_provider_usage():
    client = Client()
    report = run(catalog_case(), ['gpt-6-luna'], ['medium'], client=client, max_output_tokens=8192)
    row = report['calls'][0]
    assert row['quality']['passed'] is True and row['status'] == 'completed'
    assert report['budget_accounted_usd'] == '0.000232'
    assert len(client.requests) == 1
    assert client.requests[0]['reasoning'] == {'effort': 'medium'}
    assert client.requests[0]['store'] is False
    assert 'parsed_output' not in row


def test_budget_stops_before_generation():
    client = Client()
    report = run(catalog_case(), ['gpt-6.1-sol'], ['high'], client=client, budget=Decimal('0.001'))
    assert report['stopped'] == 'budget_reservation_exceeded'
    assert client.requests == []


@pytest.mark.parametrize('reply', [TimeoutError('private input and key'), response(usage=False)])
def test_unknown_usage_retains_reservation_and_stops_without_retry(reply):
    client = Client([reply])
    report = run(catalog_case() * 2, ['gpt-6-luna'], ['medium'], client=client)
    assert len(client.requests) == 1
    assert len(report['calls']) == 1
    assert Decimal(report['budget_accounted_usd']) > 0
    assert report['stopped'] == 'unknown_usage_or_budget_exceeded'
    assert 'private input and key' not in json.dumps(report)


def test_invalid_model_output_is_measured_and_graded_as_failure():
    report = run(catalog_case(), ['gpt-6-luna'], ['medium'], client=Client([
        response(output='{"candidates": ["invented-sku"]}')]))
    assert report['calls'][0]['status'] == 'invalid_output'
    assert report['calls'][0]['usage']['output_tokens'] == 300


@pytest.mark.parametrize('count', [None, 60001, True])
def test_bad_preflight_stops_without_generation(count):
    client = Client(count=count)
    report = run(catalog_case(), ['gpt-6-luna'], ['medium'], client=client)
    assert report['stopped'] == 'preflight_failed_no_generation'
    assert not client.requests


def test_incomplete_output_keeps_charged_usage():
    report = run(catalog_case(), ['gpt-6-luna'], ['medium'], client=Client([response(status='incomplete')]))
    assert report['calls'][0]['status'] == 'incomplete'
    assert report['budget_accounted_usd'] == '0.000232'


def test_no_match_is_a_valid_catalog_answer_and_not_a_hallucinated_id():
    case = next(case for case in cases() if case['id'] == 'catalog-unknown')
    quality, _ = grade(case, response(output='{"candidates": []}'))
    assert quality['passed'] is True


def test_vision_complete_is_not_accepted_as_ground_truth():
    quality, _ = grade({'kind': 'vision'}, response(output=json.dumps({
        'text': 'text that needs visual checking', 'blank': False, 'complete': True, 'uncertain': []})))
    assert quality['passed'] is None and quality['manual_review_required'] is True


def test_unsupported_effort_and_missing_image_are_rejected_before_network(tmp_path):
    for args in (['--models', 'gpt-6.1-sol', '--efforts', 'none'], ['--cases', 'vision']):
        with pytest.raises(SystemExit):
            main([*args, '--out', str(tmp_path / 'not-created.json')])


def test_custom_catalog_supports_other_products_and_strips_prices():
    inputs = {'products': [{'id': 'cream', 'item_name': 'Hydrating Gel Cream', 'price': 'secret-price'}],
              'queries': [{'id': 'cream-ko', 'query': '하이드레이팅 젤크림', 'expected_ids': ['cream']}]}
    case = next(case for case in cases(catalog_input=inputs) if case['kind'] == 'catalog')
    assert 'secret-price' not in case['request']['input']
    quality, _ = grade(case, response(output='{"candidates": ["cream"]}'))
    assert quality['passed'] is True
    with pytest.raises(ValueError):
        grade(case, response(output='{"candidates": ["monitor-white"]}'))


def test_image_input_uses_real_page_and_requires_manual_review(tmp_path):
    from PIL import Image
    image = tmp_path / 'page.png'
    Image.new('RGB', (40, 40), 'white').save(image)
    case = next(case for case in cases(image) if case['kind'] == 'vision')
    assert case['request']['input'][0]['content'][1]['detail'] == 'high'
    assert case['request']['input'][0]['content'][1]['image_url'].startswith('data:image/png;base64,')


def test_installed_sdk_serializes_preflight_and_generation_with_mock_transport():
    import httpx
    from openai import OpenAI
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': 1000, 'object': 'response.input_tokens'})
        return httpx.Response(200, json={
            'id': 'resp_fake', 'object': 'response', 'created_at': 0, 'status': 'completed',
            'model': 'gpt-6-luna', 'error': None, 'incomplete_details': None,
            'output': [{'id': 'msg_fake', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': '{"candidates":["monitor-white"]}',
                                     'annotations': []}]}], 'usage': response().usage})

    with OpenAI(api_key='fake-local-only', base_url='https://openai.invalid/v1', max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        report = run(catalog_case(), ['gpt-6-luna'], ['medium'], client=client)
    assert report['calls'][0]['quality']['passed'] is True
    assert report['calls'][0]['usage']['reasoning_tokens'] == 120
    assert len(requests) == 2
    assert requests[0][0] == '/v1/responses/input_tokens'
    assert requests[1][1]['max_output_tokens'] == 8192
    assert requests[1][1]['service_tier'] == 'default'


def test_correct_trade_fixture_passes_actual_input_schema_and_quote_validation():
    from app.evaluation.model_benchmark import TRADE_TEXT, wire_schema, PIExtraction
    items = []
    for color, paid, free, discount in [('Black', '10', '2', '5'), ('Pink', '3', '0', '0')]:
        start = TRADE_TEXT.index('LOGITECH PRO X SUPERLIGHT2 ' + color + ':')
        stop = TRADE_TEXT.index('%.', start) + 2
        items.append({'product_name': 'LOGITECH PRO X SUPERLIGHT2 ' + color, 'quantity': paid,
                      'paid_quantity': paid, 'free_quantity': free, 'discount_percent': discount,
                      'unit_price': '140', 'unit': 'PCS', 'price_basis': 'PCS', 'source': TRADE_TEXT[start:stop]})
    result = response()
    result.output = [SimpleNamespace(type='function_call', name=wire_schema(PIExtraction).__name__,
                                     arguments=json.dumps({'items': items}))]
    quality, _ = grade(cases()[0], result)
    assert quality['passed'] is True
