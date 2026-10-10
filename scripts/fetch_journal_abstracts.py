#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEJM / Lancet の直近掲載論文の抄録を日本語訳してテキストにまとめる.

NEJM・Lancet のサイトは Bot 対策(WAF)で単純な HTTP クライアントからの
アクセスを 403 Forbidden で拒否するため、ホームページを直接スクレイピング
する方式は使えない。代わりに PubMed (NCBI E-utilities) から両誌の直近の
論文を取得する。これは本リポジトリの循環器ダイジェスト(fetch_cardio_papers.py)
と同じ、実績のある取得方法。

抄録は Claude API で日本語に翻訳し、1本のテキストファイルにまとめて出力する。

使い方:
    python3 fetch_journal_abstracts.py                 # 直近7日
    python3 fetch_journal_abstracts.py --days 14       # 直近14日
    python3 fetch_journal_abstracts.py --outdir ~/Docs
    python3 fetch_journal_abstracts.py --diagnose      # 動かないときの原因調査
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "journal-weekly-digest"

# 対象誌。PubMed の略誌名([ta])で指定する。
JOURNALS = ['"N Engl J Med"[ta]', '"Lancet"[ta]']

# 論説・レター・訂正・ニュースなど、および抄録のない記事は除外する
EXCLUDED_PUBTYPES = {
    "Editorial", "Comment", "News", "Published Erratum", "Erratum",
    "Retraction of Publication", "Retracted Publication", "Biography",
    "Historical Article", "Newspaper Article", "Congress", "Bibliography",
    "Patient Education Handout", "Video-Audio Media",
}

ENV_FILE = os.path.expanduser("~/.journal-digest.env")


def load_env_file(path=ENV_FILE):
    """~/.journal-digest.env から環境変数を読み込む。

    シェルの `source` に頼らず、この関数だけで設定が効くようにする。
    既に環境変数が設定されていればそちらを優先する。
    戻り値は (読み込んだ変数名のリスト, 状態メッセージ)。
    """
    if not os.path.isfile(path):
        return [], f"{path} がありません"

    loaded = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                if "=" not in line:
                    continue
                name, _, value = line.partition("=")
                name, value = name.strip(), value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if name and name not in os.environ:
                    os.environ[name] = value
                    loaded.append(name)
    except OSError as e:
        return [], f"{path} を読めません: {e}"

    return loaded, f"{path} から {len(loaded)} 件読み込みました"


