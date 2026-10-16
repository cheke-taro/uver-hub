"""
要約モジュール: Geminiにファン目線で3行要約してもらいます。(前回のmain.pyの機能)
"""

import config
import llm


def summarize_for_fan(text: str) -> str:
    """テキストをファン目線で3行に要約して返す。"""
    prompt = f"""
あなたはUVERworldの熱心なファンです。
次のテキストを読んで、ファンにとって重要なポイントを日本語でちょうど3行に要約してください。

【ルール】
- 必ず3行で出力する(1行につき1ポイント)
- 各行の先頭に「・」を付ける
- ライブ・リリース・チケット・グッズ・メディア出演など、ファンが知りたい情報を優先する
- テキストに書かれていない情報は付け足さない
- 前置きや補足は書かず、要約の3行だけを出力する

【テキスト】
{text}
"""
    return llm.generate_text(prompt, config.THINKING_LEVEL_ANSWER)  # 混雑時は自動で再試行する
