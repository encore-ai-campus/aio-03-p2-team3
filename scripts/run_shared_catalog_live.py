"""개인 PC 전용 최소 선별 실행기: 확인된 공유 카탈로그 10질의 x Luna/Sol medium.

기존 `model_benchmark.run`(사전 토큰 계수·예산 예약·usage/추론 집계·미상 중단)과
`prepare_shared_catalog_cases.prepare`(가격/별칭 없는 모델 입력)를 그대로 재사용한다.
기본은 API 미호출 계획 출력이고 `--live`일 때만 호출한다. 키는 환경변수/파일/인자로 받지
않고 실행 중 비공개 입력창에서만 받는다. 이 선별은 앱 전체 품질 게이트가 아니다.
"""
import argparse
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from getpass import getpass
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

MODELS = ('gpt-6-luna', 'gpt-6.1-sol')
EFFORT = 'medium'
KNOWN = {'completed', 'incomplete', 'invalid_output'}      # 생성했고 usage를 받음
UNKNOWN = {'in_flight', 'usage_unknown', 'provider_error_usage_unknown'}  # 비용 미상
STATE_NAME = 'shared-catalog-live-state.json'
STATE_TYPE = 'shared_catalog_minimum_live_screening_state'


def load_prepare():
    path = Path(__file__).with_name('prepare_shared_catalog_cases.py')
    spec = importlib.util.spec_from_file_location('prepare_shared_catalog_cases', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def verify_inputs(snapshot, queries_doc, approval):
    """사람 확인 정답과 받은 카탈로그가 승인 기록과 같은 것인지 확인한다."""
    queries = queries_doc['queries']
    problems = []
    if queries_doc.get('human_ground_truth_confirmed') is not True or any(
            q.get('review_status') != 'confirmed' for q in queries):
        problems.append('확인본 질의가 모두 confirmed가 아닙니다')
    if approval.get('document_type') != 'human_catalog_ground_truth_confirmation':
        problems.append('승인 기록 형식이 다릅니다')
    if approval.get('confirmed_queries_sha256') != digest(queries):
        problems.append('질의 해시가 승인 기록과 다릅니다')
    if sorted(approval.get('confirmed_query_ids', [])) != sorted(q['id'] for q in queries):
        problems.append('질의 ID가 승인 기록과 다릅니다')
    if approval.get('received_catalog_snapshot_sha256') != snapshot.get('catalog_snapshot_sha256'):
        problems.append('카탈로그 해시가 승인 기록과 다릅니다')
    if approval.get('query_count') != len(queries) or approval.get('product_count') != len(
            snapshot.get('products', [])):
        problems.append('질의/상품 수가 승인 기록과 다릅니다')
    return problems


def row_key(row):
    return (row['case_id'], row['model'], row['effort'], row['repeat'], row['input_sha256'])


def row_cost(row):
    """(알려진 추계, 미상 예약액) — 미상은 0으로 처리하지 않고 예약액을 유지한다."""
    status = row.get('status')
    if status in KNOWN and row.get('usage'):
        return Decimal(row['usage']['estimated_usd']), None
    if status in KNOWN or status in UNKNOWN:
        reserved = row.get('reserved_usd')
        if reserved is None:
            raise ValueError('예약액이 없는 비용 미상 기록입니다. 대시보드 확인 전에는 계속하지 않습니다')
        return Decimal('0'), Decimal(reserved)
    return Decimal('0'), None


def totals(rows):
    known, unknown, unknown_calls = Decimal('0'), Decimal('0'), 0
    for row in rows:
        k, u = row_cost(row)
        known += k
        if u is not None:
            unknown += u
            unknown_calls += 1
    return known, unknown, unknown_calls


def new_state(metadata, budget, args):
    return {'document_type': STATE_TYPE, 'created_at': datetime.now(UTC).isoformat(),
            'purpose': 'minimum_screening_not_full_quality_gate',
            'billing_unit': 'isolated_feature_call', 'pricing_checked': '2026-11-17',
            'budget_usd': str(budget), 'timeout_seconds': args.timeout,
            'max_output_tokens': args.max_output_tokens, 'efforts': [EFFORT],
            'shared_catalog_preparation': metadata, 'calls': [], 'events': [],
            'notes': ['기능 단독 호출이며 앱 업무 1회 비용이 아닙니다.',
                      '추계는 공식 요금표 기준이며 실제 청구액과 대조하지 않았습니다.',
                      '비용 미상 호출은 0달러가 아니라 예약액으로 따로 표시합니다.']}


def save(state, path):
    state['updated_at'] = datetime.now(UTC).isoformat()
    known, unknown, unknown_calls = totals(state['calls'])
    state['known_estimated_usd'] = str(known)
    state['unknown_reserved_usd'] = str(unknown)
    state['unknown_cost_calls'] = unknown_calls
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def load_state(out_dir, metadata, budget, args):
    """기존 결과를 자동 탐색한다. 상태 파일이 있으면 이어 쓰고, 같은 입력의 다른 live
    보고서 행은 한 번만 가져온다(재과금 방지). 아무것도 지우거나 덮어쓰지 않는다."""
    path = out_dir / STATE_NAME
    state = read_json(path) if path.exists() else new_state(metadata, budget, args)
    if state.get('document_type') != STATE_TYPE:
        raise ValueError('상태 파일 형식이 다릅니다')
    if state['shared_catalog_preparation'].get('prepared_products_sha256') != metadata[
            'prepared_products_sha256']:
        raise ValueError('이전 결과의 카탈로그 해시가 다릅니다. 새 --out-dir에서 시작하세요')
    state['budget_usd'] = str(budget)
    seen = {row_key(row) for row in state['calls']}
    for other in sorted(out_dir.glob('*.json')) if out_dir.exists() else []:
        if other.name == STATE_NAME:
            continue
        try:
            doc = read_json(other)
        except (ValueError, OSError):
            continue
        if not isinstance(doc, dict) or doc.get('mode') != 'live' or not isinstance(doc.get('calls'), list):
            continue
        for row in doc['calls']:
            try:
                key = row_key(row)
            except (KeyError, TypeError):
                continue
            if row.get('status') in KNOWN | UNKNOWN and key not in seen:
                state['calls'].append({**row, 'imported_from': other.name})
                seen.add(key)
    return state, path


def plan(cases, args):
    """(case, model, repeat) 전체 계획. 모델 바깥 반복이라 Luna 10개 뒤 Sol 10개다."""
    return [(case, model, repeat) for model in args.models for case in cases
            for repeat in range(1, args.repeats + 1)]


def call_key(case, model, repeat):
    # model_benchmark.run이 행에 남기는 input_sha256과 같은 계산이다.
    return (case['id'], model, EFFORT, repeat,
            sha256(json.dumps(case['request'], sort_keys=True).encode()).hexdigest())


def pending_calls(planned, state, allow_rerun_unknown):
    existing = {}
    for row in state['calls']:
        existing.setdefault(row_key(row), []).append(row)
    pending, reused, blocked = [], [], []
    for case, model, repeat in planned:
        rows = existing.get(call_key(case, model, repeat), [])
        if any(row['status'] in KNOWN for row in rows):
            reused.append((case['id'], model, repeat))
        elif any(row['status'] in UNKNOWN and not row.get('superseded_by_rerun') for row in rows):
            if allow_rerun_unknown:
                pending.append((case, model, repeat))
            else:
                blocked.append((case['id'], model, repeat))
        else:
            pending.append((case, model, repeat))
    return pending, reused, blocked


class PreflightError(Exception):
    """사전 계수 실패 지점(모델·질의 ID)과 원인 종류만 담는다. 본문/키는 담지 않는다."""

    def __init__(self, model, case_id, error):
        super().__init__('preflight failed')
        self.detail = (f'{type(error).__name__}:status={getattr(error, "status_code", None)}'
                       f':{model}:{case_id}')


def batch_preflight(client, pending, args):
    """생성 전에 대기 중인 모든 요청의 입력을 계수하고 최악 예약액을 합산한다."""
    from app.evaluation.model_benchmark import cost_usd
    total, per_model = Decimal('0'), {}
    for case, model, _repeat in pending:
        request = {**deepcopy(case['request']), 'model': model, 'reasoning': {'effort': EFFORT}}
        try:
            counted = client.responses.input_tokens.count(**request, timeout=args.timeout).input_tokens
            if type(counted) is not int or not 0 <= counted <= args.max_input_tokens:
                raise ValueError('사전 계수한 입력 토큰이 상한을 벗어났습니다')
            reserve = cost_usd(model, counted, 0, args.max_output_tokens)
        except Exception as error:
            raise PreflightError(model, case['id'], error) from None
        total += reserve
        per_model[model] = per_model.get(model, Decimal('0')) + reserve
    return total, per_model


def summarize(state):
    out = {}
    for row in state['calls']:
        if row.get('superseded_by_rerun'):
            continue
        item = out.setdefault(row['model'], {'calls': 0, 'passed': 0, 'quality_failed': 0,
                                              'invalid_output': 0, 'incomplete': 0,
                                              'cost_unknown': 0, 'not_billed': 0})
        status = row['status']
        if status in KNOWN or status in UNKNOWN:
            item['calls'] += 1
        if status == 'completed':
            item['passed' if row.get('quality', {}).get('passed') else 'quality_failed'] += 1
        elif status == 'invalid_output':
            item['invalid_output'] += 1
        elif status == 'incomplete':
            item['incomplete'] += 1
        elif status in UNKNOWN:
            item['cost_unknown'] += 1
        else:
            item['not_billed'] += 1
    return out


def masked_input(prompt, reader=None, write=None):
    """입력한 글자마다 *를 보여 주는 비공개 입력(Windows 콘솔 붙여넣기 포함).
    Enter=확정, Backspace=지우기, Esc/Ctrl-C=취소(빈 값). 키 내용은 화면에 남지 않는다."""
    write = write or (lambda text: (sys.stdout.write(text), sys.stdout.flush()))
    if reader is None:
        try:
            import msvcrt
        except ImportError:
            return getpass(prompt)       # Windows 밖에서는 표준 비공개 입력
        reader = msvcrt.getwch
    write(prompt)
    chars = []
    while True:
        ch = reader()
        if ch in ('\r', '\n'):
            write('\n')
            return ''.join(chars)
        if ch in ('\x03', '\x1b'):
            write('\n')
            return ''
        if ch in ('\x08', '\x7f'):
            if chars:
                chars.pop()
                write('\b \b')
        elif ch in ('\x00', '\xe0'):
            reader()                      # 방향키 등 확장 키의 두 번째 코드는 버린다
        elif ch.isprintable():
            chars.append(ch)
            write('*')


def window_input(prompt):
    """별도 입력창(글자는 *). Ctrl+V 또는 [붙여넣기] 버튼으로 붙여넣는다. 취소/닫기=빈 값."""
    import tkinter as tk
    root = tk.Tk()
    root.title('OpenAI API 키 입력')
    root.attributes('-topmost', True)
    tk.Label(root, text=prompt, wraplength=440, justify='left').pack(padx=12, pady=(12, 6))
    var = tk.StringVar()
    entry = tk.Entry(root, textvariable=var, show='*', width=64)
    entry.pack(padx=12)
    result = {'value': ''}

    def paste():
        try:
            var.set(root.clipboard_get().strip())
        except tk.TclError:
            pass

    def confirm(_event=None):
        result['value'] = var.get()
        root.destroy()

    def cancel(_event=None):
        root.destroy()

    buttons = tk.Frame(root)
    buttons.pack(pady=10)
    tk.Button(buttons, text='붙여넣기', command=paste).pack(side='left', padx=4)
    tk.Button(buttons, text='확인', command=confirm).pack(side='left', padx=4)
    tk.Button(buttons, text='취소', command=cancel).pack(side='left', padx=4)
    root.bind('<Return>', confirm)
    root.bind('<Escape>', cancel)
    root.after(100, entry.focus_force)
    root.mainloop()
    return result['value']


def read_secret(prompt, mode):
    if mode == 'window':
        try:
            return window_input('OpenAI API 키를 붙여넣고 확인을 누르세요. 글자는 *로 표시되며 저장하지 않습니다. 취소/빈 값=실행 안 함.')
        except Exception:
            print('입력창을 열 수 없어 터미널 입력으로 바꿉니다.')
    return masked_input(prompt)


def main(argv=None, *, ask=input, ask_secret=None, client_factory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--queries', type=Path, required=True)
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True,
                        help='결과/상태 폴더(레포 밖 권장: 카탈로그 SKU가 들어갑니다)')
    parser.add_argument('--live', action='store_true', help='개인 PC에서 유료 API 호출 허용')
    parser.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    parser.add_argument('--repeats', type=int, choices=range(1, 4), default=1)
    parser.add_argument('--budget-usd', type=Decimal, default=Decimal('0.50'))
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--max-output-tokens', type=int, default=2048)
    parser.add_argument('--max-input-tokens', type=int, default=60000)
    parser.add_argument('--key-input', choices=('window', 'terminal'), default='window',
                        help='키 입력 방식: 별도 입력창(기본) 또는 터미널(*표시)')
    parser.add_argument('--allow-rerun-unknown', action='store_true',
                        help='비용 미상 기록을 대시보드로 확인한 뒤에만: 예약액은 유지한 채 다시 호출')
    args = parser.parse_args(argv)
    if not args.budget_usd.is_finite() or args.budget_usd <= 0 or not 0 < args.timeout <= 600 \
            or not 1 <= args.max_output_tokens <= 8192 or not 1 <= args.max_input_tokens <= 200000:
        parser.error('예산/시간/토큰 상한을 확인하세요(출력 상한은 8192 이하)')
    sys.path.insert(0, str(args.repo.resolve()))
    snapshot = read_json(args.snapshot)
    queries_doc = read_json(args.queries)
    approval = read_json(args.approval)
    problems = verify_inputs(snapshot, queries_doc, approval)
    if problems:
        parser.error('입력 검증 실패: ' + '; '.join(problems))
    cases, metadata = load_prepare().prepare(snapshot, queries_doc['queries'])
    state, state_path = load_state(args.out_dir, metadata, args.budget_usd, args)
    planned = plan(cases, args)
    pending, reused, blocked = pending_calls(planned, state, args.allow_rerun_unknown)
    known, unknown, unknown_calls = totals(state['calls'])
    remaining = args.budget_usd - known - unknown
    header = {'mode': 'live' if args.live else 'dry_plan', 'planned_calls': len(planned),
              'reuse_existing_results': len(reused), 'pending_calls': len(pending),
              'blocked_unknown_cost_calls': len(blocked),
              'known_estimated_usd': str(known), 'unknown_reserved_usd': str(unknown),
              'budget_usd': str(args.budget_usd), 'budget_remaining_usd': str(remaining),
              'generation_attempts': 0}
    if blocked:
        print(json.dumps({**header, 'stopped': 'unknown_cost_call_exists',
                          'blocked': [list(item) for item in blocked]}, ensure_ascii=False))
        print('비용 미상 호출이 있어 진행하지 않습니다. 공급자 대시보드를 확인한 뒤 '
              '--allow-rerun-unknown을 명시하거나 결과를 새 폴더에서 다시 시작하세요.')
        return 3
    if not args.live:
        print(json.dumps(header, ensure_ascii=False))
        return 0
    if not pending:
        print(json.dumps({**header, 'summary': summarize(state)}, ensure_ascii=False))
        return 0
    if remaining <= 0:
        print(json.dumps({**header, 'stopped': 'budget_exhausted'}, ensure_ascii=False))
        return 3
    args.out_dir.mkdir(parents=True, exist_ok=True)
    save(state, state_path)

    def record(event):
        state['events'].append({'at': datetime.now(UTC).isoformat(), 'event': event})
        save(state, state_path)

    try:
        prompt = 'OpenAI API 키 입력(붙여넣기 후 Enter, 글자는 *로 표시. Enter만=실행 안 함): '
        key = ((ask_secret(prompt) if ask_secret else read_secret(prompt, args.key_input)) or '').strip()
    except (KeyboardInterrupt, EOFError):
        key = ''
    if not key:
        record('key_not_provided')
        print('키를 받지 못해 실행하지 않았습니다. 기존 결과와 진행 기록은 그대로입니다(미확인).')
        return 2
    if client_factory is None:
        from openai import OpenAI

        def client_factory(secret):
            return OpenAI(api_key=secret, base_url='https://api.openai.com/v1',
                          max_retries=0, timeout=args.timeout)
    print(f'키 {len(key)}자 입력됨(내용은 표시·저장하지 않습니다).')
    client = client_factory(key)
    del key
    try:
        try:
            worst, per_model = batch_preflight(client, pending, args)
        except Exception as error:
            detail = error.detail if isinstance(error, PreflightError) else type(error).__name__
            record(f'batch_preflight_failed:{detail}')
            print(f'사전 토큰 계수 실패({detail}). 생성 호출 0회로 중단했습니다. 과금 없음.')
            return 3
        if worst > remaining:
            record('batch_worst_case_exceeds_budget')
            print(json.dumps({**header, 'stopped': 'batch_worst_case_exceeds_budget',
                              'worst_case_usd': str(worst)}, ensure_ascii=False))
            return 3
        print(json.dumps({**header, 'worst_case_reserved_usd': str(worst),
                          'worst_case_by_model': {m: str(v) for m, v in per_model.items()}},
                         ensure_ascii=False))
        answer = (ask('위 조건으로 유료 API 호출을 시작합니다. 시작하려면 yes 입력 '
                      '(그 외·Enter·모름·취소=시작 안 함, 진행 기록 유지): ') or '').strip().lower()
        if answer != 'yes':
            record('start_not_confirmed')
            print('시작하지 않았습니다(미확인). 기존 결과는 그대로입니다.')
            return 2
        from app.evaluation.model_benchmark import run
        previous_stop = state.pop('stopped', None)   # 이전 중단 이유는 이벤트에 남긴다
        record('live_started' + (f':after_{previous_stop}' if previous_stop else ''))
        stopped = None
        for case, model, repeat in pending:
            known, unknown, _ = totals(state['calls'])
            slot = {}

            def checkpoint(report, slot=slot, repeat=repeat):
                slot.clear()
                slot.update(deepcopy(report['calls'][-1]))
                slot['repeat'] = repeat    # run()은 단일 호출이라 repeat=1로 적는다
                if not any(row is slot for row in state['calls']):
                    state['calls'].append(slot)
                save(state, state_path)

            for old in state['calls']:
                if row_key(old) == call_key(case, model, repeat) and old['status'] in UNKNOWN:
                    old['superseded_by_rerun'] = True   # 기록·예약액은 보존한다
            report = run([case], [model], [EFFORT], client=client,
                         budget=args.budget_usd - known - unknown, timeout=args.timeout,
                         max_output_tokens=args.max_output_tokens,
                         max_input_tokens=args.max_input_tokens, include_output=True,
                         checkpoint=checkpoint)
            checkpoint(report)
            if report.get('stopped'):
                stopped = report['stopped']
                break      # 다른 모델/남은 호출을 자동으로 이어 부르지 않는다
        if stopped:
            state['stopped'] = stopped
        save(state, state_path)
    except KeyboardInterrupt:
        save(state, state_path)
        print('중단했습니다. 진행 중이던 호출은 비용 미상으로 남습니다. 대시보드를 확인하세요.')
        return 130
    finally:
        client.close()
    known, unknown, unknown_calls = totals(state['calls'])
    print(json.dumps({'mode': 'live', 'stopped': state.get('stopped'),
                      'known_estimated_usd': str(known), 'unknown_reserved_usd': str(unknown),
                      'unknown_cost_calls': unknown_calls, 'summary': summarize(state),
                      'not_full_quality_gate': True, 'state': str(state_path)}, ensure_ascii=False))
    return 1 if state.get('stopped') else 0


if __name__ == '__main__':
    raise SystemExit(main())
