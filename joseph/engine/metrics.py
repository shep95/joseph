"""pure-python string similarity metrics.

levenshtein distance and jaro-winkler similarity, used by entity resolution. no external
dependencies so the railway build stays small and the result is fully deterministic.
"""

from __future__ import annotations


def levenshtein(a: str, b: str) -> int:
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def levenshtein_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    d = levenshtein(a, b)
    m = max(len(a), len(b))
    return 1.0 - (d / m) if m else 1.0


def jaro(a: str, b: str) -> float:
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    match_distance = max(len(a), len(b)) // 2 - 1
    match_distance = max(match_distance, 0)
    a_matches = [False] * len(a)
    b_matches = [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len(b))
        for j in range(start, end):
            if b_matches[j] or b[j] != ca:
                continue
            a_matches[i] = b_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    # transpositions
    t = 0
    k = 0
    for i in range(len(a)):
        if not a_matches[i]:
            continue
        while not b_matches[k]:
            k += 1
        if a[i] != b[k]:
            t += 1
        k += 1
    t //= 2
    return (matches / len(a) + matches / len(b) + (matches - t) / matches) / 3.0


def jaro_winkler(a: str, b: str, *, prefix_scale: float = 0.1) -> float:
    j = jaro(a, b)
    # common prefix up to 4 chars
    prefix = 0
    for ca, cb in zip(a.lower(), b.lower()):
        if ca == cb:
            prefix += 1
            if prefix == 4:
                break
        else:
            break
    return j + prefix * prefix_scale * (1 - j)
