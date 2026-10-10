#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEJM / Lancet のホームページ(最新号)を巡回し、抄録を日本語訳してテキストにまとめる.

PubMed には頼らず、各誌の公開ページ(最新号の目次と各論文ページ)から
タイトル・著者・抄録を直接取得する。抄録は Claude API で日本語に翻訳し、
1本のテキストファイルにまとめて出力する。

使い方:
    python3 fetch_journal_abstracts.py                 # 既定の出力先に作成
    python3 fetch_journal_abstracts.py --limit 10      # 誌ごと最大10本
    python3 fetch_journal_abstracts.py --outdir ~/Docs
    python3 fetch_journal_abstracts.py --diagnose      # 動かないときの原因調査
"""

import argparse
import datetime as dt
import html
import os
import re
import sys
import time
import urllib.error
import urllib.request

TOOL = "journal-weekly-digest"

# サイト構造が変わると目次の抽出が効かなくなることがある。
# その場合は --diagnose でヒット件数を確認してほしい。
JOURNALS = [
    {
        "name": "New England Journal of Medicine",
        "toc_url": "https://www.nejm.org/toc/nejm/current",
        "base_url": "https://www.nejm.org",
        "link_pattern": re.compile(r'href="(/doi/(?:full|abs|10\.1056)/10\.1056/NEJM[\w.\-]*)"'),
    },
    {
        "name": "The Lancet",
        "toc_url": "https://www.thelancet.com/journals/lancet/issue/current",
        "base_url": "https://www.thelancet.com",
        "link_pattern": re.compile(r'href="(/journals/lancet/article/PII[\w()\-]+/fulltext)"'),
    },
]

ENV_FILE = os.path.expanduser("~/.journal-digest.env")

HEADERS = {
    # 一般的なブラウザに近い UA にしておく(素の urllib UA だと拒否するサイトがある)
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
}


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


def _get(url, retries=4, timeout=60):
    """ページを取得する。混雑時は指数バックオフで再試行する。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise  # サイト側の拒否/不在はリトライしても変わらない
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2 ** i)
    raise RuntimeError(f"取得に失敗しました: {url}: {last}")


def _strip_tags(fragment):
    """HTML断片からタグを除いてテキストだけ残す。"""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _meta(html_text, *names):
    """<meta name="..." content="..."> を順に探して最初に見つかった値を返す。"""
    for name in names:
        m = re.search(
            rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']',
            html_text, re.IGNORECASE,
        )
        if m:
            text = html.unescape(m.group(1)).strip()
            if text:
                return text
    return ""


def _meta_all(html_text, name):
    """同じ name の <meta> を全部拾う(著者名が複数タグに分かれている場合用)。"""
    out = []
    for m in re.finditer(
        rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']',
        html_text, re.IGNORECASE,
    ):
        text = html.unescape(m.group(1)).strip()
        if text:
            out.append(text)
    return out


def extract_links(toc_html, journal):
    seen, links = set(), []
    for m in journal["link_pattern"].finditer(toc_html):
        path = m.group(1)
        if path in seen:
            continue
        seen.add(path)
        links.append(journal["base_url"] + path)
    return links


def extract_abstract(article_html):
    """抄録本文を取り出す。構造が変わっても拾えるよう複数の手がかりを順に試す。"""
    abstract = _meta(article_html, "citation_abstract", "dc.Description", "DC.Description")
    if abstract:
        return _strip_tags(abstract)

    for pattern in (
        r'<section[^>]+class="[^"]*\babstract\b[^"]*"[^>]*>(.*?)</section>',
        r'<div[^>]+class="[^"]*\bAbstracts?\b[^"]*"[^>]*>(.*?)</div>\s*</div>',
        r'<div[^>]+id="[^"]*abstract[^"]*"[^>]*>(.*?)</div>\s*</div>',
    ):
        m = re.search(pattern, article_html, re.IGNORECASE | re.DOTALL)
        if m:
            text = _strip_tags(m.group(1))
            # 見出し語だけを拾ってしまった場合は不採用
            if len(text) > 80:
                return text

    og = _meta(article_html, "og:description")
    return _strip_tags(og) if og else ""


