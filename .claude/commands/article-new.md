---
description: oyanakigo.com に記事を1本追加する（または既存記事を更新する）。テーマの重複確認 → 一次情報の収集と主張・出典の対応づけ → 記事HTML と articles_index.json の作成 → 一覧の再生成 → publish-check のゲート → PR 作成・マージまで行う。
allowed-tools: Bash, Read, Write, Edit, Agent, WebSearch, WebFetch
---

# /article-new

`$ARGUMENTS` は記事のテーマ（と、分かれば想定読者・伝えたいこと）。

## 手順1. 既存記事との重複

`news/articles_index.json` の title・summary・claims と `news/*.html` を確認する。目的・主張・読者の次の行動がほぼ同じ記事があれば、新規ではなくその記事の更新を提案し、どの記事かを依頼主に伝える（ゲート10）。

## 手順2. 一次情報と主張の対応

1. 国・自治体・裁判所・実施機関の資料を集める（CLAUDE.md 第5章の方法。直接つながらないドメインは `allowed_domains` 付き WebSearch）。
2. 書きたい主張ごとに、根拠となる資料と該当箇所を先に決める。根拠が見つからない主張は書かない（ゲート1〜4）。
3. 改正は成立・公布・施行を区別する。金額は最新版で確認できた額だけ。
4. 複数の制度が交わるテーマは `deep-reasoner` で整理してから書く。

## 手順3. 作成

1. 既存記事（`news/*.html`）の構成・CSS をそのまま使い、`news/YYYY-MM-DD-<id>.html` を作る。見出し下は公開日のみ（`data-date="published"`）、情報確認日（`data-date="verified"`）は末尾の「ご利用にあたって」内。
2. 主張の要素に `id` を付け、その要素の中から `#source-<id>` へリンクする。
3. `news/articles_index.json` に sources・claims・editorial_proposals・review（10ゲートの結果と根拠、実際の確認主体、SHA-256）を追加する。架空の監修者は書かない。
4. 業務範囲（CLAUDE.md 第4章）を守り、相談導線（`../index.html#contact`）を置く。

## 手順4. ゲート

`publish-check` スキルの手順どおり：機械検証 → `law-verifier` → `logic-checker` → 表示確認。

## 手順5. 公開

作業ブランチにコミット（例：`feat: 記事「…」を追加`）→ プッシュ → PR → マージ。CLAUDE.md 第7章に従い、CLAUDE.md の作業履歴も同じ PR で更新する。

## 報告（日本語）

記事のURL（`https://oyanakigo.com/news/<file>`）、使った出典、ゲートの結果、依頼主に本番で確認してほしい点。
