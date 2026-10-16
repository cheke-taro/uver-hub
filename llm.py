"""
Gemini呼び出しの共通処理: 混雑などの一時的なエラーのとき、待ってから自動で再試行します。

Geminiは、アクセスが集中すると「503 UNAVAILABLE」を返すことがあります。
これは数十秒〜数分で解消することが多いので、すぐ諦めずに、間隔をあけて数回やり直します。
"""

import time

from google import genai
from google.genai import errors, types

import config

# 再試行する価値のあるエラー番号(混雑・一時的な障害・利用回数の一時的な上限)
RETRY_CODES = {429, 500, 502, 503, 504}

# 再試行までの待ち時間(秒)。この回数だけ再試行して、それでもだめなら諦める
WAIT_SECONDS = [3, 8, 20, 40]


class GeminiUnavailable(Exception):
    """再試行しても、Geminiが使えなかったときのエラー。"""


def call_with_retry(func):
    """func() を実行する。一時的なエラーなら、待って再試行する。"""
    for attempt, wait in enumerate(WAIT_SECONDS + [None]):
        try:
            return func()
        except errors.APIError as e:
            code = getattr(e, "code", None)
            if code not in RETRY_CODES:
                raise  # 再試行しても直らないエラー(キーの間違いなど)は、そのまま出す
            if wait is None:
                raise GeminiUnavailable(
                    f"Geminiが混み合っているか、一時的に使えません(エラー{code})。"
                    "しばらくしてから、もう一度実行してください。"
                ) from e
            print(f"  [Geminiが混み合っています(エラー{code})] {wait}秒待って再試行します"
                  f"({attempt + 1}/{len(WAIT_SECONDS)})")
            time.sleep(wait)


def _build_config(thinking_level: str | None):
    """「考える量」の設定を作る。作れない場合(SDKが古いなど)は None を返す。"""
    if not thinking_level:
        return None
    try:
        # 列挙型(ThinkingLevel.LOW など)があればそれを使い、なければ文字列のまま渡す
        level = getattr(types.ThinkingLevel, thinking_level.upper(), thinking_level)
        return types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=level))
    except Exception:
        print("[注意] このSDKでは thinking_level を指定できないため、指定なしで実行します")
        return None


def generate_text(prompt: str, thinking_level: str | None = None) -> str:
    """プロンプトをGeminiに送り、返ってきた文章を返す。(混雑時は自動で再試行)

    thinking_level: 考える量。低いほど速い。モデルが対応していない場合は、指定なしでやり直す。
    """
    client = genai.Client()

    def call(cfg):
        kwargs = {"config": cfg} if cfg is not None else {}
        return call_with_retry(
            lambda: client.models.generate_content(model=config.MODEL_NAME, contents=prompt, **kwargs)
        )

    cfg = _build_config(thinking_level)
    try:
        response = call(cfg)
    except errors.APIError as e:
        if cfg is not None and getattr(e, "code", None) == 400:
            # このモデルは thinking_level に対応していない可能性がある。指定なしでやり直す
            print(f"[注意] thinking_level='{thinking_level}' が受け付けられなかったため、指定なしで再実行します")
            response = call(None)
        else:
            raise
    return (response.text or "").strip()
