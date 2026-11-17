"""품목 후보 검색. 검색 점수는 추천 순서일 뿐 SKU/단가를 확정하지 않는다."""
from difflib import SequenceMatcher
import re
import unicodedata


# 발음으로 입력하는 대표 검색어. 원본 카탈로그 이름/출력 문서는 바꾸지 않는다.
SEARCH_TERMS = {
    '슈퍼라이트': 'superlight', '수퍼라이트': 'superlight',
    '로지텍': 'logitech', '컴팩트': 'compact', '콤팩트': 'compact',
    '블랙': 'black', '검정': 'black', '화이트': 'white', '흰색': 'white',
    '핑크': 'pink', '분홍': 'pink',
}


def search_tokens(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    for term, replacement in SEARCH_TERMS.items():
        text = re.sub(r'\s*'.join(map(re.escape, term)), f' {replacement} ', text)
    # SUPERLIGHT2와 superlight 2를 같은 단어/세대 토큰으로 비교한다.
    return re.findall(r'[^\W\d_]+|\d+', text)


def search_products(query, products):
    """모든 검색 토큰이 설명되는 후보만 반환한다. 숫자(세대)는 정확히 비교한다."""
    observed = search_tokens(query)
    if not observed or len(''.join(observed)) < 2:
        return []
    results, seen = [], set()
    for product in products:
        identity = (product.get('item_name'), product.get('source_code'), product.get('capacity'))
        if identity in seen:
            continue
        seen.add(identity)
        canonical = search_tokens(product.get('item_name'))
        scores = []
        for token in observed:
            if token in canonical:
                scores.append(1.0)
            elif token.isdigit():
                break
            else:
                best = max((SequenceMatcher(None, token, word).ratio()
                            if min(len(token), len(word)) >= 4 else 0
                            for word in canonical), default=0)
                if len(token) >= 3 and any(word.startswith(token) for word in canonical):
                    best = max(best, .9)
                if best < .78:
                    break
                scores.append(best)
        else:
            score = sum(scores) / len(scores)
            results.append({'product': product, 'similarity': round(score, 3)})
    return sorted(results, key=lambda row: (-row['similarity'],
                  len(search_tokens(row['product']['item_name'])),
                  row['product']['item_name'].casefold(), str(row['product'].get('id', ''))))
