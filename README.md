# 循環器臨床論文 週次ダイジェスト

Circulation / JACC / New England Journal of Medicine / Lancet /
Annals of Internal Medicine から直近1週間の循環器系臨床論文を集め、
Mac の Numbers で開ける一覧ファイルを毎週土曜に自動生成します。

## 出力されるもの

`~/循環器論文/` に以下の2ファイルが作られます。

- `循環器臨床論文YYYYMMDD.numbers` … Numbers 形式（macOS のみ）
- `循環器臨床論文YYYYMMDD.xlsx` … 同じ内容の Excel 形式

列は次のとおりです。

| 列 | 内容 |
|---|---|
| 雑誌名 | 掲載誌 |
| 巻(号) | 例: `154(9)` |
| ページ | 例: `701-712` |
| 論文タイトル | 原題 |
| 著者名 | 全著者 |
| 施設名 | 筆頭著者の所属 |
| 抄録（英語） | PubMed 収載の抄録全文 |
| 日本語サマリー（記入用） | 空欄。必要な論文だけ手元で訳して書き込む欄（下記参照） |
| 発行日 / 研究種別 / DOI / PMID / URL | 出典確認用 |

## 収集の方針

- **Circulation と JACC** は循環器専門誌なので、掲載された臨床論文をすべて対象にします。
- **NEJM / Lancet / Annals** は総合誌なので、循環器領域（MeSH と抄録キーワード）で絞り込みます。
- 論説・レター・訂正・ニュースなど、および**抄録のない記事は除外**します。
- 書誌情報は PubMed (NCBI E-utilities) から取得するため、巻号・ページ・著者は
  出版社の記録どおりです。推測で埋めた値は入りません。

## macOS の権限について

出力先を `~/Documents` `~/Desktop` `~/Downloads` にしないでください。
これらは macOS の TCC で保護されており、**launchd から起動される週次実行は
書き込めません**（ターミナルからの手動実行だけ成功し、週次実行が
`PermissionError: Operation not permitted` で失敗します）。
既定の `~/循環器論文` は保護対象外なので、そのまま使えば問題ありません。

どうしても `~/Documents` に置きたい場合は、システム設定 →
プライバシーとセキュリティ → フルディスクアクセス に `/bin/bash` を
追加してください（権限が広くなるため非推奨）。

`.numbers` への変換は Numbers.app を Apple Events で操作します。
週次実行時に Numbers が起動していなければ自動で（前面に出さずに）起動し、
応答可能になるまで最大90秒待ちます。ログアウト中やロック画面では
起動できないため `.xlsx` のみが作られます（ログに理由が残ります）。

## 日本語訳について

既定では**英語抄録のみ**を収集し、日本語訳は行いません。
「日本語サマリー（記入用）」列は空欄で出力されるので、読みたい論文だけ
抄録をコピーして Claude などで訳し、その欄に書き込む運用を想定しています。

自動翻訳を有効にしたい場合は、Anthropic の API キーを
`~/.cardio-digest.env` に設定してください（33本でおよそ1ドル）。

```bash
echo 'export ANTHROPIC_API_KEY=PASTE_YOUR_REAL_KEY_HERE' > ~/.cardio-digest.env
chmod 600 ~/.cardio-digest.env
python3 -m pip install --user anthropic
python3 scripts/fetch_cardio_papers.py --diagnose   # 設定を確認
```

## セットアップ（Mac で一度だけ）

```bash
git clone <このリポジトリ> ~/cardio-digest
cd ~/cardio-digest

# 週次実行を登録
./scripts/setup.sh
```

登録されると **毎週土曜 7:12** に自動実行されます。

```bash
# 次回実行予定を見る
launchctl print gui/$UID/jp.cardio.weekly-digest | grep -A3 'next fire'

# 今すぐ動かして試す
launchctl kickstart -p gui/$UID/jp.cardio.weekly-digest

# 自動実行を止める
launchctl bootout gui/$UID/jp.cardio.weekly-digest
```

実行ログは `~/Library/Logs/cardio-digest/YYYYMMDD.log` に残ります。

## 手動で実行する

```bash
python3 scripts/fetch_cardio_papers.py                 # 直近7日
python3 scripts/fetch_cardio_papers.py --days 30       # 直近30日
python3 scripts/fetch_cardio_papers.py --outdir ~/Desktop
```

## 日本語訳が入らないとき

```bash
python3 scripts/fetch_cardio_papers.py --diagnose
```

APIキーの有無と形式、`anthropic` パッケージの導入状況、実際の API 応答を
順に確認し、`[NG]` の行に対処法を表示します。

