"""
RAGモジュール: 質問に関係する断片を検索して、それを根拠にGeminiに答えてもらいます。

流れ:
  1) 質問を、観点ごとの検索キーワードに言い換える(「ライブとメディア出演」→ 2つの検索)
  2) それぞれをベクトルに変換して、DBに保存した全断片と比べる
  3) 各検索の上位を交互に混ぜて選ぶ(同じ原稿・同じ記事ばかりにならないよう制限する)
  4) 選んだ断片を「参考資料」としてGeminiに渡し、資料だけを根拠に答えさせる
"""

import datetime
import json
import re
import time
from array import array

import config
import llm
import storage
from embedder import embed_texts


def _unpack(blob: bytes) -> array:
    """DBに保存したバイト列を、数値の並びに戻す。"""
    values = array("f")
    values.frombytes(blob)
    return values


def _dot(a, b) -> float:
    """内積。長さ1にそろえたベクトル同士なら、これがそのまま類似度になる。"""
    return sum(x * y for x, y in zip(a, b))


def expand_queries(question: str) -> list[str]:
    """質問を、観点ごとの検索キーワードに言い換える。失敗したら、元の質問だけを返す。

    1つの質問に複数の話題(例: ライブとメディア出演)が含まれると、1回の検索では
    片方の話題に引っ張られて、もう片方の記事を拾えないため。
    """
    prompt = f"""
UVERworldの記事データベースを検索して、次の質問に答えます。
質問に含まれる観点(話題)ごとに、検索に使う短いキーワード文を、最大{config.MAX_QUERY_EXPANSIONS}個作ってください。

【ルール】
- 観点が1つだけなら、1個でよい
- 同じ意味のものを重複させない
- 「ライブ」に関する質問は、単独公演・ツアーと、フェス・対バンへの出演(ライブレポート)を、別の観点に分ける
- 出力は、文字列のJSON配列だけにする(説明やコードブロックは付けない)
  例: ["UVERworld ライブ 公演 ツアー", "UVERworld フェス 対バン 出演 ライブレポート", "UVERworld テレビ 番組 出演 タイアップ"]

【質問】
{question}
"""
    queries: list[str] = []
    try:
        text = re.sub(r"^```(?:json)?|```$", "", llm.generate_text(prompt, config.THINKING_LEVEL_EXPAND), flags=re.MULTILINE).strip()
        items = json.loads(text)
        queries = [q.strip() for q in items if isinstance(q, str) and q.strip()]
    except Exception as e:
        # 言い換えに失敗しても、元の質問だけで検索を続ける。(ただし、検索の質が下がるので知らせる)
        print(f"[注意] 質問の言い換えに失敗したため、元の質問だけで検索します({type(e).__name__})")
        queries = []

    return [question] + [q for q in queries if q != question][: config.MAX_QUERY_EXPANSIONS]


