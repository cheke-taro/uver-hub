"""
uver-hub: UVERworld情報収集ハブ(コマンドラインから操作します)

使い方:
    python main.py demo         # サンプル要約テスト
    python main.py collect      # RSSから記事を集めてDBに保存
    python main.py fetch        # 記事の本文を取得してDBに保存
    python main.py summarize    # 未要約の記事をGeminiで3行要約してDBに保存
    python main.py list         # 保存済みの記事を新しい順に表示
    python main.py index        # 本文を断片に分けてベクトル化(RAGの下ごしらえ)
    python main.py ask "質問"   # 保存した記事を根拠に、質問に答える(RAG)
    python main.py update       # collect -> fetch -> index をまとめて実行(定期実行用)
    python main.py show "語句"  # タイトルに語句を含む記事の保存状態と本文の冒頭を確認

普段の使い方: update でデータを最新にして、ask で質問する。(summarize は任意)
"""

import argparse
import os
import sys
import time

import collector
import storage
from llm import GeminiUnavailable

SAMPLE_TEXT = """
【サンプル記事】あるバンドが、全国ツアーの追加公演を発表した。
追加されるのは東京と大阪の2会場で、チケットは来月から先行受付が始まる。
最新アルバムの収録曲に加えて、ファン人気の高い過去の代表曲も披露される予定だという。
""".strip()

# Geminiに渡す本文の最大文字数(長すぎる記事は先頭だけ使う)
MAX_BODY_CHARS = 6000


def require_api_key() -> None:
    """Geminiを使うコマンドの前に、APIキーがあるかチェックする。"""
    if not os.environ.get("GEMINI_API_KEY"):
        print("エラー: 環境変数 GEMINI_API_KEY が設定されていません。")
        sys.exit(1)


def cmd_demo(args) -> None:
    """サンプルテキストの要約テスト。"""
    require_api_key()
    from summarizer import summarize_for_fan  # 使うときだけ読み込む

    print(summarize_for_fan(SAMPLE_TEXT))


def cmd_collect(args) -> None:
    """全情報源から記事を集めてDBに保存する。"""
    articles = collector.collect_all()
    conn = storage.get_connection()
    added = storage.save_articles(conn, articles)
    print(f"\n完了: 取得{len(articles)}件 / 新規保存{added}件(残りは重複)")


def cmd_fetch(args) -> None:
    """本文が未取得の記事について、本文を取得してDBに保存する。"""
    from fetcher import fetch_body  # 使うときだけ読み込む

    conn = storage.get_connection()
    if args.retry:
        n = storage.reset_failed(conn)
        print(f"取得に失敗していた{n}件を、再試行の対象に戻しました。")
    rows = storage.get_unfetched(conn, limit=args.limit)
    if not rows:
        print("本文が未取得の記事はありません。")
        return

    ok = 0
    for r in rows:
        print(f"本文取得中: {r['title']}")
        try:
            body, real_url, reason = fetch_body(r["url"])
        except Exception as e:
            body, real_url, reason = None, None, f"予期しないエラー: {type(e).__name__}: {e}"
        status = storage.save_body(conn, r["id"], body, real_url)
        if status == "duplicate":
            print(f"  -> 重複(同じ元記事を取得済みのためスキップ) {real_url}")
        elif body:
            ok += 1
            print(f"  -> OK ({len(body)}文字) {real_url}")
        else:
            print(f"  -> 取得できませんでした: {reason}")
            if real_url:
                print(f"     元記事: {real_url}")
        time.sleep(2)  # 相手のサーバーに負担をかけないよう、2秒あける
    print(f"\n完了: {len(rows)}件中 {ok}件で本文を取得")


def cmd_list(args) -> None:
    """保存済みの記事を表示する。"""
    conn = storage.get_connection()
    rows = storage.get_recent(conn, limit=args.limit)
    if not rows:
        print("記事がありません。先に `python main.py collect` を実行してください。")
        return
    for r in rows:
        body_mark = {
            "ok": "本文あり",
            "failed": "本文なし(取得失敗)",
            "duplicate": "重複(別の記事と本文がほぼ同じ)",
            "short": "本文が短すぎる",
        }.get(
            r["body_status"], "本文未取得"
        )
        print(f"[{r['published'] or '日時不明'}] {r['title']}  ({body_mark})")
        print(f"  {r['real_url'] or r['url']}")
        if r["summary"]:
            print("  " + r["summary"].replace("\n", "\n  "))
        print()


