"""
保存モジュール: 集めた記事をSQLite(ファイル1つで動くDB)に貯めます。
URLをUNIQUEにしているので、同じ記事を何度集めても重複しません。

【RAGへの布石】
ステップ2では、body(本文)を分割して chunks テーブルに入れ、検索できるようにします。
"""

import sqlite3
from array import array
from pathlib import Path

import config
from collector import Article

# 後から追加した列。既存のDBにも自動で足す(マイグレーション)ために一覧にしておく
EXTRA_COLUMNS = {
    "body": "TEXT",  # 取得した記事本文
    "body_status": "TEXT",  # 本文取得の結果: ok / failed (未取得ならNULL)
    "real_url": "TEXT",  # GoogleニュースのURLから割り出した、元記事のURL
}


def get_connection() -> sqlite3.Connection:
    """DBに接続する。テーブルがなければ自動で作り、足りない列があれば追加する。"""
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
    # 既存のDBに、本文関連の列がなければ追加する
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
    for column, col_type in EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {column} {col_type}")
    # RAG用: 記事を分割した断片(チャンク)と、そのベクトルを保存するテーブル
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL REFERENCES articles(id),
            chunk_index INTEGER NOT NULL,   -- 記事の中で何番目の断片か
            text TEXT NOT NULL,             -- 断片の本文
            embedding BLOB NOT NULL,        -- ベクトル(float32の並びをバイト列で保存)
            model TEXT NOT NULL             -- ベクトル化に使ったモデル名
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_article ON chunks(article_id)")
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


def get_unfetched(conn: sqlite3.Connection, limit: int = 5) -> list[sqlite3.Row]:
    """まだ本文を取得していない記事を取り出す。(失敗済みのものは再試行しない)"""
    return conn.execute(
        """
        SELECT * FROM articles
        WHERE body_status IS NULL
        ORDER BY COALESCE(published, fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def save_body(
    conn: sqlite3.Connection,
    article_id: int,
    body: str | None,
    real_url: str | None,
) -> str:
    """本文の取得結果を保存し、記録した状態(ok / failed / duplicate)を返す。

    すでに同じ元記事URLの本文を保存済みなら、重複(duplicate)として記録して、
    本文は保存しない。(配信元が違っても、元記事が同じなら1件だけ使うため)
    """
    status = "ok" if body else "failed"
    if body and real_url:
        same = conn.execute(
            "SELECT id FROM articles WHERE real_url = ? AND body_status = 'ok' AND id != ?",
            (real_url, article_id),
        ).fetchone()
        if same:
            status, body = "duplicate", None
    conn.execute(
        "UPDATE articles SET body = ?, body_status = ?, real_url = ? WHERE id = ?",
        (body, status, real_url, article_id),
    )
    conn.commit()
    return status


def reset_failed(conn: sqlite3.Connection) -> int:
    """本文取得に失敗した記事を「未取得」に戻して、再試行できるようにする。"""
    cur = conn.execute(
        "UPDATE articles SET body_status = NULL WHERE body_status = 'failed'"
    )
    conn.commit()
    return cur.rowcount


def get_unsummarized(conn: sqlite3.Connection, limit: int = 5) -> list[sqlite3.Row]:
    """まだ要約していない記事を取り出す。"""
    return conn.execute(
        """
        SELECT * FROM articles
        WHERE summary IS NULL AND COALESCE(body_status, '') != 'duplicate'
        ORDER BY COALESCE(published, fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def save_summary(conn: sqlite3.Connection, article_id: int, summary: str) -> None:
    """要約結果を記事に紐づけて保存する。"""
    conn.execute("UPDATE articles SET summary = ? WHERE id = ?", (summary, article_id))
    conn.commit()


# ----------------------------------------------------------------------------
# RAG用: 断片(チャンク)の保存と取得
# ----------------------------------------------------------------------------


def get_unindexed(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """本文があるのに、まだ断片に分けてベクトル化していない記事を取り出す。"""
    return conn.execute(
        """
        SELECT a.* FROM articles a
        WHERE a.body_status = 'ok'
          AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.article_id = a.id)
        ORDER BY COALESCE(a.published, a.fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def save_chunks(
    conn: sqlite3.Connection,
    article_id: int,
    texts: list[str],
    vectors: list[list[float]],
    model: str,
) -> None:
    """記事1件分の断片とベクトルを保存する。"""
    for i, (text, vec) in enumerate(zip(texts, vectors)):
        blob = array("f", vec).tobytes()  # 数値の並びを、DBに入れられるバイト列にする
        conn.execute(
            "INSERT INTO chunks (article_id, chunk_index, text, embedding, model) "
            "VALUES (?, ?, ?, ?, ?)",
            (article_id, i, text, blob, model),
        )
    conn.commit()


def get_all_chunks(conn: sqlite3.Connection, model: str) -> list[sqlite3.Row]:
    """指定モデルでベクトル化した全断片を、記事の情報つきで取り出す。"""
    return conn.execute(
        """
        SELECT c.id, c.text, c.embedding, a.title, a.published,
               COALESCE(a.real_url, a.url) AS link
        FROM chunks c JOIN articles a ON a.id = c.article_id
        WHERE c.model = ?
        """,
        (model,),
    ).fetchall()


def count_chunks(conn: sqlite3.Connection) -> int:
    """保存済みの断片の数。"""
    return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]


def get_indexed_articles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """すでにベクトル化済みの記事(重複判定の比較対象)を取り出す。"""
    return conn.execute(
        """
        SELECT a.id, a.title, a.body FROM articles a
        WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.article_id = a.id)
        """
    ).fetchall()


def mark_status(conn: sqlite3.Connection, article_id: int, status: str) -> None:
    """記事の状態を記録する。(本文は残す)  status: duplicate(重複) / short(本文が短すぎる)"""
    conn.execute("UPDATE articles SET body_status = ? WHERE id = ?", (status, article_id))
    conn.commit()


def mark_duplicate(conn: sqlite3.Connection, article_id: int) -> None:
    """本文が他の記事とほぼ同じ記事を、重複として記録する。"""
    mark_status(conn, article_id, "duplicate")


def reset_index(conn: sqlite3.Connection) -> None:
    """ベクトル化の結果を全部消して、最初からやり直せる状態に戻す。

    本文の重複判定で duplicate にした記事も、本文が残っていれば ok に戻す。
    (URLが同じことによる重複は、本文を保存していないので、duplicateのまま)
    """
    conn.execute("DELETE FROM chunks")
    conn.execute(
        "UPDATE articles SET body_status = 'ok' "
        "WHERE body_status IN ('duplicate', 'short') AND body IS NOT NULL"
    )
    conn.commit()


def search_articles(conn: sqlite3.Connection, keyword: str, limit: int = 5) -> list[sqlite3.Row]:
    """タイトルにキーワードを含む記事を探す。(本文の中身の確認用)"""
    return conn.execute(
        "SELECT * FROM articles WHERE title LIKE ? "
        "ORDER BY COALESCE(published, fetched_at) DESC LIMIT ?",
        (f"%{keyword}%", limit),
    ).fetchall()


def get_stats(conn: sqlite3.Connection) -> dict:
    """検索の対象になっている記事数・断片数と、最後に収集した日時(日本時間)を返す。"""
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(DISTINCT article_id) FROM chunks) AS articles,
            (SELECT COUNT(*) FROM chunks) AS chunks,
            (SELECT datetime(MAX(fetched_at), '+9 hours') FROM articles) AS last_fetched
        """
    ).fetchone()
    return {"articles": row["articles"], "chunks": row["chunks"], "last_fetched": row["last_fetched"]}
