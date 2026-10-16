"""
本文取得モジュール: 記事のURLから、本文テキストを取り出します。

流れ:
  1) GoogleニュースのURL(news.google.com/...)を、元の記事のURLに変換する
  2) 元の記事のページを取得して、広告やメニューを除いた本文だけを抽出する(trafilatura)

【注意】
- 個人利用の範囲で、少ない件数をゆっくり取得する前提です(1件ごとに待ち時間を入れています)
- 取得した本文は、公開・再配布しないでください(data/ をGit管理から外しているのもそのためです)
- googlenewsdecoder は非公式のライブラリです。Google側の仕様変更で動かなくなることがあります
"""

import re
import sys
import types
from typing import Optional

import trafilatura

import config

# --- selectolax 1.0 対応の互換処理 -------------------------------------------
# googlenewsdecoder は内部で `from selectolax.parser import HTMLParser` を使っていますが、
# selectolax 1.0 以降では、この古い読み込み先(Modest)が廃止され、エラーになります。
# そこで、googlenewsdecoder を読み込む前に「古い名前で呼ばれたら、新しい方式(lexbor)を
# 返す」代役を差し込みます。selectolax の古い版が入っていて問題ない場合は、何もしません。
try:
    import selectolax.parser  # noqa: F401  (古い方式がそのまま使えるなら、何もしない)
except ImportError:
    try:
        from selectolax import lexbor as _lexbor

        _shim = types.ModuleType("selectolax.parser")
        _shim.HTMLParser = _lexbor.LexborHTMLParser
        _shim.Node = _lexbor.LexborNode
        sys.modules["selectolax.parser"] = _shim
    except ImportError:
        pass  # selectolax 自体が入っていない場合は、下の import で通常のエラーを出す
# ------------------------------------------------------------------------------

from googlenewsdecoder import gnewsdecoder  # noqa: E402  (上の互換処理の後に読み込む)


def normalize_url(url: str) -> str:
    """変換後のURLに混ざる余計な部分を取り除いて、記事そのもののURLに整える。"""
    # Yahoo!ニュース: 画像ページ(.../articles/xxxx/images/000)を、記事ページに戻す
    if "news.yahoo.co.jp/articles/" in url and "/images/" in url:
        url = url.split("/images/")[0]
    # 写真ギャラリーのページ(.../photo/3/ など)を、記事ページに戻す(オリコンなど)
    url = re.sub(r"/photo/\d+/?$", "/", url)
    # URLの検索部分(?以降)にHTMLの断片が混ざっているときは、?以降を捨てる
    if "<" in url or "%3C" in url.upper():
        url = url.split("?")[0]
    return url


def resolve_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """GoogleニュースのURLなら元の記事URLに変換する。それ以外のURLはそのまま返す。

    戻り値: (元記事のURL, 失敗理由)  成功なら失敗理由はNone
    """
    if "news.google.com" not in url:
        return url, None
    result = gnewsdecoder(url, interval=1)  # interval: 連続アクセスの間隔(秒)

    # ライブラリの版によって、成功判定の項目名が違う("status" か "success")ため、
    # 項目名ではなく「変換後のURLが入っているか」で判定する
    decoded = result.get("decoded_url") if isinstance(result, dict) else None
    if decoded:
        return decoded, None

    # 失敗したときは、ライブラリが返したメッセージ(なければ結果そのもの)を理由として返す
    detail = result.get("message") if isinstance(result, dict) else None
    return None, f"URL変換に失敗: {detail or result}"


def clean_body(text: str) -> str:
    """メニューのような「短い行の長い連続」を取り除く。

    サイトのメニュー(「記事一覧」「ログイン」…)は、短い行が何十行も続きます。
    記事の本文は、まとまった長さの段落なので、この形にはなりません。
    (曲名が数行並ぶ程度のセットリストは、短い行の連続でも、基準に届かないので残ります)
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    kept: list[str] = []
    run: list[str] = []  # 短い行の連続を、いったんここに溜める

    def flush() -> None:
        if len(run) < config.NAV_RUN_MIN_LINES:
            kept.extend(run)  # 連続が短ければ、普通の文章なので残す
        run.clear()

    for line in lines:
        if len(line) <= config.NAV_SHORT_LINE_CHARS:
            run.append(line)
        else:
            flush()
            kept.append(line)
    flush()
    return "\n".join(kept).strip()


def fetch_body(url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """記事URLから本文を取得する。

    戻り値: (本文テキスト, 元記事のURL, 失敗理由)
      - 成功 -> (本文, 元記事のURL, None)
      - 失敗 -> (None, 元記事のURL(分かれば), 失敗理由の説明)
    """
    real_url, reason = resolve_url(url)
    if not real_url:
        return None, None, reason
    real_url = normalize_url(real_url)
    if config.is_excluded(real_url):
        return None, real_url, "除外設定(EXCLUDE_DOMAINS)のサイトのため、取得しません"

    html = trafilatura.fetch_url(real_url)
    if not html:
        return None, real_url, "ページを取得できませんでした(サイト側が拒否した可能性があります)"

    # コメント欄や表は除いて、本文だけを取り出す
    # 精度優先(STRICT_EXTRACTION)では、本文と確信できないときは、無理に取り出さない
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_precision=config.STRICT_EXTRACTION,
        no_fallback=config.STRICT_EXTRACTION,
    )
    text = clean_body(text) if text else None
    if not text:
        return None, real_url, "ページは取得できましたが、本文を抽出できませんでした(本文以外しか取れなかった可能性があります)"
    return text, real_url, None
