"""
設定ファイル: 「どこから情報を集めるか」「どのモデルを使うか」をここにまとめます。
情報源を増やしたいときは SOURCES に1行足すだけでOKです。
"""

import os

# 使用するGeminiモデル(環境変数 UVER_HUB_MODEL で上書きもできます)
MODEL_NAME = os.environ.get("UVER_HUB_MODEL", "gemini-3.8-flash")

# SQLiteデータベースの保存先
DB_PATH = "data/uver_hub.db"

# 通信するときに名乗る名前(サイト運営者に失礼がないように明示する)
USER_AGENT = "uver-hub/0.1 (personal use; RSS reader)"

# 情報源のリスト: (表示名, RSSのURL)
# まずは「Googleニュース検索のRSS」から始めるのがおすすめです。
# 理由: スクレイピングと違って、公式に提供されている形式なので安定していて安全。
SOURCES = [
    (
        "GoogleNews:UVERworld",
        "https://news.google.com/rss/search?q=UVERworld&hl=ja&gl=JP&ceid=JP:ja",
    ),
    (
        "GoogleNews:UVERworld ライブ",
        "https://news.google.com/rss/search?q=UVERworld+ライブ&hl=ja&gl=JP&ceid=JP:ja",
    ),
    # ↓ 公式サイトやYouTubeチャンネルのRSS URLが分かったら、ここに追加していく
    # ("YouTube:UVERworld", "https://www.youtube.com/feeds/videos.xml?channel_id=XXXX"),
]

# 1つの情報源につき、1回で取り込む最大件数
MAX_ENTRIES_PER_SOURCE = 30

# ----------------------------------------------------------------------------
# RAG(検索拡張生成)の設定
# ----------------------------------------------------------------------------

# 文章をベクトル(数値の並び)に変換するモデル。環境変数 UVER_HUB_EMBED_MODEL で変更可能。
# gemini-embedding-001 は task_type(文書用/質問用)の指定に対応しています。
EMBED_MODEL = os.environ.get("UVER_HUB_EMBED_MODEL", "gemini-embedding-001")

# ベクトルの次元数。小さいほど保存容量が減ります(768でも検索には十分な精度です)
EMBED_DIM = 768

# 記事本文を分割する長さ(文字数)と、前後の重なり(文字数)
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

# 質問に対して、参考資料として取り出す断片の数
TOP_K = 12

# 断片同士の類似度がこの値を超えたら「ほぼ同じ内容」とみなして、片方を除外する
# (配信元が違っても同じ原稿の記事が、検索結果を埋めないようにするため)
DUP_THRESHOLD = 0.95

# 記事の本文同士がこの割合以上重なっていたら、「同じ原稿の記事」とみなして
# ベクトル化(index)の対象から外す。(0.6 = 短いほうの6割以上が一致)
CONTENT_DUP_THRESHOLD = 0.6

# 1つの記事から、参考資料として取り出す断片の最大数(参考資料を複数の記事に分散させる)
MAX_CHUNKS_PER_ARTICLE = 3

# 本文がこの文字数より短い記事は、ベクトル化しない(写真ページなど、中身のないページ対策)
MIN_BODY_CHARS = 200

# 本文の取り出しを「精度優先」にするか。(Trueだと、メニューや関連記事の見出しが混ざりにくい
# 代わりに、本文を取れないページが増える。RAGでは、ゴミが混ざるより取れないほうがましなのでTrue)
STRICT_EXTRACTION = True

# メニューの除去: この文字数以下の短い行が、この行数以上つづいたら、メニューとみなして取り除く
NAV_SHORT_LINE_CHARS = 20
NAV_RUN_MIN_LINES = 25

# 検索の対象から外すサイト。(質が低い、中身が古いなどのサイトのドメインを書く)
# 例: EXCLUDE_DOMAINS = ["motoryokoblog.com"]
EXCLUDE_DOMAINS: list[str] = []

# 質問を言い換えて検索するときの、言い換えの最大数(元の質問とは別に数える)
MAX_QUERY_EXPANSIONS = 3


def is_excluded(url: str) -> bool:
    """URLが、EXCLUDE_DOMAINS に指定したサイトのものか。"""
    from urllib.parse import urlsplit

    host = urlsplit(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in EXCLUDE_DOMAINS)

# 記事の末尾などに付く「定型文」。ここに書いた語句を含む文は、ベクトル化の前に取り除く。
# (「メディア関係者向け」のような定型文が、質問の言葉と一致して、検索を邪魔するのを防ぐため)
# 質問と無関係な文が参考資料に出てきたら、その文の一部をここに足す。
BOILERPLATE_PHRASES = [
    "このプレスリリースには、メディア関係者向けの情報があります",
    "メディアユーザー登録を行うと",
]

# このハブの主題を表す語句。断片の「本文」にこれらが含まれていたら、検索の点数に加点する。
# (複数のアーティストが出る記事では、タイトルに名前があるだけで、他のアーティストの段落まで
#  上位に来てしまう。そこで「その断片自体が、主題に触れているか」を加点で評価する)
# 大文字・小文字は区別しない。
BOOST_TERMS = ["uverworld", "ウーバーワールド", "takuya∞", "タクヤ∞"]
BOOST_SCORE = 0.05  # 加点の大きさ(類似度は0.6〜0.8あたりに集まるので、0.05でも順位に効く)

# ----------------------------------------------------------------------------
# Geminiの「考える量」(thinking_level)。Gemini 3系は、既定が最大(high)で、遅くなりがち。
# 低いほど速く安いが、複雑な推論(例: 日付を見て、終わった出来事か今後の予定かを判断する)の
# 精度は、下がる可能性がある。 minimal / low / medium / high から選ぶ。空文字なら指定しない。
# 環境変数で上書きできる(例: $env:UVER_HUB_THINKING_ANSWER="high")
# ----------------------------------------------------------------------------
THINKING_LEVEL_EXPAND = os.environ.get("UVER_HUB_THINKING_EXPAND", "minimal")  # 質問の言い換え
THINKING_LEVEL_ANSWER = os.environ.get("UVER_HUB_THINKING_ANSWER", "low")  # 回答の生成・要約
