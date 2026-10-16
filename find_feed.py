"""
find_feed.py: Webページから、RSS/AtomフィードのURLを探す補助ツール

使い方:
    python find_feed.py https://example.com/news
    (複数のURLをスペース区切りで渡してもOK)

探し方は2段階です。
  1) ページ内の <link rel="alternate" type="application/rss+xml"> を探す
  2) 見つからなければ、よくあるパス(/feed や /rss.xml など)に実際にアクセスして試す

見つかったURLを config.py の SOURCES に追加すれば、collect で取り込めます。
標準ライブラリだけで動くので、追加インストールは不要です。
"""

import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import config

# 2段階目で試す、よくあるフィードのパス
COMMON_PATHS = [
    "/feed",
    "/feed/",
    "/rss",
    "/rss.xml",
    "/feed.xml",
    "/atom.xml",
    "/index.xml",
    "/rss/news",
    "/feed/news",
]


class FeedLinkParser(HTMLParser):
    """HTMLの <link rel="alternate" type="application/rss+xml"> を探すパーサー。"""

    def __init__(self):
        super().__init__()
        self.feeds = []  # (タイトル, href) のリスト

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = dict(attrs)
        rel = (a.get("rel") or "").lower()
        typ = (a.get("type") or "").lower()
        if "alternate" in rel and ("rss" in typ or "atom" in typ) and a.get("href"):
            self.feeds.append((a.get("title") or "(タイトルなし)", a["href"]))


def find_feeds(page_url: str, html_text: str) -> list[tuple[str, str]]:
    """HTML文字列からフィードを探し、(タイトル, 絶対URL) のリストを返す。"""
    parser = FeedLinkParser()
    parser.feed(html_text)
    # 相対URL(/feed など)を、https://... の形に直す
    return [(title, urljoin(page_url, href)) for title, href in parser.feeds]


def looks_like_feed(text: str) -> bool:
    """取得した中身が、RSS/Atomフィード(XML)らしいかを判定する。"""
    head = text.lstrip()[:1000].lower()
    return "<rss" in head or "<feed" in head or "<rdf:rdf" in head


def fetch_text(url: str) -> str:
    """URLの中身を文字列で取得する。"""
    req = Request(url, headers={"User-Agent": config.USER_AGENT})
    with urlopen(req, timeout=15) as res:
        charset = res.headers.get_content_charset() or "utf-8"
        return res.read(200_000).decode(charset, errors="replace")


def probe_common_paths(page_url: str) -> list[str]:
    """よくあるパスにアクセスして、実際にフィードが返ってくるものを探す。"""
    parts = urlsplit(page_url)
    base = f"{parts.scheme}://{parts.netloc}"
    found = []
    for path in COMMON_PATHS:
        candidate = base + path
        try:
            if looks_like_feed(fetch_text(candidate)):
                found.append(candidate)
        except Exception:
            continue  # 存在しないパスはエラーになるので、無視して次へ
    return found


def main() -> None:
    if len(sys.argv) < 2:
        print("使い方: python find_feed.py <サイトのURL> [<URL> ...]")
        sys.exit(1)

    for page_url in sys.argv[1:]:
        print(f"\n■ {page_url}")
        try:
            html_text = fetch_text(page_url)
        except Exception as e:
            print(f"  [警告] ページを取得できませんでした: {e}")
            continue

        # 1段階目: ページ内の宣言を探す
        feeds = find_feeds(page_url, html_text)
        for title, url in feeds:
            print(f"  - {title}\n    {url}")

        # 2段階目: 見つからなければ、よくあるパスを試す
        if not feeds:
            print("  ページ内に宣言なし。よくあるパスを試します...")
            for url in probe_common_paths(page_url):
                print(f"  - (推測で発見) {url}")
                feeds.append(("", url))

        if not feeds:
            print("  フィードは見つかりませんでした(このサイトはRSS非対応の可能性があります)")


if __name__ == "__main__":
    main()
