"""PO/PI event commands and derived quantities; prices and other documents stay separate."""
from decimal import InvalidOperation
import re
import unicodedata

_PAIR = re.compile(r'(?<![0-9a-z.\-])(\d+)\s*\+\s*(\d+)(?![0-9a-z.])', re.I)
_ENGLISH = re.compile(r'\bbuy\s+(\d+)\s*(?:pcs|pieces|units)?\s*,?\s*get\s+(\d+)\s*(?:pcs|pieces|units)?\s*(?:free|foc)?', re.I)
_KOREAN = re.compile(r'(\d+)\s*개?\s*(?:구매|주문)\s*(?:시|하면)?\s*(\d+)\s*개?\s*(?:증정|무료)')
_GLOBAL = re.compile(r'\b(?:all|every|entire)\b|전체|모든|전\s*(?:품목|제품)', re.I)
_NEGATED = re.compile(r"\bnot\b|\bexcept\b|don't|do\s+not|cancel|적용\s*하지|하지\s*마|제외|취소|미적용", re.I)


def _text(value):
    return unicodedata.normalize('NFKC', str(value or '')).replace('−', '-').casefold()


def _rules(value):
    text = _text(value)
    matches = []
    for pattern in (_PAIR, _ENGLISH, _KOREAN):
        for match in pattern.finditer(text):
            if int(match[1]) >= 1:
                matches.append((match.start(), match.end(), f'{int(match[1])}+{int(match[2])}'))
    return sorted(matches)


def normalize_promotion(value):
    text = _text(value)
    if _NEGATED.search(text):
        return None
    values = {rule for _, _, rule in _rules(text)}
    return next(iter(values)) if len(values) == 1 else None


def recalculate_order_promotions(draft):
    """Return an independent result for event rows; never alter the caller's rows."""
    if draft.get('document_type') not in {'PO', 'PI'} or not any(i.get('promotion') for i in draft.get('items', [])):
        return draft
    # Local import avoids changing the original arithmetic function or a cycle.
    from Quotation_KEKOREA.agent.trade_documents import apply_promotion
    result = {**draft, 'items': [dict(item) for item in draft.get('items', [])]}
    for item in result['items']:
        if draft.get('document_type') == 'PI' and item.get('is_sample') is True:
            continue
        if not item.get('promotion'):
            continue
        rule = normalize_promotion(item['promotion'])
        if not rule:
            continue  # Existing deterministic validation reports an invalid rule.
        item['promotion'] = rule
        paid = item.get('paid_quantity')
        if paid in (None, ''):
            paid = item.get('quantity')
        if paid in (None, ''):
            continue
        try:
            quantities = apply_promotion(str(paid), rule)
        except (ValueError, InvalidOperation, TypeError):
            continue
        item.update(quantities)
        item['quantity'] = quantities['paid_quantity']
    return result


def apply_promotion_commands(draft, prompt, *, products=()):
    """Resolve explicit all-item or named-item commands; never create order rows."""
    if draft.get('document_type') not in {'PO', 'PI'}:
        return draft
    text = _text(prompt)
    rules = _rules(text)
    items = draft.get('items', [])
    anchors = []
    for index, item in enumerate(items):
        if draft.get('document_type') == 'PI' and item.get('is_sample') is True:
            continue
        names = {str(item.get('product_name') or '')}
        if products:
            from Quotation_KEKOREA.agent.product_matching import match_product
            match = match_product(item.get('product_name'), item.get('capacity'), products, item.get('product_code'))
            if match['status'] == 'matched':
                names.add(match['product']['item_name'])
        for name in names:
            words = _text(name).split()
            if not words:
                continue
            pattern = r'(?<![a-z0-9])' + r'\s*'.join(map(re.escape, words)) + r'(?![a-z0-9])'
            anchors.extend((m.start(), m.end(), index) for m in re.finditer(pattern, text))
    separators = [m.start() for m in re.finditer(r'[;,\n.!?]', text)
                  if not any(start <= m.start() < end for start, end, _ in anchors)]
    global_rules = set()
    named_rules = {}
    previous_end = 0
    previous_targets = set()
    previous_global = False

    def conflict(message):
        entries = draft.setdefault('conflicts', [])
        message = 'Promotion command ' + message
        if message not in entries:
            entries.append(message)

    for start, end, rule in rules:
        left = max([previous_end] + [s + 1 for s in separators if previous_end <= s < start])
        right = min([len(text)] + [s for s in separators if s >= end])
        scope = text[left:start]
        targets = {i for begin, finish, i in anchors if left <= begin and finish <= start}
        if targets:
            compact_scope = re.sub(r'\s+', '', scope).replace('×', '*').replace('x', '*')
            sized_targets = set()
            for index in targets:
                size = re.sub(r'\s+', '', _text(items[index].get('capacity'))).replace('×', '*').replace('x', '*')
                if size and re.search(r'(?<![0-9.])' + re.escape(size) + r'(?![a-z0-9])', compact_scope):
                    sized_targets.add(index)
            if sized_targets:
                targets = sized_targets
            elif re.search(r'\d\s*(?:ml|g)\b', scope):
                targets = set()
        is_global = bool(_GLOBAL.search(scope)) and not targets
        if not targets and not is_global and re.fullmatch(r'\s*(?:or|또는|혹은)\s*', scope):
            targets, is_global = previous_targets, previous_global
        if not targets and not is_global and len(rules) == 1 and (not anchors or not scope.strip()):
            # A standalone event after an invoice request applies to its rows.
            is_global = not scope.strip() or bool(re.search(r'\b(?:pi|po|invoice|order)\b|작성|행사|이벤트', scope))
        if _NEGATED.search(text[left:right]):
            conflict('is negated or cancelled; confirm the intended event before creating the order')
        elif is_global:
            global_rules.add(rule)
        elif targets:
            for index in targets:
                named_rules.setdefault(index, set()).add(rule)
        else:
            conflict('target is unclear; name the product or specify all products')
        previous_end, previous_targets, previous_global = end, targets, is_global
    if len(global_rules) > 1 or any(len(values) > 1 for values in named_rules.values()):
        conflict('contains conflicting event ratios; specify one ratio per product')
    else:
        default = next(iter(global_rules)) if global_rules else None
        for index, item in enumerate(items):
            if draft.get('document_type') == 'PI' and item.get('is_sample') is True:
                continue
            chosen = next(iter(named_rules[index])) if index in named_rules else default
            if chosen:
                item['promotion'] = chosen
            elif rules and named_rules and item.get('promotion'):
                existing = normalize_promotion(item['promotion'])
                source = _text(item.get('source'))
                if existing and existing != normalize_promotion(source):
                    # Do not keep an AI-applied event on an untargeted row unless
                    # its own source supports that event. Manual FOC stays separate.
                    item.pop('promotion', None)
                    explicit_free = re.search(r'\b(?:free|foc|gift)\s*[:=]?\s*\d+|\d+\s*(?:pcs\s*)?(?:free|foc)|증정\s*\d+|\d+\s*개?\s*증정', source)
                    if not explicit_free:
                        item['free_quantity'] = '0'
                        paid = item.get('paid_quantity')
                        if paid in (None, ''):
                            paid = item.get('quantity')
                        if paid not in (None, ''):
                            item['shipped_quantity'] = str(paid)
    result = recalculate_order_promotions(draft)
    if result is not draft:
        draft['items'] = result['items']
    return draft
