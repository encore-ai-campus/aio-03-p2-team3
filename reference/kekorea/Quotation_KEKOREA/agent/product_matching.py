"""Recognize complete catalog names inside annotations without fuzzy SKU guesses."""
from decimal import Decimal
from difflib import SequenceMatcher
from functools import lru_cache
import re
import unicodedata


def _text(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = re.sub('[\u200b-\u200f\ufeff]', '', text)
    text = text.translate(str.maketrans('‐‑‒–—−【】〔〕', '------[][]'))
    return re.sub(r'&|＆', ' and ', text).replace('_', ' ')


def _compact(value):
    return ''.join(re.findall(r'[^\W_]+', _text(value)))


@lru_cache(maxsize=2048)
def _pattern(key):
    # Boundaries prevent matching Cell Memory Cream inside SuperCell Memory Cream.
    return re.compile(r'(?<!\w)' + r'[\W_]*'.join(map(re.escape, key)) + r'(?!\w)')


def _unit_text(value):
    text = _text(value)
    for pattern, replacement in ((r'\bmillilit(?:er|re)s?\b', 'ml'),
                                 (r'\bmilligrams?\b|毫克', 'mg'),
                                 (r'\bkilograms?\b|千克', 'kg'),
                                 (r'\blit(?:er|re)s?\b', 'l'),
                                 (r'毫升|밀리리터', 'ml'), (r'克|그램', 'g'),
                                 (r'\bgrams?\b', 'g'), (r'\b(?:pieces?|pcs?|個|개)\b', 'pcs')):
        text = re.sub(pattern, replacement, text)
    return re.sub(r'\d+(?:\.\d+)?', lambda m: format(Decimal(m[0]).normalize(), 'f'), text)


def _capacity(value):
    text = _unit_text(value)
    text = re.sub(r'^(?:capacity|size|용량)\s*[:=]?\s*', '', text)
    text = re.sub(r'\s+', '', text).replace('×', '*').replace('✕', '*').rstrip('.,;')
    text = re.sub(r'(?<=[\d\w)])x(?=[\d(])', '*', text)
    text = text.replace('[', '(').replace(']', ')')
    # Remove enclosing brackets only when they wrap the whole expression.
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for index, char in enumerate(text):
            depth += (char == '(') - (char == ')')
            if depth == 0:
                break
        if index != len(text) - 1:
            break
        text = text[1:-1]
    reversed_pack = re.fullmatch(r'(\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?(?:ml|g|pcs))', text)
    if reversed_pack:
        text = reversed_pack[2] + '*' + reversed_pack[1]
    return text or None


_MEASURE = re.compile(r'\d+(?:\.\d+)?\s*(?:ml|mg|kg|ul|μl|fl\s*oz|oz|cc|l|g|pcs)(?=[^a-z]|x\s*\d|$)(?:\s*[*x×✕]\s*\d+)?')
_LABELS = re.compile(r'\b(?:eclado|item|items|product|name|description|code|sku|model|capacity|size)\b'
                     r'|\bno\b|에끌라도|에끌라두|제품코드|제품명|상품명|품명|코드|용량')
_CODE_LABEL = r'(?:\bsku\b|\bcode\b|\bmodel\b|\bitem\s*(?:no\.?|number|#)|제품코드|상품코드|품번|제품번호|코드)'
_ORDER_QUANTITY = re.compile(r'(?:\bqty\b|\bquantity\b|수량)\s*[:=]?\s*\d+(?:\.\d+)?\s*(?:pcs|pc|pieces|개)?\b')
_VARIANT = re.compile(r'\b(?:sample|tester|refill|mini|plus|travel|not|without|except)\b'
                      r'|\b(?:new|old)\s+formula\b|샘플|테스터|리필|미니|아닌|제외')


def _inline_size_agrees(residue, reference):
    text = _unit_text(residue)
    terms = list(_MEASURE.finditer(text))
    if not terms:
        return True
    if not reference:
        return False
    start, end = terms[0].start(), terms[-1].end()
    reverse_pack = re.search(r'\d+(?:\.\d+)?\s*[*x×✕]\s*$', text[:start])
    if reverse_pack:
        start = reverse_pack.start()
    while start and text[start - 1] in ' ([\t\n':
        start -= 1
    while end < len(text) and text[end] in '0123456789.,()+*/x×✕[] \t\n':
        end += 1
    expression = text[start:end].strip(' \t\n,;').replace('[', '(').replace(']', ')')
    # Description brackets can enclose an expression and words. Remove only the
    # unbalanced outer wrapper, preserving inner groups and pack multipliers.
    while expression.startswith('(') and expression.count('(') > expression.count(')'):
        expression = expression[1:].lstrip()
    while expression.endswith(')') and expression.count(')') > expression.count('('):
        expression = expression[:-1].rstrip()
    return _capacity(expression) == _capacity(reference)


def _ratings(value):
    text = _text(value)
    return (tuple((m[1], m[2].count('+')) for m in re.finditer(r'(?<![a-z])spf\s*(\d+)\s*((?:\+\s*)*)', text)),
            tuple(m[1].count('+') for m in re.finditer(r'(?<![a-z])pa(?![a-z])\s*((?:\+\s*)*)', text)))


def _fuzzy_match(name, capacity, residue, products):
    if _VARIANT.search(residue):
        return {'status': 'not_found', 'matches': []}
    observed = _unit_text(residue)
    observed = _MEASURE.sub(' ', observed)
    observed = _ORDER_QUANTITY.sub(' ', observed)
    observed = _LABELS.sub(' ', observed)
    for product in products:
        code = _compact(product.get('source_code'))
        if code:
            observed = _pattern(code).sub(' ', observed)
    observed = _compact(observed)
    if not observed:
        return {'status': 'not_found', 'matches': []}

    scored = []
    for product in products:
        item_name = _compact(product.get('item_name'))
        if not item_name or _ratings(name) != _ratings(product.get('item_name')):
            continue
        if capacity not in (None, '') and _capacity(product.get('capacity')) != _capacity(capacity):
            continue
        if not _inline_size_agrees(residue, product.get('capacity')):
            continue
        canonical_tokens = set(re.findall(r'[^\W_]+', _text(product.get('item_name'))))
        observed_tokens = set(re.findall(r'[^\W_]+', _text(residue)))
        token_score = (2 * len(canonical_tokens & observed_tokens) /
                       (len(canonical_tokens) + len(observed_tokens))) if canonical_tokens or observed_tokens else 0
        score = 0.9 * SequenceMatcher(None, observed, item_name).ratio() + 0.1 * token_score
        scored.append((score, product))
    if not scored:
        return {'status': 'not_found', 'matches': []}

    scored.sort(key=lambda result: result[0], reverse=True)
    best_score = scored[0][0]
    close = [(score, product) for score, product in scored if best_score - score < 0.04]
    suggestions = [{'product': product, 'similarity': round(score, 3)}
                   for score, product in scored[:3] if best_score - score < 0.18]
    if best_score >= 0.90 and len(close) == 1:
        product = scored[0][1]
        return {
            'status': 'matched',
            'product': product,
            'match_method': 'fuzzy',
            'similarity': round(best_score, 3),
            'confirmation': (
                f'Double-check this product: source text "{name}" is similar to '
                f'{product["item_name"]} ({best_score:.0%}). Confirm before using its catalog price.'
            ),
        }
    if best_score >= 0.68:
        return {
            'status': 'suggested',
            'matches': [product for _, product in close],
            'suggestions': suggestions,
        }
    return {'status': 'not_found', 'matches': []}


def match_product(name, capacity, products, product_code=None):
    products = [p for p in products if p.get('brand') == 'ECLADO']
    text = _text(name)
    code_keys = {_compact(p.get('source_code')) for p in products if p.get('source_code')}
    internal_codes = set()
    # A verified SKU may appear between the words of a complete product name.
    # Preserve its constraint while removing only that catalog-backed annotation.
    for bracket in list(re.finditer(r'[\[({]([^\[\](){}]*)[\])}]', text)):
        inner = re.sub('^' + _CODE_LABEL + r'\s*[:=#]?\s*', '', bracket[1])
        code = _compact(inner)
        if code in code_keys:
            internal_codes.add(code)
            start, end = bracket.span()
            text = text[:start] + ' ' * (end - start) + text[end:]
    found = []
    for product in products:
        key = _compact(product.get('item_name'))
        if key:
            for match in _pattern(key).finditer(text):
                found.append((product, match.span()))
    # Prefer a complete longer catalog name over a shorter name nested inside it.
    found = [(p, span) for p, span in found if not any(
        other[0] <= span[0] and other[1] >= span[1] and other != span for _, other in found)]
    spans = {span for _, span in found}
    if len(spans) > 1:
        return {'status': 'ambiguous', 'matches': [p for p, _ in found]}
    residue = text
    for start, end in sorted(spans, reverse=True):
        residue = residue[:start] + ' ' * (end - start) + residue[end:]

    mentioned = set(internal_codes)
    if product_code:
        mentioned.add(_compact(product_code))
    code_hits = [(key, match.span()) for key in code_keys for match in _pattern(key).finditer(residue)]
    mentioned.update(key for key, span in code_hits if not any(
        other[0] <= span[0] and other[1] >= span[1] and other != span for _, other in code_hits))
    # Explicit unknown codes must not be ignored as harmless descriptive words.
    for label in re.finditer(_CODE_LABEL + r'\s*[:=#]?\s*', residue):
        labeled_hits = [(key, _pattern(key).match(residue, label.end())) for key in code_keys]
        labeled_hits = [(key, hit) for key, hit in labeled_hits if hit]
        longest_end = max((hit.end() for _, hit in labeled_hits), default=-1)
        labeled_codes = {key for key, hit in labeled_hits if hit.end() == longest_end}
        if labeled_codes:
            mentioned.update(labeled_codes)
        else:
            token = re.match(r'[a-z0-9][a-z0-9.-]*', residue[label.end():])
            if token:
                mentioned.add(_compact(token[0]))
    for match in re.finditer(r'[\[({]\s*([a-z][a-z0-9.-]*\d[a-z0-9.-]*)\s*[\])}]', residue):
        mentioned.add(_compact(match[1]))
    for token in re.finditer(r'(?<!\w)[a-z][a-z0-9]*(?:\s*[-.]\s*[a-z0-9]+)+(?!\w)', residue):
        if re.search(r'\d', token[0]):
            mentioned.add(_compact(token[0]))
    if len(mentioned) > 1 or any(code not in code_keys for code in mentioned):
        return {'status': 'not_found', 'matches': []}
    for key in mentioned:
        residue = _pattern(key).sub(' ', residue)
    residue = _ORDER_QUANTITY.sub(' ', residue)

    if not found:
        # Code-only rows can resolve a unique SKU, but a code cannot override a
        # different product name supplied alongside it. A matching SKU can
        # narrow a typo candidate, but the name must still be sufficiently similar.
        if mentioned and not re.search(r'\w', _LABELS.sub('', residue)):
            found = [(p, (0, 0)) for p in products]
        else:
            if mentioned:
                code_products = [p for p in products if _compact(p.get('source_code')) in mentioned]
                return _fuzzy_match(name, capacity, residue, code_products)
            return _fuzzy_match(name, capacity, residue, products)
    if _VARIANT.search(residue):
        return {'status': 'not_found', 'matches': []}
    candidates = []
    for product, _ in found:
        if _ratings(name) != _ratings(product.get('item_name')):
            continue
        if mentioned and _compact(product.get('source_code')) not in mentioned:
            continue
        if capacity not in (None, '') and _capacity(product.get('capacity')) != _capacity(capacity):
            continue
        if not _inline_size_agrees(residue, product.get('capacity')):
            continue
        if product not in candidates:
            candidates.append(product)
    if len(candidates) != 1:
        return {'status': 'ambiguous' if candidates else 'not_found', 'matches': candidates}
    result = {'status': 'matched', 'product': candidates[0], 'match_method': 'exact'}
    annotation = _LABELS.sub('', _MEASURE.sub(' ', _unit_text(residue)))
    if re.search(r'\w', annotation):
        result['confirmation'] = f'Confirm product annotation for {name}; catalog product is {candidates[0]["item_name"]}'
    return result
