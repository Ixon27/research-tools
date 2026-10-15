#!/usr/bin/env python3
"""harvest.py — 리뷰논문용 문헌 코퍼스 수집기 (Europe PMC + OpenAlex).

주제 쿼리로 매칭 논문을 **전수 수집**(페이지네이션)하고, 두 소스를 합쳐
중복 제거 후 메타데이터(제목·저자·연도·저널·DOI·인용수·OA·초록·소스)를
corpus.md + corpus.csv 로 저장한다. 리뷰논문 "다 가져와 비교·거르기"의 1단계.

소스:
  - Europe PMC : 생의학·미생물 특화, 초록 충실 (무료·무키)
  - OpenAlex   : 전분야 커버리지, 저널(venue)·인용그래프 품질신호 (무료·무키)
표준 라이브러리만 사용(certifi 있으면 활용).

사용법:
    python3 harvest.py "gut microbiome obesity" --since 2018 --max 400
    python3 harvest.py 'TITLE:"Paenibacillus" AND TITLE_ABS:genome' --source epmc
    python3 harvest.py "extremophile thermostability" --source openalex --min-cited 20
옵션:
    --source {both,epmc,openalex}  기본 both (합쳐서 중복제거)
    --max N        소스별 최대 수집(기본 500)
    --since YEAR   이 연도 이후만
    --min-cited N  인용 N 이상만(수집 후 필터)
    --open-only    OA(전문 무료)만
    --out DIR      출력 폴더(기본 ./out/<날짜>)

주의: --source both 는 쿼리를 자유어(키워드)로 다룬다. Europe PMC 필드문법
(TITLE: 등)을 쓰려면 --source epmc 로.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENALEX = "https://api.openalex.org/works"
MAILTO = os.environ.get("OPENALEX_MAILTO", "")   # 본인 이메일 — OpenAlex polite pool (빠른 응답). 비워도 동작한다

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    SSL_CTX = ssl.create_default_context()


import html as _html
TAG_RE = re.compile(r"<[^>]+>")


def clean_text(s: str) -> str:
    """HTML 태그(<i>,<scp>,<h4> 등)·엔티티 제거. 엔티티 먼저 unescape 후 태그 제거
    (순서 반대면 &lt;i&gt;가 태그로 되살아남). 이중 인코딩까지 처리."""
    s = _html.unescape(_html.unescape(s or ""))
    s = TAG_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": f"lit-review/2.0 ({MAILTO})"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            log(f"재시도 {attempt+1}/3 ({e})")
            time.sleep(2 * (attempt + 1))
    return {}


# ---------- Europe PMC ----------

def harvest_epmc(query: str, cap: int) -> list[dict]:
    cursor, seen, out, total = "*", set(), [], None
    while True:
        params = {"query": query, "format": "json", "pageSize": "100",
                  "resultType": "core", "cursorMark": cursor}
        data = get_json(EPMC + "?" + urllib.parse.urlencode(params))
        if total is None:
            total = data.get("hitCount", 0)
            log(f"  [EPMC] hitCount={total}")
        out.extend(data.get("resultList", {}).get("result", []))
        nxt = data.get("nextCursorMark")
        if not nxt or nxt == cursor or nxt in seen or len(out) >= cap:
            break
        seen.add(cursor); cursor = nxt
        time.sleep(0.34)
    return [epmc_row(r) for r in out[:cap]]


def epmc_authors(rec: dict) -> str:
    al = rec.get("authorList", {}).get("author", [])
    names = [a.get("fullName") or a.get("lastName", "") for a in al]
    if not names:
        return rec.get("authorString", "")
    return ", ".join(names[:3]) + (f" et al. ({len(names)}인)" if len(names) > 3 else "")


def epmc_row(r: dict) -> dict:
    return {
        "title": clean_text((r.get("title") or "").rstrip(".")),
        "authors": epmc_authors(r),
        "year": str(r.get("pubYear", "")),
        "journal": clean_text(r.get("journalInfo", {}).get("journal", {}).get("title", "")),
        "doi": (r.get("doi") or "").lower(),
        "pmid": r.get("pmid", ""),
        "pmcid": r.get("pmcid", ""),
        "cited": int(r.get("citedByCount", 0) or 0),
        "open_access": "Y" if r.get("isOpenAccess") == "Y" else "N",
        "abstract": clean_text((r.get("abstractText") or "").replace("\n", " ")),
        "source": "epmc",
    }


# ---------- OpenAlex ----------

def openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = [(i, w) for w, idxs in inv.items() for i in idxs]
    pos.sort()
    return " ".join(w for _, w in pos)


def harvest_openalex(query: str, cap: int, since: int | None, open_only: bool) -> list[dict]:
    filters = []
    if since:
        filters.append(f"from_publication_date:{since}-01-01")
    if open_only:
        filters.append("is_oa:true")
    cursor, out, total = "*", [], None
    while True:
        params = {"search": query, "per-page": "200", "cursor": cursor, "mailto": MAILTO}
        if filters:
            params["filter"] = ",".join(filters)
        data = get_json(OPENALEX + "?" + urllib.parse.urlencode(params))
        if total is None:
            total = data.get("meta", {}).get("count", 0)
            log(f"  [OpenAlex] count={total}")
        out.extend(data.get("results", []))
        nxt = data.get("meta", {}).get("next_cursor")
        if not nxt or len(out) >= cap or not data.get("results"):
            break
        cursor = nxt
        time.sleep(0.2)
    return [openalex_row(r) for r in out[:cap]]


def openalex_row(r: dict) -> dict:
    src = (r.get("primary_location") or {}).get("source") or {}
    auth = [a["author"]["display_name"] for a in r.get("authorships", []) if a.get("author")]
    ids = r.get("ids", {})
    pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1]
    return {
        "title": clean_text((r.get("title") or "").rstrip(".")),
        "authors": ", ".join(auth[:3]) + (f" et al. ({len(auth)}인)" if len(auth) > 3 else ""),
        "year": str(r.get("publication_year", "")),
        "journal": clean_text(src.get("display_name", "") or ""),
        "doi": (r.get("doi") or "").replace("https://doi.org/", "").lower(),
        "pmid": pmid,
        "pmcid": "",
        "cited": int(r.get("cited_by_count", 0) or 0),
        "open_access": "Y" if (r.get("open_access") or {}).get("is_oa") else "N",
        "abstract": clean_text(openalex_abstract(r.get("abstract_inverted_index"))),
        "source": "openalex",
    }


# ---------- 병합 · 중복제거 ----------

def normalize_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def merge(records: list[dict]) -> list[dict]:
    """DOI→제목으로 중복 병합. 중복이면 초록 긴 쪽 유지, source 합침(both)."""
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for r in records:
        key = r["doi"] or ("t:" + normalize_title(r["title"]))
        if not key or key == "t:":
            key = f"anon:{len(order)}"
        if key not in by_key:
            by_key[key] = r
            order.append(key)
        else:
            cur = by_key[key]
            # 더 정보 많은 레코드를 base 로 (초록 길이 우선), 인용수는 max
            base = r if len(r["abstract"]) > len(cur["abstract"]) else cur
            base = dict(base)
            base["cited"] = max(cur["cited"], r["cited"])
            base["open_access"] = "Y" if "Y" in (cur["open_access"], r["open_access"]) else "N"
            srcs = set(cur["source"].split("+")) | set(r["source"].split("+"))
            base["source"] = "+".join(sorted(srcs))
            base["pmid"] = cur["pmid"] or r["pmid"]
            base["pmcid"] = cur["pmcid"] or r["pmcid"]
            by_key[key] = base
    return [by_key[k] for k in order]


# ---------- 출력 ----------

def write_outputs(rows: list[dict], query: str, source: str, outdir: str, here: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    cols = ["title", "authors", "year", "journal", "doi", "pmid", "pmcid",
            "cited", "open_access", "source", "abstract"]
    with open(os.path.join(outdir, "corpus.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    md_path = os.path.join(outdir, "corpus.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"---\ntags: [lit-review, corpus]\ncreated: {dt.date.today().isoformat()}\n---\n\n")
        f.write(f"# 문헌 코퍼스 — {len(rows)}편\n\n")
        f.write(f"쿼리: `{query}` · 소스: {source} · 인용순 정렬\n\n")
        f.write("> 스크리닝(포함/제외 기준)은 `/review-paper` 2단계에서. `source`가 `epmc+openalex`면 두 곳 모두 색인된 것.\n\n")
        f.write("| # | 연도 | 인용 | OA | 소스 | 제목 | 저자 | 저널 | DOI |\n")
        f.write("|---|------|------|----|------|------|------|------|-----|\n")
        for i, x in enumerate(rows, 1):
            doi = f"[{x['doi']}](https://doi.org/{x['doi']})" if x["doi"] else "—"
            oa = "✅" if x["open_access"] == "Y" else ""
            title = x["title"].replace("|", "\\|")
            auth = x["authors"].replace("|", "\\|")
            jour = x["journal"].replace("|", "\\|")
            f.write(f"| {i} | {x['year']} | {x['cited']} | {oa} | {x['source']} | "
                    f"{title} | {auth} | {jour} | {doi} |\n")
        f.write("\n---\n\n## 초록\n\n")
        for i, x in enumerate(rows, 1):
            f.write(f"### {i}. {x['title']} ({x['year']})\n\n")
            f.write(f"- 저자: {x['authors']} · 저널: {x['journal']} · 인용 {x['cited']} · "
                    f"OA {x['open_access']} · DOI: {x['doi'] or '—'} · 소스: {x['source']}\n\n")
            f.write((x["abstract"] or "_(초록 없음)_") + "\n\n")
    return md_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--source", choices=["both", "epmc", "openalex"], default="both")
    ap.add_argument("--max", type=int, default=500)
    ap.add_argument("--since", type=int, default=None)
    ap.add_argument("--min-cited", type=int, default=0)
    ap.add_argument("--open-only", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    records: list[dict] = []
    failed: list[str] = []
    if args.source in ("both", "epmc"):
        q = args.query
        if args.since:
            q = f"({q}) AND PUB_YEAR:[{args.since} TO 3000]"
        if args.open_only:
            q = f"({q}) AND OPEN_ACCESS:Y"
        log(f"쿼리(EPMC): {q}")
        try:
            records += harvest_epmc(q, args.max)
        except Exception as e:  # noqa: BLE001 — 한 소스 실패가 전체를 막지 않게
            log(f"⚠️ EPMC 실패, 건너뜀: {e}")
            failed.append("epmc")
    if args.source in ("both", "openalex"):
        log(f"쿼리(OpenAlex): {args.query}")
        try:
            records += harvest_openalex(args.query, args.max, args.since, args.open_only)
        except Exception as e:  # noqa: BLE001
            log(f"⚠️ OpenAlex 실패, 건너뜀: {e}")
            failed.append("openalex")

    if not records and failed:
        print(f"❌ 소스 모두 실패({', '.join(failed)}) — 네트워크·쿼리 확인 후 재시도.")
        return 1
    if failed:
        log(f"⚠️ 일부 소스 실패({', '.join(failed)}) — 나머지로 진행. 코퍼스가 불완전할 수 있음.")

    log(f"수집 {len(records)}편(중복 포함) → 병합")
    rows = merge(records)
    if args.min_cited:
        rows = [x for x in rows if x["cited"] >= args.min_cited]
    rows.sort(key=lambda x: (x["cited"], x["year"]), reverse=True)
    log(f"최종 {len(rows)}편 (인용 내림차순)")

    if not rows:
        print("결과 0편 — 쿼리를 넓혀보세요.")
        return 0

    here = os.path.dirname(os.path.abspath(__file__))
    outdir = args.out or os.path.join(here, "out", dt.date.today().isoformat())
    md = write_outputs(rows, args.query, args.source, outdir, here)
    both = sum(1 for x in rows if "+" in x["source"])
    log(f"저장: {os.path.relpath(md, here)} (양쪽 색인 {both}편)")
    print(f"\n✅ {len(rows)}편 → {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
