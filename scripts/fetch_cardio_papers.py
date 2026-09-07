#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""循環器臨床論文の週次サマリー収集ツール.

Circulation / JACC / NEJM / Lancet / Annals of Internal Medicine から
直近1週間の循環器系臨床論文を PubMed 経由で取得し、
雑誌名・巻号・ページ・タイトル・著者・施設・日本語サマリーを
Excel (.xlsx) にまとめる。macOS では Numbers 形式にも変換する。

使い方:
    python3 fetch_cardio_papers.py                 # 直近7日
    python3 fetch_cardio_papers.py --days 14       # 直近14日
    python3 fetch_cardio_papers.py --outdir ~/Docs
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "cardio-weekly-digest"

# 循環器専門誌: 臨床論文をすべて拾う
CARDIO_JOURNALS = ['"Circulation"[ta]', '"J Am Coll Cardiol"[ta]']

# 総合誌: 循環器領域に絞り込む
GENERAL_JOURNALS = ['"N Engl J Med"[ta]', '"Lancet"[ta]', '"Ann Intern Med"[ta]']

CARDIO_FILTER = (
    '("Cardiovascular Diseases"[MeSH] OR "Cardiology"[MeSH] OR '
    '"Cardiovascular Agents"[MeSH] OR '
    'cardiac[tiab] OR cardiology[tiab] OR cardiovascular[tiab] OR '
    'heart[tiab] OR coronary[tiab] OR myocardial[tiab] OR myocarditis[tiab] OR '
    '"atrial fibrillation"[tiab] OR arrhythmia*[tiab] OR "heart failure"[tiab] OR '
    'hypertension[tiab] OR hypertensive[tiab] OR aortic[tiab] OR valvular[tiab] OR '
    'valve[tiab] OR stent[tiab] OR angioplasty[tiab] OR "lipid lowering"[tiab] OR '
    'statin*[tiab] OR cholesterol[tiab] OR anticoagul*[tiab] OR antiplatelet[tiab] OR '
    'thrombosis[tiab] OR "pulmonary embolism"[tiab] OR stroke[tiab])'
)

# 原著・臨床研究のみ。論説やレターは除外する
EXCLUDED_PUBTYPES = {
    "Editorial", "Comment", "News", "Published Erratum", "Erratum",
    "Retraction of Publication", "Retracted Publication", "Biography",
    "Historical Article", "Newspaper Article", "Congress", "Bibliography",
    "Patient Education Handout", "Video-Audio Media",
}

HEADERS = [
    "雑誌名", "巻(号)", "ページ", "論文タイトル", "著者名", "施設名",
    "サマリー（日本語訳）", "原題サマリー(英語)", "発行日", "研究種別",
    "DOI", "PMID", "URL",
]


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


def build_query(days):
    """雑誌別の条件を1本の PubMed クエリにまとめる。"""
    cardio = " OR ".join(CARDIO_JOURNALS)
    general = " OR ".join(GENERAL_JOURNALS)
    return f"(({cardio}) OR (({general}) AND {CARDIO_FILTER}))"


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
        return None  # 抄録のないものは臨床論文として扱わない

    journal = art.find(".//Journal")
    issue = journal.find("JournalIssue") if journal is not None else None
    volume = _text(issue.find("Volume")) if issue is not None else ""
    number = _text(issue.find("Issue")) if issue is not None else ""

    authors = []
    affiliation = ""
    for a in art.findall(".//AuthorList/Author"):
        last, fore = _text(a.find("LastName")), _text(a.find("ForeName"))
        name = f"{last} {fore}".strip() or _text(a.find("CollectiveName"))
        if name:
            authors.append(name)
        if not affiliation:
            aff = a.find(".//AffiliationInfo/Affiliation")
            affiliation = _text(aff)

    ids = {i.get("IdType"): _text(i) for i in art.findall(".//ArticleIdList/ArticleId")}
    pmid = ids.get("pubmed", "")

    pubdate = art.find(".//Journal/JournalIssue/PubDate")
    date = " ".join(_text(pubdate).split()) if pubdate is not None else ""

    return {
        "雑誌名": _text(journal.find("Title")) if journal is not None else "",
        "巻(号)": f"{volume}({number})" if number else volume,
        "ページ": _text(art.find(".//Pagination/MedlinePgn")) or _text(art.find(".//Pagination/StartPage")),
        "論文タイトル": _text(art.find(".//ArticleTitle")),
        "著者名": ", ".join(authors),
        "施設名": affiliation,
        "サマリー（日本語訳）": "",
        "原題サマリー(英語)": abstract,
        "発行日": date,
        "研究種別": ", ".join(sorted(pubtypes - {"Journal Article"})) or "Journal Article",
        "DOI": ids.get("doi", ""),
        "PMID": pmid,
        "URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
    }


