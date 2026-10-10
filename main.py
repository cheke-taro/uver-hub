"""
uver-hub: 最小限のテストスクリプト
サンプルテキストをGemini 2.5 Flashに渡して、ファン目線で3行要約します。

事前準備:
    1) pip install google-genai
    2) 環境変数 GEMINI_API_KEY にAPIキーを設定する
       - Mac / Linux : export GEMINI_API_KEY="あなたのAPIキー"
       - Windows(PS) : $env:GEMINI_API_KEY="あなたのAPIキー"
実行:
    python main.py
"""

import os
import sys

from google import genai

# 使用するモデル名
MODEL_NAME = "gemini-3.8-flash"

# 要約したいサンプルテキスト(動作確認用のダミー文章です)
# 本番ではここを「自動収集したニュース記事」などに差し替えます
SAMPLE_TEXT = """
【サンプル記事】あるバンドが、全国ツアーの追加公演を発表した。
追加されるのは東京と大阪の2会場で、チケットは来月から先行受付が始まる。
今回のツアーでは、最新アルバムの収録曲に加えて、ファン人気の高い過去の代表曲も
披露される予定だという。また、公式サイトでは会場限定グッズの情報も公開された。
メンバーは「今回も全力で届けたい。会場で一緒に盛り上がろう」とコメントしている。
"""


def summarize_for_fan(text: str) -> str:
    """テキストを受け取り、ファン目線で重要なポイントを3行で要約して返す関数"""

    # クライアントを作成する
    # APIキーは環境変数 GEMINI_API_KEY から自動で読み込まれるので、
    # ここにキーを直接書く必要はありません
    client = genai.Client()

    # Geminiへのお願い文(プロンプト)
    prompt = f"""
あなたはバンドの熱心なファンです。
次のテキストを読んで、ファンにとって重要なポイントを日本語でちょうど3行に要約してください。

【ルール】
- 必ず3行で出力する(1行につき1ポイント)
- 各行の先頭に「・」を付ける
- ライブ・リリース・チケット・グッズなど、ファンが知りたい情報を優先する
- 前置きや補足は書かず、要約の3行だけを出力する

【テキスト】
{text}
"""

    # Gemini 2.5 Flash に問い合わせる
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )

    # 返ってきた文章を取り出す(前後の空白は削除)
    return response.text.strip()


def main():
    # APIキーが設定されているか先にチェックする(初心者がつまずきやすいポイント)
    if not os.environ.get("GEMINI_API_KEY"):
        print("エラー: 環境変数 GEMINI_API_KEY が設定されていません。")
        print('例) export GEMINI_API_KEY="あなたのAPIキー"')
        sys.exit(1)

    print("=== 元のテキスト ===")
    print(SAMPLE_TEXT.strip())
    print()

    # 要約を実行する(通信エラーなどに備えて try/except で囲む)
    try:
        summary = summarize_for_fan(SAMPLE_TEXT)
    except Exception as e:
        print(f"要約中にエラーが起きました: {e}")
        sys.exit(1)

    print("=== ファン目線の3行要約 ===")
    print(summary)


# このファイルを直接実行したときだけ main() を動かす
if __name__ == "__main__":
    main()