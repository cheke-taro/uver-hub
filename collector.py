"""
情報収集モジュール: RSSから記事を取ってきて、共通の形(Article)にそろえます。
「どの情報源でも同じ形にそろえる」ことが、後のRAGで効いてきます。
"""

import html
import re
import time
from dataclasses import dataclass
from typing import Optional

import feedparser

import config


@dataclass
class Article:
    """1件の記事を表すデータ。どの情報源から来ても、この形にそろえる。"""

    source: str  # 情報源の名前(例: GoogleNews:UVERworld)
    title: str  # 記事タイトル
    url: str  # 記事URL(重複チェックのキーにも使う)
    published: Optional[str]  # 公開日時(ISO形式の文字列。不明ならNone)
    content: str  # 本文または概要(HTMLタグは除去済み)


def clean_html(text: str) -> str:
    """RSSの概要に混ざっているHTMLタグを取り除いて、きれいな文章にする。"""
    text = re.sub(r"<[^>]+>", " ", text)  # タグを削除
    text = html.unescape(text)  # &amp; などを元の文字に戻す
    text = re.sub(r"\s+", " ", text)  # 連続する空白を1つに
    return text.strip()


def to_iso(struct_time) -> Optional[str]:
    """feedparserの日時データを 2026-10-10T12:00:00 のような文字列に変換する。"""
    if not struct_time:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", struct_time)


def fetch_feed(name: str, url: str) -> list[Article]:
    """1つのRSSを読み込んで、Articleのリストとして返す。"""
    feed = feedparser.parse(url, agent=config.USER_AGENT)

    # 取得に失敗したときは、空のリストを返して処理を続ける(全体を止めない)
    if feed.bozo and not feed.entries:
        print(f"  [警告] {name} の取得に失敗しました: {feed.get('bozo_exception')}")
        return []

    articles = []
    for entry in feed.entries[: config.MAX_ENTRIES_PER_SOURCE]:
        link = entry.get("link")
        title = entry.get("title")
        if not link or not title:
            continue  # URLやタイトルがないものは使えないのでスキップ

        raw_content = entry.get("summary", "")
        articles.append(
            Article(
                source=name,
                title=clean_html(title),
                url=link,
                published=to_iso(entry.get("published_parsed")),
                content=clean_html(raw_content),
            )
        )
    return articles


def collect_all() -> list[Article]:
    """config.SOURCES に登録された全ての情報源から記事を集める。"""
    all_articles = []
    for name, url in config.SOURCES:
        print(f"取得中: {name}")
        articles = fetch_feed(name, url)
        print(f"  -> {len(articles)}件")
        all_articles.extend(articles)
        time.sleep(1)  # 相手のサーバーに負担をかけないよう、1秒あける
    return all_articles
