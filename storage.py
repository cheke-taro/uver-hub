"""
保存モジュール: 集めた記事をSQLite(ファイル1つで動くDB)に貯めます。
URLをUNIQUEにしているので、同じ記事を何度集めても重複しません。

【RAGへの布石】
今は articles テーブルだけですが、ステップ2では
  chunks テーブル(記事を分割した断片 + ベクトル)
を追加して、検索できるようにします。
"""

import sqlite3
from pathlib import Path

import config
from collector import Article


def get_connection() -> sqlite3.Connection:
    """DBに接続する。テーブルがなければ自動で作る。"""
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row  # 列名でアクセスできるようにする
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,   -- 重複防止のキー
            published TEXT,
            content TEXT,
            summary TEXT,               -- Geminiの3行要約(未要約ならNULL)
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def save_articles(conn: sqlite3.Connection, articles: list[Article]) -> int:
    """記事を保存する。すでに保存済みのURLは無視して、新規に追加できた件数を返す。"""
    added = 0
    for a in articles:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO articles (source, title, url, published, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (a.source, a.title, a.url, a.published, a.content),
        )
        added += cur.rowcount  # 追加されたら1、重複で無視されたら0
    conn.commit()
    return added


def get_recent(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    """新しい順に記事を取り出す。"""
    return conn.execute(
        """
        SELECT * FROM articles
        ORDER BY COALESCE(published, fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def get_unsummarized(conn: sqlite3.Connection, limit: int = 5) -> list[sqlite3.Row]:
    """まだ要約していない記事を取り出す。"""
    return conn.execute(
        """
        SELECT * FROM articles
        WHERE summary IS NULL
        ORDER BY COALESCE(published, fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def save_summary(conn: sqlite3.Connection, article_id: int, summary: str) -> None:
    """要約結果を記事に紐づけて保存する。"""
    conn.execute("UPDATE articles SET summary = ? WHERE id = ?", (summary, article_id))
    conn.commit()
