"""개인정보 가리기 — `docs/CONTRACT.md` 8.3절.

내보내기 파일과 실행 기록 화면에 같은 규칙을 쓴다. 한 `Masker`는 한 파일(또는 한 화면) 안에서
같은 이메일 주소·이름에 같은 번호를 준다.
"""
import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
BUSINESS_NO = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)")
# 한글 바로 뒤(예: '전화010-…')도 잡도록 앞뒤 경계는 영문·숫자·하이픈만 본다.
PHONE = re.compile(
    r"(?<![0-9A-Za-z-])(?:\+82[- ]?\(?0?\)?|0)\d{1,2}[- .)]?\d{3,4}[- .]?\d{4}(?![0-9A-Za-z-])"
)

# 이름 값을 담는 키(보낸 사람 표시 이름·담당자 이름)
NAME_KEYS = {"from_name", "display_name", "contact_name", "sender_name"}
# 메일 본문·답장 후보 본문을 담는 키
BODY_KEYS = {"body", "body_text", "body_html", "snippet"}
# 식별자·시각·이름표처럼 가리면 기록을 따라갈 수 없게 되는 키(개인정보가 아니다)
SAFE_KEYS = {
    "type", "run_id", "user_id", "seq", "at", "event", "node", "tool", "mode", "scenario",
    "message_id", "thread_id", "gmail_message_id", "source_message_id", "sent_message_id",
    "candidate_id", "quote_id", "started_at", "ended_at", "end_reason", "duration_ms",
    "reflection_enabled", "prompt_version",
}


class Masker:
    def __init__(self, mode: str):
        # mode=live는 실제 메일이라 본문을 길이로만 남긴다. mode=test는 지어낸 메일이라 남긴다.
        self.mode = mode
        self._emails: dict[str, str] = {}
        self._names: dict[str, str] = {}

    def _email(self, match: re.Match) -> str:
        address = match.group(0).lower()
        if address not in self._emails:
            self._emails[address] = f"<이메일{len(self._emails) + 1}>"
        return self._emails[address]

    def name(self, value: str) -> str:
        key = value.strip()
        if not key:
            return value
        if key not in self._names:
            self._names[key] = f"<이름{len(self._names) + 1}>"
        return self._names[key]

    def learn(self, value, key: str | None = None):
        """이름 키에 든 이름을 먼저 모아, 다른 글(오류 문구·시험 본문)에 섞인 같은 이름도 가린다."""
        if isinstance(value, dict):
            for k, v in value.items():
                self.learn(v, k)
        elif isinstance(value, list | tuple):
            for item in value:
                self.learn(item, key)
        elif isinstance(value, str) and key in NAME_KEYS:
            self.name(value)

    def text(self, value: str) -> str:
        # 긴 이름부터 바꿔 짧은 이름이 긴 이름의 일부를 먼저 바꾸지 않게 한다.
        for name in sorted(self._names, key=len, reverse=True):
            value = value.replace(name, self._names[name])
        value = EMAIL.sub(self._email, value)
        value = BUSINESS_NO.sub("<사업자번호>", value)
        return PHONE.sub("<전화>", value)

    def body(self, value: str) -> str:
        if self.mode == "live":
            return f"<본문 {len(value)}자>"
        return self.text(value)

    def value(self, value, key: str | None = None):
        """dict·list·문자열을 끝까지 따라가며 가린다. 원본은 바꾸지 않는다.

        여러 줄을 가릴 때는 먼저 `learn()`에 모두 넘겨야 앞줄의 글에 섞인 이름도 가려진다."""
        if isinstance(value, dict):
            return {k: self.value(v, k) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.value(item, key) for item in value]
        if not isinstance(value, str) or key in SAFE_KEYS:
            return value
        if key in NAME_KEYS:
            return self.name(value)
        if key in BODY_KEYS:
            return self.body(value)
        return self.text(value)
