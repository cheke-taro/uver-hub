"""
uver-hub: UVERworld情報収集ハブ(コマンドラインから操作します)

使い方:
    python main.py demo         # 前回のサンプル要約テスト
    python main.py collect      # RSSから記事を集めてDBに保存
    python main.py list         # 保存済みの記事を新しい順に表示
    python main.py summarize    # 未要約の記事をGeminiで3行要約してDBに保存
"""

import argparse
import os
import sys

import collector
import storage

SAMPLE_TEXT = """
【サンプル記事】あるバンドが、全国ツアーの追加公演を発表した。
追加されるのは東京と大阪の2会場で、チケットは来月から先行受付が始まる。
最新アルバムの収録曲に加えて、ファン人気の高い過去の代表曲も披露される予定だという。
""".strip()


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


def cmd_list(args) -> None:
    """保存済みの記事を表示する。"""
    conn = storage.get_connection()
    rows = storage.get_recent(conn, limit=args.limit)
    if not rows:
        print("記事がありません。先に `python main.py collect` を実行してください。")
        return
    for r in rows:
        print(f"[{r['published'] or '日時不明'}] {r['title']}")
        print(f"  {r['url']}")
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
        # タイトルと概要をまとめて渡す
        text = f"{r['title']}\n{r['content'] or ''}"
        try:
            summary = summarize_for_fan(text)
        except Exception as e:
            print(f"  [警告] 要約に失敗しました: {e}")
            continue
        storage.save_summary(conn, r["id"], summary)
        print("  " + summary.replace("\n", "\n  "))


def main() -> None:
    parser = argparse.ArgumentParser(description="uver-hub")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="サンプル要約テスト").set_defaults(func=cmd_demo)
    sub.add_parser("collect", help="記事を収集").set_defaults(func=cmd_collect)

    p_list = sub.add_parser("list", help="記事一覧")
    p_list.add_argument("--limit", type=int, default=10, help="表示件数")
    p_list.set_defaults(func=cmd_list)

    p_sum = sub.add_parser("summarize", help="未要約の記事を要約")
    p_sum.add_argument("--limit", type=int, default=5, help="1回で要約する件数")
    p_sum.set_defaults(func=cmd_summarize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