def translate(rows, model="claude-opus-5"):
    """Claude API で抄録を日本語サマリーに要約翻訳する。

    ANTHROPIC_API_KEY が未設定なら英語抄録のみを残してスキップする。
    1本ずつ独立に処理し、失敗した論文だけを記録して残りは続行する。
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("! ANTHROPIC_API_KEY が未設定のため日本語訳をスキップします", file=sys.stderr)
        return

    try:
        import anthropic
    except ImportError:
        print("! anthropic パッケージが未導入のため日本語訳をスキップします\n"
              "  導入するには: python3 -m pip install --user anthropic", file=sys.stderr)
        return

    # レート制限(429)やサーバエラーは SDK が指数バックオフで再試行する
    client = anthropic.Anthropic(max_retries=5, timeout=300.0)

    system = (
        "あなたは循環器内科医向けの抄読会資料を作成する医学翻訳者です。"
        "英文抄録を日本語で400字程度に要約翻訳してください。"
        "背景・方法・結果・結論がわかるようにし、数値と統計値（ハザード比、信頼区間、"
        "p値、症例数など）は原文のまま保持してください。"
        "前置き・見出し・補足は書かず、要約本文のみを出力してください。"
    )

    failed = 0
    for i, row in enumerate(rows, 1):
        try:
            res = client.messages.create(
                model=model,
                max_tokens=8000,  # 思考トークンも消費するため余裕を持たせる
                output_config={"effort": "low"},  # 定型的な要約翻訳なので低めで十分
                system=system,
                messages=[{"role": "user", "content": (
                    f"タイトル: {row['論文タイトル']}\n\n"
                    f"抄録:\n{row['原題サマリー(英語)']}"
                )}],
            )
            if res.stop_reason == "refusal":
                row["サマリー（日本語訳）"] = "[翻訳不可: モデルが応答を拒否しました]"
                failed += 1
            else:
                row["サマリー（日本語訳）"] = "".join(
                    b.text for b in res.content if b.type == "text"
                ).strip()
        except anthropic.RateLimitError as e:
            row["サマリー（日本語訳）"] = f"[翻訳失敗: レート制限 {e}]"
            failed += 1
        except anthropic.APIStatusError as e:
            row["サマリー（日本語訳）"] = f"[翻訳失敗: HTTP {e.status_code}]"
            failed += 1
        except anthropic.APIConnectionError as e:
            row["サマリー（日本語訳）"] = f"[翻訳失敗: 接続エラー {e}]"
            failed += 1

        print(f"  翻訳 {i}/{len(rows)}", file=sys.stderr)

    if failed:
        print(f"! {failed} 件の翻訳に失敗しました（該当セルに理由が入っています）",
              file=sys.stderr)


def write_xlsx(rows, path, period):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "循環器臨床論文"

    ws.append([f"循環器臨床論文まとめ（{period}）  取得件数: {len(rows)}"])
    ws.append([])
    ws.append(HEADERS)

    head_fill = PatternFill("solid", fgColor="C00000")
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = head_fill
        c.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
    ws["A1"].font = Font(bold=True, size=14)

    for row in rows:
        ws.append([row.get(h, "") for h in HEADERS])

    widths = {
        "雑誌名": 22, "巻(号)": 10, "ページ": 14, "論文タイトル": 55, "著者名": 40,
        "施設名": 40, "サマリー（日本語訳）": 70, "原題サマリー(英語)": 70,
        "発行日": 14, "研究種別": 24, "DOI": 28, "PMID": 12, "URL": 40,
    }
    for i, h in enumerate(HEADERS, 1):
        ws.column_dimensions[get_column_letter(i)].width = widths[h]

    for r in ws.iter_rows(min_row=4):
        for c in r:
            c.alignment = Alignment(vertical="top", wrap_text=True)

    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:{get_column_letter(len(HEADERS))}{ws.max_row}"
    wb.save(path)


def to_numbers(xlsx_path):
    """macOS 上で Numbers に読み込ませ .numbers として保存する。"""
    if sys.platform != "darwin":
        return None
    numbers_path = os.path.splitext(xlsx_path)[0] + ".numbers"
    script = f'''
    tell application "Numbers"
        set d to open POSIX file "{xlsx_path}"
        save d in POSIX file "{numbers_path}"
        close d saving no
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True, timeout=180)
        return numbers_path
    except Exception as e:  # noqa: BLE001
        print(f"! Numbers への変換に失敗しました（.xlsx はそのまま使えます）: {e}",
              file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser(description="循環器臨床論文の週次まとめを作成する")
    ap.add_argument("--days", type=int, default=7, help="遡る日数（既定: 7）")
    ap.add_argument("--outdir", default=os.path.expanduser("~/Documents/循環器論文"),
                    help="出力先ディレクトリ")
    ap.add_argument("--no-translate", action="store_true", help="日本語訳を行わない")
    ap.add_argument("--model", default="claude-opus-5", help="翻訳に使うモデル")
    args = ap.parse_args()

    today = dt.date.today()
    start = today - dt.timedelta(days=args.days)
    mindate, maxdate = start.strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d")
    period = f"{start:%Y-%m-%d} 〜 {today:%Y-%m-%d}"

    api_key = os.environ.get("NCBI_API_KEY")
    print(f"PubMed を検索中: {period}", file=sys.stderr)
    pmids = search(build_query(args.days), mindate, maxdate, api_key)
    print(f"  {len(pmids)} 件ヒット", file=sys.stderr)

    rows = [r for r in (parse_article(a) for a in fetch(pmids, api_key)) if r]
    rows.sort(key=lambda r: (r["雑誌名"], r["ページ"]))
    print(f"  臨床論文として {len(rows)} 件を採用", file=sys.stderr)

    if not rows:
        print("該当論文がありませんでした。ファイルは作成しません。", file=sys.stderr)
        return 0

    if not args.no_translate:
        translate(rows, args.model)

    os.makedirs(args.outdir, exist_ok=True)
    xlsx = os.path.join(args.outdir, f"循環器臨床論文{today:%Y%m%d}.xlsx")
    write_xlsx(rows, xlsx, period)
    print(f"作成しました: {xlsx}")

    numbers = to_numbers(xlsx)
    if numbers:
        print(f"作成しました: {numbers}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
