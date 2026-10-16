"""
重複判定モジュール: 「同じ原稿を載せた記事」を、本文の文字列の重なり具合で見つけます。

配信元が違っても、通信社などの同じ原稿を載せている記事は多くあります。
断片のベクトルで比べると区切り位置のずれで見逃すため、本文そのものを比べます。

やり方:
  本文を「5文字ずつずらした文字列(シングル)」の集まりにして、
  片方の集まりが、もう片方にどれだけ含まれているかを調べます。
  (短い版が、長い版の一部だけの場合も、検出できるようにするため)
"""

import re


def shingles(text: str, n: int = 5) -> set[str]:
    """本文を、n文字ずつずらした文字列の集合にする。(空白は無視する)"""
    t = re.sub(r"\s+", "", text)
    if len(t) < n:
        return {t} if t else set()
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def containment(a: set[str], b: set[str]) -> float:
    """小さいほうの集合のうち、何割が相手にも含まれているか。(0〜1)"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def find_duplicate(body: str, refs: list, threshold: float):
    """すでに登録した記事の中に、ほぼ同じ本文があれば (タイトル, 重なり率) を返す。

    refs: [(タイトル, shinglesの集合), ...]
    """
    target = shingles(body)
    for title, ref in refs:
        score = containment(target, ref)
        if score >= threshold:
            return title, score
    return None
