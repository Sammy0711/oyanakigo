---
name: publish-check
description: oyanakigo.com の記事（news/）やページ（index.html、service-*.html など）を新規作成・変更したとき、コミットする前に必ず通す品質ゲート。機械検証（render_news_index.py --check、validate_news.py、テスト）→ law-verifier による出典照合 → logic-checker による独立レビュー → 表示確認の順に実行し、合格してからコミット・PR・マージへ進む。依頼主が「公開して」「仕上げて」「反映して」と言ったときに使う。
---

# 公開前チェック（publish-check）

書く役とチェックする役を分ける。メインセッションが書き、スクリプトと独立したエージェントがチェックする。不合格は「書き直し」であって、無視して進めることではない。

## 手順

1. **機械検証**（リポジトリのルートで実行）
   ```
   python3 -B scripts/render_news_index.py
   python3 -B scripts/render_news_index.py --check
   python3 -B scripts/validate_news.py
   python3 -B scripts/test_render_news_index.py
   ```
   FAIL が出たら直して再実行する。記事HTMLを直したら `news/articles_index.json` の `article_sha256` を更新する（UTF-8、CRLF→LF 正規化後の SHA-256）。
2. **出典照合**：原稿が制度・手続・金額・期間・改正日を述べるときは `law-verifier` エージェントに原稿のパスを渡す。`outdated` / `unverified` の行は、直すか「未確認」「窓口で確認」と弱める。確認方法（WebFetch か、`allowed_domains` 付き WebSearch か）を `review` の記録に正直に書く。
3. **独立レビュー**：新規・書き直しのページごとに `logic-checker` エージェントを実行する。`REVISE` なら blocking を全部直して手順1〜3をやり直す。major も、理由を明記できない限り反映する。複数の制度が交わる・資料が食い違うなど判断が重いときは、先に `deep-reasoner` で整理する。
4. **表示確認**：`python3 -m http.server` とヘッドレス Chromium で、パソコン幅と約500px幅のスクリーンショットを撮り、見出し・目次・出典リンク・相談導線・カードの見た目を確認する。
5. **コミット〜マージ**：手順1〜4が合格してから。作業ブランチ（main 以外）にコミットし、プッシュ → PR 作成 → マージまで行う（CLAUDE.md 第1章）。依頼主が「確認してから」「マージしないで」と言った場合と、ゲート不合格の場合はマージしない。
6. **報告**（日本語）：合格したもの、直したもの、未解決の指摘とその理由、依頼主に本番で確認してほしい点（Claude からは oyanakigo.com が見えないため）。

## 注意

- `news/index.html` とトップの `LATEST_NEWS` 範囲は生成物。手で直さず、`articles_index.json` かテンプレート（`scripts/news_index_template.html`）を直して再生成する。
- ゲートの合格は依頼主の承認ではない。個別の相談者について制度の適用を判断する内容は、行政書士 麥生田の確認が必要。
- 10品質ゲートの詳細は `news/README.md`。