翻訳がスキップされた場合は本体の実行時にも末尾で警告が出ます。
`.xlsx` / `.numbers` は英語抄録入りで作成されるので、原因を直してから
同じコマンドを再実行すれば上書きされます。

## 設定できる環境変数

| 変数 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | 日本語要約翻訳に使用。未設定なら翻訳をスキップ |

環境変数は `~/.cardio-digest.env` に書いておけばスクリプトが自動で読み込みます
（`source` は不要）。シェルの環境変数が設定済みならそちらが優先されます。
| `NCBI_API_KEY` | 任意。PubMed のレート制限が緩和されます（[取得先](https://www.ncbi.nlm.nih.gov/account/)） |

## 収集条件を変えたいとき

`scripts/fetch_cardio_papers.py` の先頭にある定数を編集してください。

- `CARDIO_JOURNALS` / `GENERAL_JOURNALS` … 対象誌の追加・削除
- `CARDIO_FILTER` … 総合誌に対する循環器の絞り込み条件
- `EXCLUDED_PUBTYPES` … 除外する記事種別

## 動作要件

- macOS（Numbers 変換と launchd 登録のため）
- Python 3.9 以上 + `openpyxl`（`setup.sh` が導入します）。日本語訳を使う場合のみ `anthropic` も必要
- Numbers.app（未インストールでも `.xlsx` は生成されます）

---

# NEJM / Lancet 週次抄録ダイジェスト

New England Journal of Medicine と The Lancet の直近掲載論文を集め、
抄録を日本語に翻訳して1本のテキストファイルにまとめます。
毎週土曜の朝に自動実行されるよう launchd に登録できます。

NEJM・Lancet のサイトは Bot 対策(WAF)で単純な HTTP クライアントからの
アクセスを 403 Forbidden で拒否するため、ホームページを直接スクレイピング
する方式ではなく、循環器ダイジェスト(`fetch_cardio_papers.py`)と同じ
PubMed (NCBI E-utilities) 経由で取得します。両誌の論文はいずれも
掲載後すぐ PubMed に収載されるため、「直近掲載論文」として扱えます。
論説・レター・訂正・ニュースなど、抄録のない記事は除外します。

## 出力されるもの

`~/NEJM_Lancet抄録/` に `NEJM_Lancet抄録YYYYMMDD.txt` が作られます。
誌ごとに論文を並べ、それぞれに原文の抄録と日本語訳を記載します。

```
■ New England Journal of Medicine(12本)
----------------------------------------------------------------------

タイトル: ...
著者: ...
掲載日: ...
URL: https://pubmed.ncbi.nlm.nih.gov/.../

[原文抄録]
...

[日本語訳]
...

======================================================================
```

## セットアップ（Mac で一度だけ）

```bash
# 日本語訳を使う場合（推奨）: Anthropic の API キーを設定
echo 'export ANTHROPIC_API_KEY=sk-ant-...' > ~/.journal-digest.env
chmod 600 ~/.journal-digest.env
python3 -m pip install --user anthropic

# 週次実行を登録（毎週土曜 7:30）
./scripts/setup_journal_digest.sh
```

```bash
# 次回実行予定を見る
launchctl print gui/$UID/jp.journal-digest.weekly | grep -A3 'next fire'

# 今すぐ動かして試す
launchctl kickstart -p gui/$UID/jp.journal-digest.weekly

# 自動実行を止める
launchctl bootout gui/$UID/jp.journal-digest.weekly
```

実行ログは `~/Library/Logs/journal-digest/YYYYMMDD.log` に残ります。

## 手動で実行する

```bash
python3 scripts/fetch_journal_abstracts.py                 # 直近7日
python3 scripts/fetch_journal_abstracts.py --days 14       # 直近14日
python3 scripts/fetch_journal_abstracts.py --no-translate  # 英語抄録のみ
python3 scripts/fetch_journal_abstracts.py --outdir ~/Desktop
```

## うまく取得できないとき

```bash
python3 scripts/fetch_journal_abstracts.py --diagnose
```

PubMed への接続と検索結果の件数、API キーと翻訳の動作確認を順に行い、
`[NG]` の行に対処法を表示します。

## 設定できる環境変数

| 変数 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | 日本語訳に使用。未設定なら翻訳をスキップ(英語抄録のみ) |
| `NCBI_API_KEY` | 任意。PubMed のレート制限が緩和されます([取得先](https://www.ncbi.nlm.nih.gov/account/)) |

環境変数は `~/.journal-digest.env` に書いておけばスクリプトが自動で読み込みます。

## 動作要件

- macOS(launchd 登録のため。スクリプト自体は Python が動けば他OSでも実行可)
- Python 3.9 以上(追加パッケージなしで動作)。日本語訳を使う場合のみ `anthropic` が必要
