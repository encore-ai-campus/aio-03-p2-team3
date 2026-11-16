"""확정 원문의 위치를 보존하는 조항 parent / 문자 단위 child 분할."""
import re
from uuid import uuid4

from app.knowledge.schemas import ChildChunk, KnowledgeError, PageText, ParentChunk, SourceSpan

PARENT_CHARS = 8000
CHILD_CHARS = 1000
OVERLAP_CHARS = 150
CLAUSE = re.compile(r"(?im)^(?:제\s*\d+\s*조(?:의\s*\d+)?[^\n]*|article\s+\d+[^\n]*)")


def _ranges(text: str, start: int, end: int, size: int, overlap: int = 0):
    while start < end:
        stop = min(start + size, end)
        if stop < end:
            boundary = max(text.rfind("\n", start + size // 2, stop),
                           text.rfind(" ", start + size // 2, stop))
            if boundary > start:
                stop = boundary
        left, right = start, stop
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            yield left, right
        if stop == end:
            break
        start = max(start + 1, stop - overlap)


def build_chunks(pages: list[PageText]) -> tuple[list[ParentChunk], list[ChildChunk]]:
    text, locations = "", []
    for page in pages:
        if text:
            text += "\n\n"
        start = len(text)
        text += page.text
        locations.append((page, start, len(text)))
    if not text.strip():
        raise KnowledgeError("empty_text", "임베딩할 원문이 없습니다. 추출문을 확인해 주세요.")
    cuts = sorted({0, len(text), *(m.start() for m in CLAUSE.finditer(text))})
    parents, children = [], []
    for clause_start, clause_end in zip(cuts, cuts[1:]):
        for start, end in _ranges(text, clause_start, clause_end, PARENT_CHARS):
            parent = ParentChunk(
                id=str(uuid4()), ordinal=len(parents), text=text[start:end], start=start, end=end,
                sources=[SourceSpan(page=p.number, source=p.source,
                                    start=max(start, a) - a, end=min(end, b) - a)
                         for p, a, b in locations if max(start, a) < min(end, b)],
            )
            parents.append(parent)
            for left, right in _ranges(parent.text, 0, len(parent.text), CHILD_CHARS, OVERLAP_CHARS):
                children.append(ChildChunk(id=str(uuid4()), parent_id=parent.id, ordinal=len(children),
                                           text=parent.text[left:right], start=left, end=right))
    return parents, children