def _get(url, retries=4):
    """E-utilities への GET。混雑時は指数バックオフで再試行する。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"PubMed への接続に失敗しました: {last}")


def build_query():
    return "(" + " OR ".join(JOURNALS) + ")"


def search(query, mindate, maxdate, api_key=None):
    params = {
        "db": "pubmed", "term": query, "retmax": "300",
        "datetype": "edat", "mindate": mindate, "maxdate": maxdate,
        "retmode": "json", "tool": TOOL,
    }
    if api_key:
        params["api_key"] = api_key
    data = json.loads(_get(f"{EUTILS}/esearch.fcgi?{urllib.parse.urlencode(params)}"))
    return data.get("esearchresult", {}).get("idlist", [])


def fetch(pmids, api_key=None):
    """PMID をまとめて efetch し、記事単位の XML 要素を返す。"""
    out = []
    for i in range(0, len(pmids), 100):
        params = {
            "db": "pubmed", "id": ",".join(pmids[i:i + 100]),
            "retmode": "xml", "tool": TOOL,
        }
        if api_key:
            params["api_key"] = api_key
        root = ET.fromstring(_get(f"{EUTILS}/efetch.fcgi?{urllib.parse.urlencode(params)}"))
        out.extend(root.findall(".//PubmedArticle"))
        time.sleep(0.4)
    return out


def _text(node):
    return "".join(node.itertext()).strip() if node is not None else ""


def parse_article(art):
    """PubmedArticle 要素から必要な書誌情報を抜き出す。"""
    pubtypes = {_text(p) for p in art.findall(".//PublicationType")}
    if pubtypes & EXCLUDED_PUBTYPES:
        return None

    abstract_nodes = art.findall(".//Abstract/AbstractText")
    parts = []
    for n in abstract_nodes:
        label = n.get("Label")
        body = _text(n)
        parts.append(f"{label}: {body}" if label else body)
    abstract = "\n".join(p for p in parts if p)
    if not abstract:
        return None  # 抄録のないものは対象外

    journal = art.find(".//Journal")
    journal_title = _text(journal.find("Title")) if journal is not None else ""

    authors = []
    for a in art.findall(".//AuthorList/Author"):
        last, fore = _text(a.find("LastName")), _text(a.find("ForeName"))
        name = f"{last} {fore}".strip() or _text(a.find("CollectiveName"))
        if name:
            authors.append(name)

    ids = {i.get("IdType"): _text(i) for i in art.findall(".//ArticleIdList/ArticleId")}
    pmid = ids.get("pubmed", "")

    pubdate = art.find(".//Journal/JournalIssue/PubDate")
    date = " ".join(_text(pubdate).split()) if pubdate is not None else ""

    return {
        "journal": journal_title,
        "title": _text(art.find(".//ArticleTitle")),
        "authors": ", ".join(authors),
        "date": date,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "abstract_en": abstract,
    }


def valid_api_key(key):
    """実際に使えそうな API キーかどうか(説明用のプレースホルダ事故を防ぐ)。"""
    return bool(key) and key.startswith("sk-ant-") and "..." not in key and len(key) >= 40


def translate(abstract_en, title, model):
    """Claude API で抄録を日本語に翻訳する。例外は呼び出し側で処理する。"""
    import anthropic

    client = anthropic.Anthropic(max_retries=5, timeout=300.0)
    system = (
        "あなたは臨床医向けの抄読会資料を作成する医学翻訳者です。"
        "英文抄録を日本語に翻訳してください。"
        "背景・方法・結果・結論の構成がわかるようにし、数値と統計値"
        "(ハザード比、信頼区間、p値、症例数など)は原文のまま保持してください。"
        "前置き・見出し・補足は書かず、翻訳本文のみを出力してください。"
    )
    res = client.messages.create(
        model=model,
        max_tokens=8000,
        output_config={"effort": "low"},
        system=system,
        messages=[{"role": "user", "content": f"タイトル: {title}\n\n抄録:\n{abstract_en}"}],
    )
    if res.stop_reason == "refusal":
        return "[翻訳不可: モデルが応答を拒否しました]"
    return "".join(b.text for b in res.content if b.type == "text").strip()


def diagnose(model="claude-opus-5", env_status=None):
    """論文が取れない/訳が出ないときの原因を切り分ける。"""
    ok = True
    print("=== 診断 ===")

    if env_status:
        loaded, msg = env_status
        print(f"[{'OK' if loaded else '--'}] 設定ファイル: {msg}")

    print("[..] PubMed への接続を確認中...")
    try:
        today = dt.date.today()
        start = today - dt.timedelta(days=14)
        pmids = search(build_query(), start.strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d"),
                       os.environ.get("NCBI_API_KEY"))
        print(f"[OK] 直近14日で {len(pmids)} 件ヒットしました")
        if not pmids:
            print("     0件です。--days を増やして様子を見てください。")
    except Exception as e:  # noqa: BLE001
        print(f"[NG] PubMed への接続に失敗しました: {type(e).__name__}: {e}")
        ok = False

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("[NG] ANTHROPIC_API_KEY が設定されていません")
        if not os.path.isfile(ENV_FILE):
            print(f"     {ENV_FILE} が存在しません。次のコマンドで作成してください:")
            print("       echo 'export ANTHROPIC_API_KEY=<実際のキー>' > ~/.journal-digest.env")
            print("       chmod 600 ~/.journal-digest.env")
        return 1
    if not valid_api_key(key):
        print(f"[NG] ANTHROPIC_API_KEY が実際のキーではありません(長さ {len(key)})")
        print("     1) https://console.anthropic.com/settings/keys でキーを発行する")
        print(f"     2) {ENV_FILE} に書く")
        return 1
    print(f"[OK] ANTHROPIC_API_KEY を検出(末尾4桁: ...{key[-4:]})")

    try:
        import anthropic
    except ImportError:
        print("[NG] anthropic パッケージが未導入です")
        print("     対処: python3 -m pip install --user anthropic")
        return 1
    print(f"[OK] anthropic {getattr(anthropic, '__version__', '不明')} を検出")

    print(f"[..] {model} へテスト翻訳を送信中...")
    try:
        text = translate("The trial met its primary endpoint.", "test", model)
        print(f"[OK] 応答を受信: {text}")
    except Exception as e:  # noqa: BLE001
        print(f"[NG] API 呼び出しに失敗: {type(e).__name__}: {e}")
        ok = False

    print("=== 診断ここまで ===")
    return 0 if ok else 1


def write_digest(path, period, rows):
    by_journal = {}
    for row in rows:
        by_journal.setdefault(row["journal"], []).append(row)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"NEJM / Lancet 週次抄録ダイジェスト({period})\n")
        f.write("=" * 70 + "\n\n")
        for journal_name, articles in by_journal.items():
            f.write(f"■ {journal_name}({len(articles)}本)\n")
            f.write("-" * 70 + "\n\n")
            for a in articles:
                f.write(f"タイトル: {a['title']}\n")
                if a["authors"]:
                    f.write(f"著者: {a['authors']}\n")
                if a["date"]:
                    f.write(f"掲載日: {a['date']}\n")
                f.write(f"URL: {a['url']}\n\n")
                f.write("[原文抄録]\n")
                f.write(a["abstract_en"] + "\n\n")
                f.write("[日本語訳]\n")
                f.write((a.get("abstract_ja") or "(翻訳なし)") + "\n")
                f.write("\n" + "=" * 70 + "\n\n")


def main():
    ap = argparse.ArgumentParser(description="NEJM / Lancet の直近掲載論文の抄録を日本語訳してテキストにまとめる")
    ap.add_argument("--days", type=int, default=7, help="遡る日数(既定: 7)")
    # ~/Documents ~/Desktop ~/Downloads は macOS の TCC 保護対象で、
    # launchd から起動したプロセスは書き込めない。既定は保護対象外に置く。
    ap.add_argument("--outdir", default=os.path.expanduser("~/NEJM_Lancet抄録"),
                    help="出力先ディレクトリ(既定: ~/NEJM_Lancet抄録)")
    ap.add_argument("--no-translate", action="store_true", help="日本語訳を行わない(英語抄録のみ出力)")
    ap.add_argument("--model", default="claude-opus-5", help="翻訳に使うモデル")
    ap.add_argument("--diagnose", action="store_true", help="動かない原因を調べて終了する")
    args = ap.parse_args()

    env_status = load_env_file()

    if args.diagnose:
        return diagnose(args.model, env_status)

    can_translate = not args.no_translate and valid_api_key(os.environ.get("ANTHROPIC_API_KEY"))
    if not args.no_translate and not can_translate:
        print("i 日本語訳は行いません(ANTHROPIC_API_KEY 未設定)。有効にするには --diagnose を参照",
              file=sys.stderr)

    today = dt.date.today()
    start = today - dt.timedelta(days=args.days)
    mindate, maxdate = start.strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d")
    period = f"{start:%Y-%m-%d} 〜 {today:%Y-%m-%d}"

    api_key = os.environ.get("NCBI_API_KEY")
    print(f"PubMed を検索中: {period}", file=sys.stderr)
    pmids = search(build_query(), mindate, maxdate, api_key)
    print(f"  {len(pmids)} 件ヒット", file=sys.stderr)

    rows = [r for r in (parse_article(a) for a in fetch(pmids, api_key)) if r]
    rows.sort(key=lambda r: (r["journal"], r["title"]))
    print(f"  抄録ありの論文として {len(rows)} 件を採用", file=sys.stderr)

    if not rows:
        print("該当論文がありませんでした。ファイルは作成しません。", file=sys.stderr)
        return 0

    translate_failed = 0
    if can_translate:
        for i, row in enumerate(rows, 1):
            try:
                row["abstract_ja"] = translate(row["abstract_en"], row["title"], args.model)
            except Exception as e:  # noqa: BLE001
                row["abstract_ja"] = f"[翻訳失敗: {type(e).__name__}: {e}]"
                translate_failed += 1
            print(f"  翻訳 {i}/{len(rows)}", file=sys.stderr)

    out_path = os.path.join(args.outdir, f"NEJM_Lancet抄録{today:%Y%m%d}.txt")
    try:
        os.makedirs(args.outdir, exist_ok=True)
        write_digest(out_path, period, rows)
    except PermissionError:
        print(f"エラー: {args.outdir} に書き込めません。", file=sys.stderr)
        print("  macOS では ~/Documents ~/Desktop ~/Downloads が保護されており、", file=sys.stderr)
        print("  launchd から起動した週次実行はこれらに書き込めません。", file=sys.stderr)
        print("  対処: --outdir で保護対象外の場所を指定する(既定は ~/NEJM_Lancet抄録)", file=sys.stderr)
        return 1

    print(f"作成しました: {out_path}")
    if translate_failed:
        print()
        print("=" * 60)
        print(f"⚠️  {translate_failed}/{len(rows)} 件の翻訳に失敗しました(該当箇所に理由が入っています)")
        print("   原因を調べるには: python3 " + os.path.basename(__file__) + " --diagnose")
        print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
