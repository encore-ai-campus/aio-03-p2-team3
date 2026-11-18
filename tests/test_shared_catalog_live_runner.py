"""실제 API/키 없이 PC 선별 실행기의 재사용·중단·미상 비용 처리를 검증한다."""
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
# 실제 SKU가 든 기록 폴더는 공개 레포에 없다. 개인 PC에서만(CATALOG_RECORDS_DIR 또는 기본 경로) 돈다.
RECORDS = Path(os.environ.get('CATALOG_RECORDS_DIR') or ROOT / 'docs/test-records/llm-benchmark-20261118')
if not all((RECORDS / name).exists() for name in
           ('catalog-query-confirmed.json', 'shared-catalog-snapshot.json', 'catalog-ground-truth-approval.json')):
    pytest.skip('공유 카탈로그 기록 폴더 없음(CATALOG_RECORDS_DIR)', allow_module_level=True)
spec = importlib.util.spec_from_file_location('run_live', ROOT / 'scripts/run_shared_catalog_live.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

QUERIES = json.loads((RECORDS / 'catalog-query-confirmed.json').read_text(encoding='utf-8'))
EXPECTED = {q['query']: q['expected_ids'] for q in QUERIES['queries']}


class FakeClient:
    """질의 문장으로 정답 ID를 돌려주는 가짜 클라이언트. events로 호출 순서를 남긴다."""

    def __init__(self, behavior=None, count=3000):
        self.behavior = behavior or {}
        self.creates = []
        self.closed = False
        self.count = count
        self.responses = SimpleNamespace(input_tokens=SimpleNamespace(count=self._count), create=self._create)

    def _count(self, **request):
        return SimpleNamespace(input_tokens=self.count)

    def _create(self, **request):
        index = len(self.creates)
        self.creates.append(request)
        action = self.behavior.get(index)
        if isinstance(action, Exception):
            raise action
        query = json.loads(request['input'])['query']
        output = json.dumps({'candidates': EXPECTED[query]})
        usage = None if action == 'no-usage' else {
            'input_tokens': 3000, 'input_tokens_details': {'cached_tokens': 0},
            'output_tokens': 200, 'output_tokens_details': {'reasoning_tokens': 80}}
        return SimpleNamespace(status='completed', id=f'fake-{index}', model=request['model'],
                               output_text=output, usage=usage)

    def close(self):
        self.closed = True


def argv(tmp_path, *extra, live=True):
    return ['--repo', str(ROOT), '--snapshot', str(RECORDS / 'shared-catalog-snapshot.json'),
            '--queries', str(RECORDS / 'catalog-query-confirmed.json'),
            '--approval', str(RECORDS / 'catalog-ground-truth-approval.json'),
            '--out-dir', str(tmp_path / 'results'), *(['--live'] if live else []), *extra]


def secret(value='fake-test-key-never-saved'):
    return lambda prompt: value


def state_of(tmp_path):
    return json.loads((tmp_path / 'results' / runner.STATE_NAME).read_text(encoding='utf-8'))


def test_dry_plan_needs_no_key_or_client_and_writes_nothing(tmp_path, capsys):
    def fail(*_):
        pytest.fail('dry plan must not ask for a key or build a client')
    assert runner.main(argv(tmp_path, live=False), ask=fail, ask_secret=fail, client_factory=fail) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['mode'] == 'dry_plan' and out['planned_calls'] == 20
    assert out['pending_calls'] == 20 and out['generation_attempts'] == 0
    assert not (tmp_path / 'results').exists()


def test_tampered_queries_are_rejected_before_any_key_prompt(tmp_path):
    bad = json.loads(json.dumps(QUERIES))
    bad['queries'][0]['expected_ids'] = ['AIO3-FAKE000000000000']
    path = tmp_path / 'tampered.json'
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')
    args = argv(tmp_path)
    args[args.index('--queries') + 1] = str(path)
    with pytest.raises(SystemExit):
        runner.main(args, ask_secret=lambda *_: pytest.fail('no key before verification'))


def test_model_input_has_no_prices_aliases_or_expected_answers():
    snapshot = json.loads((RECORDS / 'shared-catalog-snapshot.json').read_text(encoding='utf-8'))
    cases, metadata = runner.load_prepare().prepare(snapshot, QUERIES['queries'])
    assert len(cases) == 10 and metadata['no_prices_or_aliases'] is True
    for case in cases:
        text = case['request']['input'] + case['request']['instructions']
        assert 'expected' not in text and 'review_status' not in text
        assert 'unit_price' not in text and 'alias' not in text.lower()
        assert json.loads(case['request']['input'])['catalog'][0]['id'].startswith('AIO3-')


def test_full_live_runs_20_calls_then_reuses_every_result(tmp_path, capsys):
    client = FakeClient()
    code = runner.main(argv(tmp_path), ask=lambda *_: 'yes', ask_secret=secret(),
                       client_factory=lambda key: client)
    assert code == 0 and client.closed and len(client.creates) == 20
    models = [r['model'] for r in client.creates]
    assert models == ['gpt-6-luna'] * 10 + ['gpt-6.1-sol'] * 10
    assert all(r['reasoning'] == {'effort': 'medium'} and r['max_output_tokens'] == 2048 and
               r['store'] is False for r in client.creates)
    state = state_of(tmp_path)
    assert len(state['calls']) == 20 and state['unknown_cost_calls'] == 0
    assert Decimal(state['known_estimated_usd']) > 0
    assert 'fake-test-key-never-saved' not in json.dumps(state) + capsys.readouterr().out
    assert all(row['quality']['passed'] is True and row['parsed_output'] for row in state['calls'])
    again = FakeClient()
    code = runner.main(argv(tmp_path), ask=lambda *_: 'yes', ask_secret=secret('x'),
                       client_factory=lambda key: again)
    assert code == 0 and again.creates == []          # 같은 결과를 다시 과금하지 않는다
    assert len(state_of(tmp_path)['calls']) == 20


def test_cancelled_key_or_unconfirmed_start_makes_no_call_and_keeps_progress(tmp_path):
    client = FakeClient()
    assert runner.main(argv(tmp_path, '--models', 'gpt-6-luna'), ask=lambda *_: 'yes',
                       ask_secret=secret(), client_factory=lambda key: client) == 0
    before = state_of(tmp_path)['calls']
    never = lambda key: pytest.fail('client must not be created without a key')   # noqa: E731
    assert runner.main(argv(tmp_path), ask_secret=secret(''), client_factory=never) == 2
    asked = FakeClient()
    assert runner.main(argv(tmp_path), ask=lambda *_: '모름', ask_secret=secret(),
                       client_factory=lambda key: asked) == 2
    assert asked.creates == []
    after = state_of(tmp_path)
    assert after['calls'] == before                      # 초기화/삭제 없음
    assert [e['event'] for e in after['events']][-2:] == ['key_not_provided', 'start_not_confirmed']


def test_timeout_keeps_reservation_blocks_next_calls_and_never_calls_other_model(tmp_path):
    client = FakeClient(behavior={2: TimeoutError('private input and key')})
    code = runner.main(argv(tmp_path), ask=lambda *_: 'yes', ask_secret=secret(),
                       client_factory=lambda key: client)
    assert code == 1 and len(client.creates) == 3
    assert {r['model'] for r in client.creates} == {'gpt-6-luna'}   # Sol 자동 호출 없음
    state = state_of(tmp_path)
    assert state['stopped'] == 'unknown_usage_or_budget_exceeded'
    assert state['unknown_cost_calls'] == 1 and Decimal(state['unknown_reserved_usd']) > 0
    assert 'private input and key' not in json.dumps(state)
    blocked = FakeClient()
    assert runner.main(argv(tmp_path), ask=lambda *_: 'yes', ask_secret=secret(),
                       client_factory=lambda key: blocked) == 3
    assert blocked.creates == []


def test_rerun_after_unknown_is_explicit_and_preserves_old_reservation(tmp_path):
    runner.main(argv(tmp_path, '--models', 'gpt-6-luna'), ask=lambda *_: 'yes', ask_secret=secret(),
                client_factory=lambda key: FakeClient(behavior={0: TimeoutError()}))
    reserved = Decimal(state_of(tmp_path)['unknown_reserved_usd'])
    client = FakeClient()
    code = runner.main(argv(tmp_path, '--models', 'gpt-6-luna', '--allow-rerun-unknown'),
                       ask=lambda *_: 'yes', ask_secret=secret(), client_factory=lambda key: client)
    state = state_of(tmp_path)
    assert code == 0 and len(client.creates) == 10
    assert Decimal(state['unknown_reserved_usd']) == reserved        # 0으로 지우지 않는다
    assert sum(1 for row in state['calls'] if row.get('superseded_by_rerun')) == 1


def test_batch_worst_case_over_budget_stops_before_any_generation(tmp_path):
    client = FakeClient()
    code = runner.main(argv(tmp_path, '--budget-usd', '0.05'), ask=lambda *_: 'yes',
                       ask_secret=secret(), client_factory=lambda key: client)
    assert code == 3 and client.creates == []
    assert state_of(tmp_path)['events'][-1]['event'] == 'batch_worst_case_exceeds_budget'


def test_missing_usage_is_unknown_not_zero_and_stops(tmp_path):
    client = FakeClient(behavior={0: 'no-usage'})
    code = runner.main(argv(tmp_path), ask=lambda *_: 'yes', ask_secret=secret(),
                       client_factory=lambda key: client)
    state = state_of(tmp_path)
    assert code == 1 and len(client.creates) == 1
    assert state['calls'][0]['status'] == 'usage_unknown'
    assert state['unknown_cost_calls'] == 1 and Decimal(state['unknown_reserved_usd']) > 0


def test_preflight_failure_records_only_type_status_and_target_never_key_or_body(tmp_path, capsys):
    class Denied(Exception):
        status_code = 401

    client = FakeClient()

    def deny(**request):
        raise Denied('Incorrect API key provided: fake-test-key-never-saved')

    client.responses.input_tokens.count = deny
    code = runner.main(argv(tmp_path), ask=lambda *_: 'yes', ask_secret=secret(),
                       client_factory=lambda key: client)
    state = state_of(tmp_path)
    event = state['events'][-1]['event']
    assert code == 3 and client.creates == []
    assert event.startswith('batch_preflight_failed:Denied:status=401:gpt-6-luna:mixed-pink')
    assert 'fake-test-key-never-saved' not in json.dumps(state) + capsys.readouterr().out


def test_masked_input_shows_stars_supports_backspace_and_cancel():
    def feed(text):
        it = iter(text)
        return lambda: next(it)

    shown = []
    value = runner.masked_input('p: ', reader=feed('abXc\x08\x08d\r'), write=shown.append)
    assert value == 'abd' and 'abd' not in ''.join(shown) and ''.join(shown).count('*') == 5
    assert runner.masked_input('p: ', reader=feed('ab\x1b'), write=lambda text: None) == ''
    assert runner.masked_input('p: ', reader=feed('\r'), write=lambda text: None) == ''


def test_key_length_is_reported_without_the_key(tmp_path, capsys):
    runner.main(argv(tmp_path, '--models', 'gpt-6-luna'), ask=lambda *_: 'no',
                ask_secret=secret('abcde'), client_factory=lambda key: FakeClient())
    out = capsys.readouterr().out
    assert '키 5자 입력됨' in out and 'abcde' not in out


def test_default_key_input_is_a_window_with_terminal_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, 'window_input', lambda prompt: calls.append('window') or 'k')
    assert runner.read_secret('p', 'window') == 'k' and calls == ['window']

    def broken(prompt):
        raise RuntimeError('no display')
    monkeypatch.setattr(runner, 'window_input', broken)
    monkeypatch.setattr(runner, 'masked_input', lambda prompt: 'from-terminal')
    assert runner.read_secret('p', 'window') == 'from-terminal'
    assert runner.read_secret('p', 'terminal') == 'from-terminal'