def search(conn, queries: list[str], k: int, timings: dict | None = None):
    """複数の検索キーワードで断片を探して、上位k件を返す。戻り値: [(類似度, DBの行), ...]"""
    t0 = time.perf_counter()
    query_vecs = embed_texts(queries, "RETRIEVAL_QUERY")
    t1 = time.perf_counter()
    if timings is not None:
        timings["埋め込み"] = t1 - t0

    # 除外サイトの断片は、最初から対象にしない
    candidates = [
        (row, _unpack(row["embedding"]))
        for row in storage.get_all_chunks(conn, config.EMBED_MODEL)
        if not config.is_excluded(row["link"])
    ]

    # 断片の本文が主題(BOOST_TERMS)に触れていたら、加点する。(表示される類似度にも加点が含まれる)
    bonus = {
        row["id"]: config.BOOST_SCORE
        if any(term in row["text"].lower() for term in config.BOOST_TERMS)
        else 0.0
        for row, _ in candidates
    }

    # 検索キーワードごとに、(類似度+加点)の高い順に並べる
    ranked_lists = [
        sorted(
            ((_dot(qv, vec) + bonus[row["id"]], row, vec) for row, vec in candidates),
            key=lambda x: x[0],
            reverse=True,
        )
        for qv in query_vecs
    ]

    picked = []
    used_ids: set[int] = set()
    per_article: dict[str, int] = {}  # 記事のURL -> すでに選んだ断片の数
    depth = max((len(r) for r in ranked_lists), default=0)

    # 各検索の1位、2位、3位…を交互に見ていく。(どの観点の記事も拾えるようにするため)
    for i in range(depth):
        for ranked in ranked_lists:
            if i >= len(ranked):
                continue
            score, row, vec = ranked[i]
            if row["id"] in used_ids:
                continue
            # 1つの記事から選びすぎない
            if per_article.get(row["link"], 0) >= config.MAX_CHUNKS_PER_ARTICLE:
                continue
            # すでに選んだ断片とほぼ同じ内容なら、飛ばす(同じ原稿の記事対策)
            if any(_dot(vec, p[2]) > config.DUP_THRESHOLD for p in picked):
                continue
            picked.append((score, row, vec))
            used_ids.add(row["id"])
            per_article[row["link"]] = per_article.get(row["link"], 0) + 1
            if len(picked) >= k:
                break
        if len(picked) >= k:
            break
    if timings is not None:
        timings["検索計算"] = time.perf_counter() - t1
    return [(s, r) for s, r, _ in picked]


def answer_question(conn, question: str, k: int | None = None):
    """質問に答える。戻り値: (回答テキスト, 参考にした断片のリスト, 検索に使ったキーワード, 処理時間の内訳)"""
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    queries = expand_queries(question)
    timings["言い換え"] = time.perf_counter() - t0
    hits = search(conn, queries, k or config.TOP_K, timings)
    if not hits:
        return None, [], queries, timings

    # Geminiに渡す「参考資料」を組み立てる(番号を付けて、出典を引用させる)
    blocks = []
    for n, (_, row) in enumerate(hits, start=1):
        date = (row["published"] or "日時不明")[:10]
        blocks.append(f"[{n}] {row['title']} ({date})\n{row['text']}")
    context = "\n\n".join(blocks)

    today = datetime.date.today().isoformat()  # 今日の日付(古い出来事を新しい出来事と混同させないため)
    prompt = f"""
あなたはUVERworldのファン向け情報アシスタントです。
下の「参考資料」だけを根拠に、質問に日本語で簡潔に答えてください。

今日の日付は {today} です。

【ルール】
- 参考資料に書かれていないことは推測せず、「資料からは分かりません」と答える
- 根拠にした資料の番号を、文末に [1] のように付ける
- 資料の括弧内の日付は「記事の公開日」であり、出来事が起きた日とは限らない。
  本文中の日付や年を確認して、今日より前に終わった出来事を「これから行われる」と書かない
- 開催前の告知記事に書かれた予定は、実際に行われたと断定しない。
  今日より前の日付の予定は「〜の予定でした(実施されたかは資料からは分かりません)」のように書く
- 「最近」「直近」「今後」など時期を聞かれたら、(1)最近終わった出来事 と (2)発表済みの今後の予定 を分けて書く。
  日付の古い出来事は混ぜない。資料に根拠のある該当の出来事は、漏れなくすべて挙げる
- 資料には、関連記事の見出し・ニュース速報・メニューなど、記事の本文と無関係な文字列が混ざっていることがある。
  それらは根拠にせず、その記事自体の内容だけを使う(他の記事の見出しを、UVERworldの出来事として書かない)
- 資料同士で内容が食い違う場合は、その旨を書く

【参考資料】
{context}

【質問】
{question}
"""
    t0 = time.perf_counter()
    answer = llm.generate_text(prompt, config.THINKING_LEVEL_ANSWER)  # 混雑時は自動で再試行する
    timings["回答生成"] = time.perf_counter() - t0
    timings["合計"] = sum(timings.values())
    return answer, hits, queries, timings
