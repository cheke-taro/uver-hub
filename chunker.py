"""
分割モジュール: 長い記事本文を、検索しやすい長さの「断片(チャンク)」に分けます。

なぜ分けるのか:
  記事全体を1つのベクトルにすると、内容がぼやけて検索精度が落ちます。
  数百文字ごとに分けると、「どの部分に何が書いてあるか」を探せるようになります。
"""

import re


def split_text(text: str, size: int = 500, overlap: int = 80) -> list[str]:
    """本文を、文の区切り(。！？や改行)を尊重しながら、size文字前後の断片に分ける。

    overlap: 前の断片の末尾を、次の断片の頭に重ねる文字数。
             区切り目で話の流れが切れても、検索で拾えるようにするため。
    """
    # まず「。」「！」「？」や改行で、文に分ける
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])|\n+", text) if s and s.strip()]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        # 1文がsizeより長い場合は、そのままsize文字ごとに切る
        if len(sentence) > size:
            if current.strip():
                chunks.append(current)
                current = ""
            chunks.extend(sentence[i : i + size] for i in range(0, len(sentence), size))
            continue

        if current and len(current) + len(sentence) > size:
            chunks.append(current)
            tail = current[-overlap:] if overlap > 0 else ""  # 末尾を次に引き継ぐ
            current = tail + sentence
        else:
            current += sentence

    if current.strip():
        chunks.append(current)
    return chunks


def strip_boilerplate(text: str, phrases: list[str]) -> str:
    """指定した語句を含む「文」を取り除く。(定型文の除去用)

    行を文(。！？の区切り)に分けて、語句を含む文だけを捨てる。
    1行まるごと定型文なら、その行も消える。
    """
    if not phrases:
        return text
    kept_lines = []
    for line in text.split("\n"):
        sentences = re.split(r"(?<=[。！？!?])", line)
        kept = "".join(s for s in sentences if not any(p in s for p in phrases)).strip()
        if kept:
            kept_lines.append(kept)
    return "\n".join(kept_lines)
