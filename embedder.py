"""
埋め込みモジュール: 文章をGeminiでベクトル(数値の並び)に変換します。

意味が近い文章は、近いベクトルになります。この性質を使って
「質問に意味が近い断片」を探すのが、RAGの検索の仕組みです。
"""

import math
import time

from google import genai
from google.genai import types

import config
from llm import call_with_retry

BATCH_SIZE = 50  # 1回のリクエストで変換する文章の数


def _normalize(vec: list[float]) -> list[float]:
    """ベクトルの長さを1にそろえる。(そうすると、内積がそのまま類似度(コサイン類似度)になる)"""
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def embed_texts(texts: list[str], task_type: str) -> list[list[float]]:
    """文章のリストをベクトルのリストに変換する。

    task_type:
      "RETRIEVAL_DOCUMENT" ... 検索される側(記事の断片)を変換するとき
      "RETRIEVAL_QUERY"    ... 検索する側(ユーザーの質問)を変換するとき
    """
    client = genai.Client()  # APIキーは環境変数 GEMINI_API_KEY から自動で読み込まれる
    vectors: list[list[float]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        result = call_with_retry(  # 混雑時は自動で再試行する
            lambda batch=batch: client.models.embed_content(
                model=config.EMBED_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=config.EMBED_DIM,
                ),
            )
        )
        # 次元数を減らしたときは、長さを1にそろえ直す必要がある
        vectors.extend(_normalize(list(e.values)) for e in result.embeddings)
        if i + BATCH_SIZE < len(texts):
            time.sleep(1)  # リクエストが続くときは、少し間をあける
    return vectors
