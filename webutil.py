"""
Web用の補助モジュール: 回答の表示変換・回数制限・パスワード照合。
(Flaskに依存しない部品だけを、ここに集めています)
"""

import hmac
import html
import re
import threading
import time
from collections import deque

# 回答の中の [1] や [1, 2] のような出典番号を見つける
_CITE = re.compile(r"\[(\d+(?:\s*[,、]\s*\d+)*)\]")
_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
_HEADING = re.compile(r"^#{1,4}\s+(.*)$")


def _inline(text: str) -> str:
    """1行分の文章を、安全なHTMLにする。(太字と、出典番号のリンク化)"""
    t = html.escape(text, quote=True)  # まず必ずエスケープする(スクリプトの混入を防ぐ)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)

    def link(m: re.Match) -> str:
        nums = re.split(r"\s*[,、]\s*", m.group(1))
        return "[" + ", ".join(f'<a href="#src-{n}">{n}</a>' for n in nums) + "]"

    return _CITE.sub(link, t)


def render_answer_html(answer: str) -> str:
    """Geminiの回答(簡単なMarkdown)を、安全なHTMLに変換する。

    対応する書式: 見出し(#)、箇条書き(- や *、字下げで1段階の入れ子)、太字(**)、段落。
    """
    out: list[str] = []
    depth = 0  # 開いている <ul> の数
    for line in answer.splitlines():
        m = _BULLET.match(line)
        if m:
            level = 1 if len(m.group(1).replace("\t", "  ")) >= 2 else 0
            while depth < level + 1:
                out.append("<ul>")
                depth += 1
            while depth > level + 1:
                out.append("</ul>")
                depth -= 1
            out.append(f"<li>{_inline(m.group(2))}</li>")
            continue

        while depth > 0:  # 箇条書きが終わったら、閉じる
            out.append("</ul>")
            depth -= 1
        stripped = line.strip()
        if not stripped:
            continue
        h = _HEADING.match(stripped)
        out.append(f"<h3>{_inline(h.group(1))}</h3>" if h else f"<p>{_inline(stripped)}</p>")

    while depth > 0:
        out.append("</ul>")
        depth -= 1
    return "\n".join(out)


def check_password(provided: str, expected: str) -> bool:
    """パスワードを照合する。(文字を1つずつ比べると時間差で推測されるため、専用の関数で比べる)"""
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


class RateLimiter:
    """質問回数の制限。1分あたり(IPアドレスごと)と、1日あたり(全体)の上限を管理する。

    メモリ上で数えるだけの簡易版です。サーバーを再起動すると、回数はリセットされます。
    """

    def __init__(self, per_minute: int, per_day: int):
        self.per_minute = per_minute
        self.per_day = per_day
        self._hits: dict[str, deque] = {}
        self._day = ""
        self._day_count = 0
        self._lock = threading.Lock()

    def check(self, ip: str, now: float | None = None) -> str | None:
        """質問してよければNone(回数に数える)。上限に達していたら、その理由の文章を返す。"""
        now = time.time() if now is None else now
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        with self._lock:
            if today != self._day:  # 日付が変わったら、1日の回数をリセット
                self._day, self._day_count = today, 0
            if self._day_count >= self.per_day:
                return "本日の質問回数の上限に達しました。明日またお試しください。"

            hits = self._hits.setdefault(ip, deque())
            while hits and now - hits[0] > 60:  # 1分より前の記録は捨てる
                hits.popleft()
            if len(hits) >= self.per_minute:
                return "質問が続いています。1分ほど待ってから、もう一度お試しください。"

            hits.append(now)
            self._day_count += 1
            return None