def extract_article(url):
    article_html = _get(url)
    title = _meta(article_html, "citation_title")
    if not title:
        m = re.search(r"<title>([^<]+)</title>", article_html, re.IGNORECASE)
        title = html.unescape(m.group(1)).strip() if m else "(タイトル不明)"

    authors = _meta_all(article_html, "citation_author")
    date = _meta(article_html, "citation_publication_date", "citation_online_date")
    abstract = extract_abstract(article_html)

    return {
        "title": title,
        "authors": ", ".join(authors),
        "date": date,
        "url": url,
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
    """抄録が取れない/訳が出ないときの原因を切り分ける。"""
    ok = True
    print("=== 診断 ===")

    if env_status:
        loaded, msg = env_status
        print(f"[{'OK' if loaded else '--'}] 設定ファイル: {msg}")

    for journal in JOURNALS:
        print(f"[..] {journal['name']} の目次を取得中: {journal['toc_url']}")
        try:
            toc_html = _get(journal["toc_url"])
        except Exception as e:  # noqa: BLE001
            print(f"[NG] 取得に失敗しました: {type(e).__name__}: {e}")
            ok = False
            continue
        links = extract_links(toc_html, journal)
        if links:
            print(f"[OK] 論文リンクを {len(links)} 件検出しました")
        else:
            print("[NG] 論文リンクを検出できませんでした(サイトの構造が変わった可能性)")
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


def write_digest(path, period, journal_results):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"NEJM / Lancet 週次抄録ダイジェスト({period})\n")
        f.write("=" * 70 + "\n\n")
        for journal_name, articles in journal_results:
            f.write(f"■ {journal_name}（{len(articles)}本）\n")
            f.write("-" * 70 + "\n\n")
            for a in articles:
                f.write(f"タイトル: {a['title']}\n")
                if a["authors"]:
                    f.write(f"著者: {a['authors']}\n")
                if a["date"]:
                    f.write(f"掲載日: {a['date']}\n")
                f.write(f"URL: {a['url']}\n\n")
                f.write("[原文抄録]\n")
                f.write((a["abstract_en"] or "(抄録を取得できませんでした)") + "\n\n")
                f.write("[日本語訳]\n")
                f.write((a.get("abstract_ja") or "(翻訳なし)") + "\n")
                f.write("\n" + "=" * 70 + "\n\n")


def main():
    ap = argparse.ArgumentParser(description="NEJM / Lancet の最新号抄録を日本語訳してテキストにまとめる")
    ap.add_argument("--limit", type=int, default=25, help="誌ごとに処理する論文数の上限(既定: 25)")
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
    journal_results = []
    translate_failed = 0
    total_articles = 0

    for journal in JOURNALS:
        print(f"{journal['name']} の目次を取得中...", file=sys.stderr)
        try:
            toc_html = _get(journal["toc_url"])
        except Exception as e:  # noqa: BLE001
            print(f"  ! 目次の取得に失敗しました: {e}", file=sys.stderr)
            journal_results.append((journal["name"], []))
            continue

        links = extract_links(toc_html, journal)[:args.limit]
        print(f"  {len(links)} 本の論文を検出", file=sys.stderr)

        articles = []
        for i, url in enumerate(links, 1):
            print(f"  [{i}/{len(links)}] {url}", file=sys.stderr)
            try:
                article = extract_article(url)
            except Exception as e:  # noqa: BLE001
                print(f"    ! 取得に失敗しました: {e}", file=sys.stderr)
                continue
            if not article["abstract_en"]:
                print("    ! 抄録を検出できませんでした(構造が変わったか抄録なし)", file=sys.stderr)

            if can_translate and article["abstract_en"]:
                try:
                    article["abstract_ja"] = translate(article["abstract_en"], article["title"], args.model)
                except Exception as e:  # noqa: BLE001
                    article["abstract_ja"] = f"[翻訳失敗: {type(e).__name__}: {e}]"
                    translate_failed += 1

            articles.append(article)
            total_articles += 1
            time.sleep(1)  # サイトに負荷をかけないよう間隔を空ける

        journal_results.append((journal["name"], articles))

    if total_articles == 0:
        print("論文を1本も取得できませんでした。ファイルは作成しません。", file=sys.stderr)
        print("  --diagnose で目次ページの取得状況を確認してください。", file=sys.stderr)
        return 1

    period = f"{today:%Y-%m-%d} 時点の最新号"
    out_path = os.path.join(args.outdir, f"NEJM_Lancet抄録{today:%Y%m%d}.txt")
    try:
        os.makedirs(args.outdir, exist_ok=True)
        write_digest(out_path, period, journal_results)
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
        print(f"⚠️  {translate_failed}/{total_articles} 件の翻訳に失敗しました(該当箇所に理由が入っています)")
        print("   原因を調べるには: python3 " + os.path.basename(__file__) + " --diagnose")
        print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
