# 循環器臨床論文 週次ダイジェスト

Circulation / JACC / New England Journal of Medicine / Lancet /
Annals of Internal Medicine から直近1週間の循環器系臨床論文を集め、
Mac の Numbers で開ける一覧ファイルを毎週土曜に自動生成します。

## 出力されるもの

`~/Documents/循環器論文/` に以下の2ファイルが作られます。

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
| サマリー（日本語訳） | 抄録を400字程度に要約翻訳したもの |
| 原題サマリー(英語) | PubMed 収載の抄録全文 |
| 発行日 / 研究種別 / DOI / PMID / URL | 出典確認用 |

## 収集の方針

- **Circulation と JACC** は循環器専門誌なので、掲載された臨床論文をすべて対象にします。
- **NEJM / Lancet / Annals** は総合誌なので、循環器領域（MeSH と抄録キーワード）で絞り込みます。
- 論説・レター・訂正・ニュースなど、および**抄録のない記事は除外**します。
- 書誌情報は PubMed (NCBI E-utilities) から取得するため、巻号・ページ・著者は
  出版社の記録どおりです。推測で埋めた値は入りません。

## セットアップ（Mac で一度だけ）

```bash
git clone <このリポジトリ> ~/cardio-digest
cd ~/cardio-digest

# 日本語訳に使う API キーを設定（省略すると英語抄録のみになります）
echo 'export ANTHROPIC_API_KEY=sk-ant-...' > ~/.cardio-digest.env
chmod 600 ~/.cardio-digest.env

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
python3 scripts/fetch_cardio_papers.py --no-translate  # 翻訳せず高速に
python3 scripts/fetch_cardio_papers.py --outdir ~/Desktop
```

## 設定できる環境変数

| 変数 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | 日本語要約翻訳に使用。未設定なら翻訳をスキップ |
| `NCBI_API_KEY` | 任意。PubMed のレート制限が緩和されます（[取得先](https://www.ncbi.nlm.nih.gov/account/)） |

## 収集条件を変えたいとき

`scripts/fetch_cardio_papers.py` の先頭にある定数を編集してください。

- `CARDIO_JOURNALS` / `GENERAL_JOURNALS` … 対象誌の追加・削除
- `CARDIO_FILTER` … 総合誌に対する循環器の絞り込み条件
- `EXCLUDED_PUBTYPES` … 除外する記事種別

## 動作要件

- macOS（Numbers 変換と launchd 登録のため）
- Python 3.9 以上 + `openpyxl`（`setup.sh` が導入します）
- Numbers.app（未インストールでも `.xlsx` は生成されます）
