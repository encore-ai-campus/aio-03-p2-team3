"""Apply scoped KE KOREA contract-workspace changes to a local Git checkout.
Never modifies quotation, ECLADO, pricing, or other application modules.
"""
from pathlib import Path
import sys

root = Path.cwd()
ui_path = root / 'Quotation_KEKOREA/contracts/ui.py'
test_path = root / 'Quotation_KEKOREA/tests/test_contract_workspace_ui.py'
if not ui_path.is_file() or not test_path.is_file():
    sys.exit('Run from KE_KOREA_CO_LTD repository root.')
ui = ui_path.read_text(encoding='utf-8')
tests = test_path.read_text(encoding='utf-8')

# Include the one-line fix from the prior partially applied patch, if missing.
old = '''    records = _records(repo)
    if records:
        st.markdown("### 저장된 계약")'''
new = '''    records = _records(repo)
    if records:
        options = {str(record["id"]): record for record in records}
        st.markdown("### 저장된 계약")'''
if old in ui:
    ui = ui.replace(old, new, 1)
elif new not in ui:
    sys.exit('Cannot safely identify saved-contract list; no changes applied.')

old = '''    messages = repo.list_messages(snapshot["contract_id"])
    with st.container(height=420, border=True):
        if not messages:
            st.caption("대화를 시작해 거래 조건과 확인 사항을 입력하세요.")
        for message in messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])
'''
new = '''    messages = repo.list_messages(snapshot["contract_id"])
    # Recent messages form the conversation; earlier records stay available on demand.
    older_messages, recent_messages = _chat_history_window(messages)
    if older_messages:
        with st.expander(f"이전 대화 {len(older_messages)}개 보기", expanded=False):
            for message in older_messages:
                with st.chat_message(message["role"]):
                    st.write(message["content"])
    with st.container(height=420, border=True):
        if not recent_messages:
            st.caption("대화를 시작해 거래 조건과 확인 사항을 입력하세요.")
        for message in recent_messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])
'''
if old in ui:
    ui=ui.replace(old,new,1)
elif new not in ui:
    sys.exit('Chat history code does not match expected version; no changes applied.')

anchor='''def _contract_chat(repo, snapshot, state_key, env):'''
helper='''def _chat_history_window(messages, *, recent_limit=20):
    """Return older and recent chat messages without mutating persisted history."""
    if recent_limit < 1:
        raise ValueError("recent_limit must be positive")
    return messages[:-recent_limit], messages[-recent_limit:]


'''
if helper not in ui:
    if ui.count(anchor) != 1:
        sys.exit('Could not locate chat renderer; no changes applied.')
    ui=ui.replace(anchor,helper+anchor,1)

old='''            repo.add_message(snapshot["contract_id"], "user", prompt.strip())
            selected_context ='''
new='''            repo.add_message(snapshot["contract_id"], "user", prompt.strip())
            with st.chat_message("user"):
                st.write(prompt.strip())
            selected_context ='''
if old in ui:
    ui=ui.replace(old,new,1)
elif new not in ui:
    sys.exit('Chat submit code does not match expected version; no changes applied.')

old='''            analysis = analyze_trade(prior_messages, snapshot, selected_context, env=env)'''
new='''            with st.spinner("AI가 거래조건을 분석하고 있습니다..."):
                analysis = analyze_trade(prior_messages, snapshot, selected_context, env=env)'''
if old in ui:
    ui=ui.replace(old,new,1)
elif new not in ui:
    sys.exit('Analysis call does not match expected version; no changes applied.')

old='''            repo.add_message(snapshot["contract_id"], "assistant",
                             f"조건 분석 완료: {len(analysis.get('terms', []))}개 조건 후보, "
                             f"{len(analysis.get('questions', []))}개 확인 질문.")'''
new='''            response = (f"거래조건을 분석했습니다. 조건 후보 {len(analysis.get('terms', []))}개, "
                        f"확인할 질문 {len(analysis.get('questions', []))}개입니다.")
            if analysis.get("questions"):
                response += "\\n\\n확인할 사항:\\n" + "\\n".join(
                    f"- {question}" for question in analysis["questions"][:5])
            if snapshot.get("clauses"):
                response += "\\n\\n기존 계약 내용은 자동 덮어쓰지 않았습니다. 아래 분석 후보를 검토해 적용하세요."
            repo.add_message(snapshot["contract_id"], "assistant", response)'''
if old in ui:
    ui=ui.replace(old,new,1)
elif new not in ui:
    sys.exit('Assistant response code does not match expected version; no changes applied.')

# Only add a small pure helper regression test; existing X/confirm/cancel tests must remain intact.
marker='''    def test_contract_delete_requires_confirmation(self):'''
addition='''    def test_contract_chat_history_keeps_older_messages_collapsed(self):
        from Quotation_KEKOREA.contracts.ui import _chat_history_window
        messages = [{"role": "user", "content": str(i)} for i in range(25)]
        older, recent = _chat_history_window(messages)
        self.assertEqual(len(older), 5)
        self.assertEqual(len(recent), 20)
        self.assertEqual(recent[0]["content"], "5")
        self.assertEqual(recent[-1]["content"], "24")
        self.assertEqual(len(messages), 25)

'''
if addition not in tests:
    if tests.count(marker)!=1:
        sys.exit('Cannot identify contract deletion tests; no changes applied.')
    tests=tests.replace(marker,addition+marker,1)

# Compile both new source texts before writing anything.
compile(ui, str(ui_path), 'exec')
compile(tests, str(test_path), 'exec')
ui_path.write_text(ui, encoding='utf-8')
test_path.write_text(tests, encoding='utf-8')
print('Updated:', ui_path.relative_to(root))
print('Updated:', test_path.relative_to(root))
print('Kept all other files unchanged; run contract tests before deployment.')
