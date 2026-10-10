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