def cmd_summarize(args) -> None:
    """未要約の記事をGeminiで要約して、結果をDBに保存する。"""
    require_api_key()
    from summarizer import summarize_for_fan

    conn = storage.get_connection()
    rows = storage.get_unsummarized(conn, limit=args.limit)
    if not rows:
        print("未要約の記事はありません。")
        return

    for r in rows:
        print(f"要約中: {r['title']}")
        # 本文があれば本文を使い、なければRSSの概要を使う
        material = r["body"] or r["content"] or ""
        text = f"{r['title']}\n{material[:MAX_BODY_CHARS]}"
        try:
            summary = summarize_for_fan(text)
        except Exception as e:
            print(f"  [警告] 要約に失敗しました: {e}")
            continue
        storage.save_summary(conn, r["id"], summary)
        print("  " + summary.replace("\n", "\n  "))


def cmd_index(args) -> None:
    """本文を断片に分けてベクトル化し、DBに保存する。(RAGの下ごしらえ)"""
    require_api_key()
    import config
    import dedupe
    from chunker import split_text, strip_boilerplate
    from embedder import embed_texts

    def clean(body: str) -> str:
        return strip_boilerplate(body, config.BOILERPLATE_PHRASES)  # 定型文を取り除く

    conn = storage.get_connection()
    if args.rebuild:
        storage.reset_index(conn)
        print("ベクトル化の結果を消して、最初からやり直します。")

    # --limit を指定しなかったとき: 通常は20記事まで。--rebuild(全部やり直し)のときは上限なし
    limit = args.limit if args.limit is not None else (100000 if args.rebuild else 20)
    rows = storage.get_unindexed(conn, limit=limit)
    if not rows:
        print("ベクトル化が必要な記事はありません。")
        print(f"(保存済みの断片: {storage.count_chunks(conn)}件)")
        return

    # 重複判定の比較対象: すでにベクトル化済みの記事
    refs = [(a["title"], dedupe.shingles(clean(a["body"]))) for a in storage.get_indexed_articles(conn)]

    # 定型文を取り除いた本文で、以降の処理をする。長い記事を先に処理する。
    # (途中までしか取れていない短い版が、重複として落ちるように)
    bodies = {r["id"]: clean(r["body"]) for r in rows}
    rows = sorted(rows, key=lambda r: len(bodies[r["id"]]), reverse=True)

    for r in rows:
        body = bodies[r["id"]]
        if len(body) < config.MIN_BODY_CHARS:
            storage.mark_status(conn, r["id"], "short")
            print(f"本文が短すぎるためスキップ({len(body)}文字): {r['title']}")
            continue
        dup = dedupe.find_duplicate(body, refs, config.CONTENT_DUP_THRESHOLD)
        if dup:
            storage.mark_duplicate(conn, r["id"])
            print(f"重複のためスキップ: {r['title']}")
            print(f"  (「{dup[0][:30]}...」と本文が{dup[1]:.0%}一致)")
            continue

        chunks = split_text(body, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
        print(f"ベクトル化中: {r['title']} ({len(chunks)}断片)")
        # タイトルを頭に付けてベクトル化すると、「何の記事の断片か」が検索に効く
        vectors = embed_texts([f"{r['title']}\n{c}" for c in chunks], "RETRIEVAL_DOCUMENT")
        storage.save_chunks(conn, r["id"], chunks, vectors, config.EMBED_MODEL)
        refs.append((r["title"], dedupe.shingles(body)))
    print(f"\n完了: 保存済みの断片は合計{storage.count_chunks(conn)}件")


def cmd_ask(args) -> None:
    """保存した記事を根拠に、質問に答える。(RAG)"""
    require_api_key()
    from rag import answer_question

    conn = storage.get_connection()
    if storage.count_chunks(conn) == 0:
        print("検索できるデータがありません。先に `python main.py index` を実行してください。")
        return

    answer, hits, queries, timings = answer_question(conn, args.question, k=args.k)
    print("検索に使ったキーワード: " + " / ".join(queries) + "\n")
    if answer is None:
        print("関連する資料が見つかりませんでした。")
        return

    if args.context:
        print("=== 取得した断片(回答の根拠の確認用) ===")
        for n, (score, row) in enumerate(hits, start=1):
            preview = row["text"].replace("\n", " ")[: args.context_chars]
            print(f"[{n}] ({row['title'][:30]}...) {preview}...")
        print()

    print("=== 回答 ===")
    print(answer)
    print("\n処理時間: " + " / ".join(f"{k} {v:.1f}秒" for k, v in timings.items()))
    print("\n=== 参考にした資料 ===")
    first_seen = {}  # 記事のURL -> 最初に出てきた番号
    for n, (score, row) in enumerate(hits, start=1):
        if row["link"] in first_seen:
            print(f"[{n}] (類似度 {score:.2f}) [{first_seen[row['link']]}] と同じ記事の別の箇所")
            continue
        first_seen[row["link"]] = n
        date = (row["published"] or "日時不明")[:10]
        print(f"[{n}] (類似度 {score:.2f}) {row['title']} ({date})")
        print(f"    {row['link']}")


def cmd_show(args) -> None:
    """タイトルにキーワードを含む記事の、保存状態と本文の冒頭を表示する。(確認用)"""
    rows = storage.search_articles(storage.get_connection(), args.keyword, limit=args.limit)
    if not rows:
        print("該当する記事がありません。")
        return
    for r in rows:
        body = r["body"] or ""
        print(f"[id={r['id']}] {r['title']}")
        print(f"  状態: {r['body_status']} / 本文{len(body)}文字 / {r['real_url'] or r['url']}")
        if body:
            print("  --- 本文の冒頭 ---")
            print("  " + body[: args.chars].replace("\n", "\n  "))
        print()


def cmd_update(args) -> None:
    """収集 -> 本文取得 -> ベクトル化を、まとめて実行する。(定期実行用)

    1つのステップが失敗しても、残りのステップは続けて実行する。
    (例: 収集に失敗しても、すでに保存済みの記事の本文取得とベクトル化は進められるため)
    """
    require_api_key()  # ベクトル化で必要なので、最初に確認する

    steps = [
        ("収集 (collect)", cmd_collect, argparse.Namespace()),
        ("本文取得 (fetch)", cmd_fetch, argparse.Namespace(limit=args.fetch_limit, retry=False)),
        ("ベクトル化 (index)", cmd_index, argparse.Namespace(limit=args.index_limit, rebuild=False)),
    ]
    if args.summarize > 0:
        steps.append(("要約 (summarize)", cmd_summarize, argparse.Namespace(limit=args.summarize)))

    failed = []
    for name, func, ns in steps:
        print(f"\n===== {name} =====")
        try:
            func(ns)
        except Exception as e:
            print(f"[エラー] {name} に失敗しました: {type(e).__name__}: {e}")
            failed.append(name)

    print("\n===== update 完了 =====")
    if failed:
        print("失敗したステップ: " + ", ".join(failed))
        sys.exit(1)  # 自動実行したときに、失敗に気づけるよう、異常終了にする


def main() -> None:
    parser = argparse.ArgumentParser(description="uver-hub")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="サンプル要約テスト").set_defaults(func=cmd_demo)
    sub.add_parser("collect", help="記事を収集").set_defaults(func=cmd_collect)

    p_fetch = sub.add_parser("fetch", help="記事の本文を取得")
    p_fetch.add_argument("--limit", type=int, default=5, help="1回で取得する件数")
    p_fetch.add_argument(
        "--retry", action="store_true", help="取得に失敗した記事も、もう一度試す"
    )
    p_fetch.set_defaults(func=cmd_fetch)

    p_list = sub.add_parser("list", help="記事一覧")
    p_list.add_argument("--limit", type=int, default=10, help="表示件数")
    p_list.set_defaults(func=cmd_list)

    p_sum = sub.add_parser("summarize", help="未要約の記事を要約")
    p_sum.add_argument("--limit", type=int, default=5, help="1回で要約する件数")
    p_sum.set_defaults(func=cmd_summarize)

    p_idx = sub.add_parser("index", help="本文をベクトル化して検索できるようにする")
    p_idx.add_argument(
        "--limit", type=int, default=None, help="1回でベクトル化する記事数(省略時は20。--rebuild時は全部)"
    )
    p_idx.add_argument(
        "--rebuild", action="store_true", help="ベクトル化の結果を消して、最初からやり直す"
    )
    p_idx.set_defaults(func=cmd_index)

    p_ask = sub.add_parser("ask", help="保存した記事を根拠に質問に答える")
    p_ask.add_argument("question", help="質問文(引用符で囲む)")
    p_ask.add_argument("--k", type=int, default=None, help="参考にする断片の数(省略時は config.py の TOP_K)")
    p_ask.add_argument("--context", action="store_true", help="取得した断片の中身も表示する")
    p_ask.add_argument(
        "--context-chars", type=int, default=200, help="--context で表示する、断片ごとの文字数"
    )
    p_ask.set_defaults(func=cmd_ask)

    p_upd = sub.add_parser("update", help="収集・本文取得・ベクトル化をまとめて実行")
    p_upd.add_argument("--fetch-limit", type=int, default=20, help="本文を取得する最大件数")
    p_upd.add_argument("--index-limit", type=int, default=50, help="ベクトル化する最大記事数")
    p_upd.add_argument(
        "--summarize", type=int, default=0, help="3行要約もする場合の件数(0なら要約しない)"
    )
    p_upd.set_defaults(func=cmd_update)

    p_show = sub.add_parser("show", help="記事の保存状態と本文の冒頭を確認")
    p_show.add_argument("keyword", help="タイトルに含まれる語句")
    p_show.add_argument("--limit", type=int, default=3, help="表示する記事数")
    p_show.add_argument("--chars", type=int, default=600, help="表示する本文の文字数")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    try:
        args.func(args)
    except GeminiUnavailable as e:
        # 再試行しても、Geminiが使えなかった場合。(長いエラー表示は出さず、対処を案内する)
        print(f"\n[エラー] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
