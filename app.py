"""
app.py: uver-hub のニュースまとめサイト画面

使い方:
    python app.py
    ブラウザで http://127.0.0.1:5000 を開く
"""

import os
import sys

from flask import Flask, render_template_string, request

import storage

app = Flask(__name__)

# ---------------------------------------------------------------------------
# 画面テンプレート (ニュース一覧表示)
# ---------------------------------------------------------------------------
PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>uver-hub - ニュースまとめ</title>
<style>
  :root { --bg:#fafafa; --fg:#222; --muted:#666; --card:#fff; --line:#ddd; --accent:#1a56db; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16181d; --fg:#e8e8e8; --muted:#9aa0a6; --card:#20232a; --line:#333842; --accent:#6ea8fe; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); line-height:1.7;
         font-family:-apple-system,"Hiragino Sans","Yu Gothic",Meiryo,sans-serif; }
  main { max-width:800px; margin:0 auto; padding:24px 16px 48px; }
  h1 { font-size:1.6rem; margin:0 0 4px; }
  .sub { color:var(--muted); font-size:.95rem; margin:0 0 24px; }
  
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:20px; margin-bottom:16px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); }
  .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 0.85rem; color: var(--muted); }
  .source-tag { background: var(--line); padding: 2px 8px; border-radius: 4px; font-weight: 500; }
  
  .card h2 { font-size: 1.15rem; margin: 0 0 10px; line-height: 1.4; }
  .card h2 a { color: var(--fg); text-decoration: none; }
  .card h2 a:hover { color: var(--accent); text-decoration: underline; }
  
  .summary { font-size: 0.95rem; color: var(--fg); margin: 8px 0; white-space: pre-wrap; }
  .empty { text-align: center; color: var(--muted); padding: 40px 0; }
  
  footer { color: var(--muted); font-size: 0.8rem; margin-top: 32px; text-align: center; border-top: 1px solid var(--line); padding-top: 16px; }
</style>
</head>
<body>
<main>
  <h1>uver-hub</h1>
  <p class="sub">UVERworldに関する最新ニュース・情報のまとめ</p>

  {% if articles %}
    {% for a in articles %}
    <div class="card">
      <div class="card-header">
        <span class="source-tag">{{ a.source }}</span>
        <span>{{ (a.published or a.fetched_at)[:10] }}</span>
      </div>
      <h2><a href="{{ a.real_url or a.url }}" target="_blank" rel="noopener noreferrer">{{ a.title }}</a></h2>
      {% if a.summary %}
        <div class="summary">{{ a.summary }}</div>
      {% elif a.content %}
        <div class="summary" style="color: var(--muted);">{{ a.content[:150] }}...</div>
      {% endif %}
    </div>
    {% endfor %}
  else:
    <div class="card empty">
      <p>まだ記事が蓄積されていません。</p>
      <p style="font-size: 0.85rem; margin-top: 8px;">データ収集スクリプトを実行して記事を取り込んでください。</p>
    </div>
  {% endif %}

  <footer>
    {% if stats.articles %}
      登録記事数: {{ stats.articles }}件 / 最終データ更新: {{ stats.last_fetched }} (日本時間)
    {% else %}
      データがありません
    {% endif %}
  </footer>
</main>
</body>
</html>
"""

@app.route("/")
def index():
    """蓄積されたニュースの一覧を表示する"""
    conn = storage.get_connection()
    try:
        # 新しい順に最大30件の記事を取得
        articles = storage.get_recent(conn, limit=30)
        stats = storage.get_stats(conn)
    finally:
        conn.close()

    ctx = {
        "articles": articles,
        "stats": stats,
    }
    return render_template_string(PAGE, **ctx)


if __name__ == "__main__":
    host = os.environ.get("UVER_HUB_HOST", "127.0.0.1")
    port = int(os.environ.get("UVER_HUB_PORT", "5000"))
    
    app.run(host=host, port=port, debug=False)