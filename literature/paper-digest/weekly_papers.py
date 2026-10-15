#!/usr/bin/env python3
"""이번 주 논문 — 주간 논문 수집·검증·발송.

매주 월요일, config.json의 4개 카테고리마다
  - 피인용 상위 2편 (파란 섹션) — FWCI(분야·연도 보정 인용 영향력) 순
  - 최신 1편 (주황 섹션) — Claude 관련도 사전선별을 통과한 것 중 최신
을 Europe PMC에서 모으고, OpenAlex로 실측 인용수·저널 지표·철회 여부를 확인한 뒤
디스코드·Gmail로 보낸다. 한 번 보낸 논문은 history.json에 남아 다시 오지 않는다.
표준 라이브러리만 사용한다 (외부 pip 패키지 불필요).
"""

import datetime as dt
import html
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr

BASE = os.path.dirname(os.path.abspath(__file__))
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ICITE = "https://icite.od.nih.gov/api/pubs"  # NIH RCR(상대 인용 비율) 지표
OPENALEX_WORKS = "https://api.openalex.org/works"
OPENALEX_SOURCES = "https://api.openalex.org/sources"
# OpenAlex는 키가 필요 없지만, 연락처를 UA에 넣으면 polite pool(빠른 큐)로 처리된다
OA_UA = f"weekly-paper-digest/2.0 (mailto:{os.environ.get('OPENALEX_MAILTO', '')})"  # OpenAlex polite pool용 본인 이메일

# macOS python.org 빌드는 시스템 CA를 못 찾는 경우가 있어 certifi 번들을 우선 사용
try:
    import certifi

    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    SSL_CTX = ssl.create_default_context()


def log(msg):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


def load_config():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def load_secrets():
    """secrets.env 를 읽어 환경변수처럼 dict 로 반환."""
    secrets = {}
    path = os.path.join(BASE, "secrets.env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip()
    # 환경변수가 있으면 우선
    for k in ("GMAIL_APP_PASSWORD", "ANTHROPIC_API_KEY", "DISCORD_WEBHOOK_URL"):
        if os.environ.get(k):
            secrets[k] = os.environ[k]
    return secrets


def epmc_search(query, sort, page_size):
    """Europe PMC 검색. resultType=core 로 초록·인용수 포함."""
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": str(page_size),
        "sort": sort,
    }
    url = EPMC + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "weekly-paper-digest/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("resultList", {}).get("result", [])
        except Exception as e:  # noqa: BLE001
            log(f"  EPMC 재시도 {attempt + 1}/3: {e}")
            time.sleep(3)
    return []


import re

_TAG = re.compile(r"<[^>]+>")


def strip_tags(s):
    # EPMC 제목엔 <i>Salmonella</i> 가 &lt;i&gt; 로 이스케이프돼 오는 경우가 있다.
    # 먼저 엔티티를 풀고 태그를 지워야 &lt;/i&gt; 가 그대로 새지 않는다.
    return " ".join(_TAG.sub("", html.unescape(s or "")).split())


def normalize(rec):
    pmid = rec.get("pmid") or rec.get("id") or ""
    doi = rec.get("doi", "")
    if doi:
        link = f"https://doi.org/{doi}"
    elif pmid:
        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    else:
        link = f"https://europepmc.org/article/{rec.get('source', 'MED')}/{rec.get('id', '')}"
    return {
        "id": rec.get("id", ""),
        "pmid": pmid,
        "doi": doi,
        "title": strip_tags(rec.get("title") or "").strip().rstrip("."),
        "authors": rec.get("authorString", ""),
        "journal": (rec.get("journalInfo", {}) or {}).get("journal", {}).get("title", "")
        or rec.get("journalTitle", ""),
        "year": rec.get("pubYear", ""),
        "date": rec.get("firstPublicationDate", ""),
        "cited": int(rec.get("citedByCount", 0) or 0),
        "abstract": strip_tags(rec.get("abstractText") or "").strip(),
        "link": link,
        # 신뢰 판정용 원자료
        "src": rec.get("source", ""),
        "pub_types": list((rec.get("pubTypeList", {}) or {}).get("pubType", []) or []),
        "corrections": [
            c.get("type", "")
            for c in (rec.get("commentCorrectionList", {}) or {}).get("commentCorrection", []) or []
        ],
    }


# 철회·우려표명은 검색 단계에서 이미 뺀다 (뒤에서 OpenAlex로 한 번 더 확인)
EXCLUDE_CLAUSE = ' NOT (PUB_TYPE:"Retracted Publication" OR PUB_TYPE:"Expression of Concern")'


def collect_candidates(cfg):
    """카테고리마다 후보를 넉넉히 모은다. 선별은 검증 뒤에 한다."""
    this_year = dt.date.today().year
    lo = this_year - cfg["highly_cited_years"] + 1
    pool_size = cfg.get("quality", {}).get("candidate_pool", 30)
    results = []
    for cat in cfg["categories"]:
        log(f"카테고리: {cat['name']}")
        base_q = f"({cat['query']}){EXCLUDE_CLAUSE}"
        cited_q = f"({base_q}) AND (PUB_YEAR:[{lo} TO {this_year}])"
        bucket = {
            "category": cat["name"],
            "cited_pool": [normalize(r) for r in epmc_search(cited_q, "CITED desc", pool_size)],
            "new_pool": [normalize(r) for r in epmc_search(base_q, "P_PDATE_D desc", pool_size)],
            "cited": [],
            "new": [],
        }
        log(f"  후보 피인용 {len(bucket['cited_pool'])}편, 최신 {len(bucket['new_pool'])}편")
        results.append(bucket)
        time.sleep(1)
    return results


def _pool(buckets):
    out = []
    for b in buckets:
        out.extend(b["cited_pool"] + b["new_pool"])
    return out


def select_papers(buckets, cfg, prescreen):
    """1층 신뢰 필터 → 2층 선별·정렬 → 카테고리별 최종 편수 확정.

    피인용 슬롯은 FWCI(분야·연도 보정 인용 영향력) 내림차순.
    원인용수로 정렬하면 리뷰논문과 큰 분야가 구조적으로 유리하고,
    발행 2년 창에서도 앞선 해가 뒤엣해를 항상 이긴다.
    """
    q = cfg.get("quality", {})
    today = dt.date.today()
    hist = load_history(cfg)
    min_cite = q.get("min_citations_for_fwci", 5)
    one_per_journal = q.get("one_paper_per_journal", True)
    picked_ids = set()         # 이번 회차에 이미 뽑은 것 (카테고리 간 중복 방지)
    seen = set(hist) | picked_ids
    journals = set()
    dropped = {}

    def passes(p):
        if not p["title"] or p["id"] in seen:
            return False
        reason, warn = trust_flags(p, cfg, today)
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            return False
        p["warnings"] = warn
        if one_per_journal and p.get("journal"):
            if p["journal"] in journals:
                return False
        return True

    def take(cands, n):
        picked = []
        for p in cands:
            if len(picked) >= n:
                break
            if not passes(p):
                continue
            picked_ids.add(p["id"])
            seen.add(p["id"])
            journals.add(p.get("journal", ""))
            picked.append(p)
        if len(picked) < n:
            picked += relax(cands, n - len(picked))
        return picked

    def relax(cands, need):
        """후보가 말랐을 때 편수를 줄이는 대신 '가장 오래 전에 보낸 것'부터 되살린다.

        신뢰 필터(철회·프리프린트·미래날짜)는 절대 풀지 않는다. 푸는 건 발송 이력뿐.
        """
        # hist 에 있다는 이유로 걸린 것들만 되살린다 (이번 회차에 이미 뽑은 건 제외)
        stale = sorted((p for p in cands if p["id"] in hist and p["id"] not in picked_ids),
                       key=lambda p: hist[p["id"]])
        picked = []
        for p in stale:
            if len(picked) >= need:
                break
            reason, warn = trust_flags(p, cfg, today)
            if reason:
                continue
            p["warnings"] = warn + [f"{hist[p['id']]} 에 보낸 논문 (후보 부족으로 재등장)"]
            picked_ids.add(p["id"])
            seen.add(p["id"])
            picked.append(p)
        if picked:
            log(f"  후보 부족 → 예전 발송분 {len(picked)}편 재사용")
        return picked

    for b in buckets:
        # 피인용 슬롯: FWCI 우선. 인용이 적으면 FWCI가 불안정(0.0)하므로 뒤로 보낸다.
        def sort_key(p):
            cited = p.get("oa_cited") or p["cited"]
            fwci = p.get("fwci")
            reliable = fwci is not None and cited >= min_cite
            return (1 if reliable else 0, fwci if reliable else 0, cited)

        b["cited"] = take(sorted(b["cited_pool"], key=sort_key, reverse=True),
                          cfg["n_highly_cited"])

        # 최신 슬롯: 그냥 최신순으로 뽑으면 한 저널의 같은 주제가 도배된다.
        # 제목·저널만으로 관련도를 사전 선별한 뒤 그중 최신을 고른다.
        cands = sorted(b["new_pool"], key=lambda p: p.get("date", ""), reverse=True)
        if prescreen:
            keep = prescreen(b["category"], cands, cfg)
            if keep:
                cands = keep
        b["new"] = take(cands, cfg["n_newest"])
        log(f"  {b['category']}: 피인용 {len(b['cited'])}편 · 최신 {len(b['new'])}편 확정")

    if dropped:
        log("신뢰 필터 탈락: " + ", ".join(f"{k} {v}편" for k, v in sorted(dropped.items())))
    for b in buckets:
        b.pop("cited_pool", None)
        b.pop("new_pool", None)
    return hist


def fetch_icite(buckets):
    """PMID 목록으로 iCite에서 RCR·인용수·논문유형 보강."""
    papers = _flatten(buckets)
    pmids = [p["pmid"] for p in papers if p.get("pmid")]
    if not pmids:
        return
    url = ICITE + "?pmids=" + ",".join(pmids)
    req = urllib.request.Request(url, headers={"User-Agent": "weekly-paper-digest/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        by = {str(d.get("pmid")): d for d in data.get("data", [])}
        n = 0
        for p in papers:
            d = by.get(str(p.get("pmid")))
            if not d:
                continue
            rcr = d.get("relative_citation_ratio")
            p["rcr"] = round(rcr, 2) if isinstance(rcr, (int, float)) else None
            if isinstance(d.get("citation_count"), int):
                p["cited"] = d["citation_count"]
            p["is_research"] = d.get("is_research_article")
            n += 1
        log(f"iCite RCR 보강 완료 ({n}편)")
    except Exception as e:  # noqa: BLE001
        log(f"iCite 보강 실패 (RCR 없이 진행): {e}")


def _flatten(buckets):
    papers = []
    for b in buckets:
        papers.extend(b["cited"] + b["new"])
    return papers


# ── OpenAlex 검증 계층 ────────────────────────────────────────────────
# Europe PMC의 citedByCount는 EPMC 코퍼스 내부 인용만 세어 실제의 절반 수준이다
# (예: Nat Rev Microbiol SCFA 리뷰 = EPMC 209회 vs OpenAlex 415회).
# OpenAlex에서 실측 인용수·FWCI(분야/연도 보정)·철회 여부·저널 지표를 가져온다.

def _oa_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": OA_UA})
    with urllib.request.urlopen(req, timeout=40, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def openalex_enrich(papers):
    """PMID(없으면 DOI) 배치 조회로 실측 인용수·FWCI·철회·유형·ISSN 채우기."""
    sel = ("ids,cited_by_count,fwci,citation_normalized_percentile,"
           "is_retracted,type,primary_location,publication_year")
    by_pmid, by_doi = {}, {}
    for p in papers:
        if p.get("pmid"):
            by_pmid.setdefault(str(p["pmid"]), []).append(p)
        elif p.get("doi"):
            by_doi.setdefault(p["doi"].lower(), []).append(p)

    def _apply(w):
        ids = w.get("ids", {}) or {}
        pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1]
        doi = (ids.get("doi") or "").replace("https://doi.org/", "").lower()
        targets = by_pmid.get(pmid, []) or by_doi.get(doi, [])
        src = (w.get("primary_location") or {}).get("source") or {}
        cnp = w.get("citation_normalized_percentile") or {}
        for p in targets:
            p["oa_cited"] = w.get("cited_by_count")
            p["fwci"] = w.get("fwci")
            p["pct_top1"] = bool(cnp.get("is_in_top_1_percent"))
            p["pct_top10"] = bool(cnp.get("is_in_top_10_percent"))
            p["oa_retracted"] = bool(w.get("is_retracted"))
            p["oa_type"] = w.get("type") or ""
            p["issn_l"] = src.get("issn_l") or ""

    n = 0
    for key, table in (("pmid", by_pmid), ("doi", by_doi)):
        keys = list(table)
        for i in range(0, len(keys), 50):
            chunk = keys[i:i + 50]
            url = (f"{OPENALEX_WORKS}?per_page=50&select={sel}"
                   f"&filter={key}:" + "|".join(chunk))
            try:
                for w in _oa_get(url).get("results", []):
                    _apply(w)
                    n += 1
            except Exception as e:  # noqa: BLE001
                log(f"  OpenAlex {key} 배치 실패: {e}")
            time.sleep(0.2)
    log(f"OpenAlex 보강 완료 ({n}/{len(papers)}편)")


# 2년 평균 피인용 → 등급 라벨. 표시 전용이며 절대 필터로 쓰지 않는다.
# (실측: eLife 1.74 < PLoS ONE 3.12 < J Ethnopharmacol 5.34 < Bioinformatics 6.12 —
#  하한선을 걸면 좋은 저널이 먼저 죽는다.)
def journal_tier(mc):
    if mc is None:
        return ""
    if mc >= 20:
        return "최상위"
    if mc >= 10:
        return "상위"
    if mc >= 5:
        return "중상위"
    if mc >= 2:
        return "보통"
    return "낮음"


def journal_metrics(papers):
    """고유 ISSN만 모아 OpenAlex sources 조회 → 저널 지표를 각 논문에 채운다."""
    issns = sorted({p.get("issn_l") for p in papers if p.get("issn_l")})
    if not issns:
        return
    info = {}
    sel = "issn_l,issn,display_name,summary_stats,host_organization_name,is_in_doaj"
    for i in range(0, len(issns), 50):
        chunk = issns[i:i + 50]
        url = (f"{OPENALEX_SOURCES}?per_page=50&select={sel}"
               f"&filter=issn:" + "|".join(chunk))
        try:
            for srec in _oa_get(url).get("results", []):
                sm = srec.get("summary_stats", {}) or {}
                rec = {
                    "j_name": srec.get("display_name", ""),
                    "j_2yr": sm.get("2yr_mean_citedness"),
                    "j_h": sm.get("h_index"),
                    "j_pub": srec.get("host_organization_name") or "",
                    "j_doaj": bool(srec.get("is_in_doaj")),
                }
                for key in filter(None, [srec.get("issn_l")] + (srec.get("issn") or [])):
                    info.setdefault(key, rec)
        except Exception as e:  # noqa: BLE001
            log(f"  OpenAlex sources 배치 실패: {e}")
        time.sleep(0.2)
    n = 0
    for p in papers:
        rec = info.get(p.get("issn_l"))
        if not rec:
            continue
        p.update(rec)
        p["j_tier"] = journal_tier(rec["j_2yr"])
        n += 1
    log(f"저널 지표 보강 완료 ({n}/{len(papers)}편)")


def trust_flags(p, cfg, today):
    """1층 신뢰 판정. (탈락사유 or None, 표시용 경고 리스트) 를 돌려준다."""
    q = cfg.get("quality", {})
    warn = []

    types = [t.lower() for t in p.get("pub_types", [])]
    corrections = [c.lower() for c in p.get("corrections", [])]
    retracted = (
        p.get("oa_retracted")
        or any("retracted publication" in t for t in types)
        or any("retraction in" in c for c in corrections)
    )
    if retracted:
        if q.get("exclude_retracted", True):
            return "철회 논문", warn
        warn.append("철회된 논문")

    if any("expression of concern" in t for t in types) or \
       any("expression of concern" in c for c in corrections):
        if q.get("exclude_retracted", True):
            return "우려표명(Expression of Concern)", warn
        warn.append("우려표명 있음")

    if q.get("exclude_preprint", True) and (
        p.get("oa_type") == "preprint" or p.get("src") == "PPR"
    ):
        return "프리프린트", warn

    # ahead-of-print 이슈 날짜 때문에 미래 날짜 논문이 '최신' 1위를 먹는다
    if q.get("exclude_future_dated", True) and p.get("date", "") > today.isoformat():
        return f"미래 발행일({p['date']})", warn

    if any("erratum" in c or "correction in" in c for c in corrections):
        warn.append("정오표 있음")
    if p.get("j_2yr") is None:
        warn.append("저널 지표 없음")
    return None, warn


# ── 발송 이력 ────────────────────────────────────────────────────────
# 쿼리가 결정론적이라 이력이 없으면 매주 같은 피인용 논문이 그대로 다시 온다.

def history_path():
    return os.path.join(BASE, "history.json")


def load_history(cfg):
    """한 번 보낸 논문은 다시 안 보낸다. 만료 기간을 두지 않는다.

    '최근 2년' 검색 창이 매년 1월에 통째로 갈리므로 후보는 해마다 새로 공급되고,
    그래도 마르면 relax() 가 오래된 것부터 되살린다. 한 편당 27바이트.
    """
    try:
        with open(history_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


# 연동(notebook_sync.py)이 쓰는 필드만 — normalize() 의 출력 중 일부
MANIFEST_FIELDS = ("id", "pmid", "doi", "title", "authors", "journal", "year", "date",
                   "cited", "abstract", "link", "src")


def save_manifest(buckets):
    """이번 회차의 카테고리·슬롯 구성을 남긴다.

    history.json 은 중복 방지용 대장이라 ID만 담는다. 뒤따르는 NotebookLM 연동이
    디스코드와 같은 순서·분류로 노트를 만들려면 구성 자체가 따로 필요하다.

    논문 정보(제목·DOI·초록 등)도 함께 담는다. 연동이 Europe PMC 를 다시 조회하게
    두면 그쪽이 죽은 날 논문이 조용히 빠진다 (2026-09-21 W39 — 503 연속으로
    10편 중 1편 누락). 발송 때 이미 손에 있던 정보를 그대로 넘기면 조회가 필요 없다.
    """
    manifest = {
        "date": dt.date.today().isoformat(),
        "categories": [
            {
                "name": b["category"],
                "cited": [p["id"] for p in b["cited"]],
                "new": [p["id"] for p in b["new"]],
            }
            for b in buckets
        ],
        "papers": {
            p["id"]: {k: p.get(k, "") for k in MANIFEST_FIELDS}
            for b in buckets
            for p in b["cited"] + b["new"]
        },
    }
    with open(os.path.join(BASE, "last_digest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    log("이번 회차 구성 저장 (last_digest.json)")


def save_history(hist, papers):
    today = dt.date.today().isoformat()
    for p in papers:
        if p.get("id"):
            hist[p["id"]] = today
    with open(history_path(), "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1, sort_keys=True)
    log(f"발송 이력 저장 ({len(hist)}편 보관)")


def build_enrich_prompt(papers, cfg):
    items = []
    for i, p in enumerate(papers):
        ab = p["abstract"][:1500] if p["abstract"] else "(초록 없음)"
        items.append(f"[{i}] 제목: {p['title']}\n저널/연도: {p['journal']} {p['year']}\n초록: {ab}")
    return (
        "다음은 한 대학원생을 위해 수집한 논문들이다. 연구자 배경:\n"
        f"{cfg['researcher_context']}\n\n"
        "각 논문에 대해 아래 JSON 배열만 출력하라 (설명·코드블록 없이 순수 JSON):\n"
        '[{"i":0,"type":"논문유형(예: 원저/리뷰/방법론)","method":"핵심 방법론 한 줄",'
        '"result":"핵심 결과 한 줄","relevance":"낮음|보통|높음","why":"관련도 이유 한 줄"}, ...]\n'
        "모든 값은 한국어로 간결하게. 논문 목록:\n\n" + "\n\n".join(items)
    )


def apply_enrich(papers, text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text[4:] if text.startswith("json") else text
    enrich = json.loads(text[text.index("["): text.rindex("]") + 1])
    by_i = {int(e["i"]): e for e in enrich}
    for i, p in enumerate(papers):
        e = by_i.get(i, {})
        p["type"] = e.get("type", "")
        p["method"] = e.get("method", "")
        p["result"] = e.get("result", "")
        p["relevance"] = e.get("relevance", "")
        p["why"] = e.get("why", "")


def find_claude_cli():
    """설치된 claude CLI 경로 탐색 (launchd는 PATH가 좁으므로 절대경로 우선)."""
    import shutil

    for c in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude",
              os.path.expanduser("~/.local/bin/claude")):
        if os.path.exists(c):
            return c
    return shutil.which("claude")


def _claude_api(prompt, cfg, api_key, timeout=180):
    body = json.dumps({
        "model": cfg["claude_model"],
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(blk.get("text", "") for blk in data.get("content", []))


def _claude_cli(prompt, claude_path, timeout=240):
    import subprocess

    proc = subprocess.run([claude_path, "-p"], input=prompt,
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"rc={proc.returncode}: {proc.stderr.strip()[:200]}")
    return proc.stdout


def claude_backend(cfg, secrets):
    """API 키 > 로그인된 claude CLI > 없음. 프롬프트를 받아 텍스트를 주는 함수를 돌려준다."""
    key = secrets.get("ANTHROPIC_API_KEY")
    if key:
        log("Claude 백엔드: Anthropic API")
        return lambda prompt: _claude_api(prompt, cfg, key)
    path = find_claude_cli()
    if path:
        log(f"API 키 없음 — 로그인된 claude CLI 사용: {path}")
        return lambda prompt: _claude_cli(prompt, path)
    log("API 키·claude CLI 모두 없음 — 사전선별·요약 생략.")
    return None


def build_prescreen_prompt(category, cands, cfg):
    items = [f"[{i}] {p['title']}  ({p['journal']})" for i, p in enumerate(cands)]
    return (
        "다음은 한 대학원생에게 추천할 '최신 논문' 후보 목록이다. 연구자 배경:\n"
        f"{cfg['researcher_context']}\n\n"
        f"카테고리: {category}\n\n"
        "이 연구자의 연구와 실제로 관련 있는 논문의 번호만 골라라. "
        "제목만 비슷하고 주제가 동떨어진 것(예: 특정 한약 처방의 약리 효과 검증, "
        "임상 진료 프로토콜, 수의·축산 생산성)은 제외한다. "
        "설명 없이 JSON 배열 하나만 출력하라. 예: [3,7,11]\n"
        "관련 있는 것이 하나도 없으면 [] 를 출력하라.\n\n"
        + "\n".join(items)
    )


def make_prescreener(cfg, ask):
    """최신 슬롯용 관련도 사전선별기. 제목+저널만 보내 토큰을 아낀다."""
    if not ask or not cfg.get("quality", {}).get("prescreen_newest", True):
        return None

    def prescreen(category, cands, cfg_):
        if not cands:
            return cands
        try:
            text = ask(build_prescreen_prompt(category, cands, cfg_)).strip()
            idx = json.loads(text[text.index("["): text.rindex("]") + 1])
            keep = [cands[i] for i in idx if isinstance(i, int) and 0 <= i < len(cands)]
            log(f"  최신 사전선별: {len(cands)} → {len(keep)}편")
            return keep or None
        except Exception as e:  # noqa: BLE001
            log(f"  최신 사전선별 실패 (전체 후보 사용): {e}")
            return None

    return prescreen


def enrich_with_claude(buckets, cfg, ask):
    """최종 선정된 논문에만 유형·방법·결과·관련도 요약을 붙인다."""
    papers = _flatten(buckets)
    if not papers or not ask:
        return
    try:
        apply_enrich(papers, ask(build_enrich_prompt(papers, cfg)))
        log(f"관련도 판정 완료 ({len(papers)}편)")
    except Exception as e:  # noqa: BLE001
        log(f"관련도 판정 실패 (기본 정보만 발송): {e}")


REL_COLOR = {"높음": "#16a34a", "보통": "#d97706", "낮음": "#9ca3af"}


def snippet(text, limit=190):
    """초록을 단어 경계에서 잘라 미리보기 문장 생성."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut + "…"


def paper_card(p, accent):
    t = html.escape(p["title"])
    authors = html.escape((p["authors"] or "")[:110])
    journal = html.escape(f"{p['journal']} · {p['year']}".strip(" ·"))
    n_cited = p.get("oa_cited") if p.get("oa_cited") is not None else p.get("cited")
    cited = f"인용 {n_cited}회" if n_cited else ""
    tier = f"저널 {p['j_tier']}(2년 평균인용 {p['j_2yr']:.1f})" if p.get("j_2yr") is not None else ""
    impact = impact_text(p)
    impact = impact if impact != "—" else ""
    warn = " · ".join(p.get("warnings") or [])
    meta = "&nbsp;·&nbsp;".join(
        [journal] + [html.escape(x) for x in [cited, impact, tier] if x]
    )
    if warn:
        meta += (f'<br><span style="color:#b45309;">⚠️ {html.escape(warn)}</span>')

    rel = p.get("relevance", "")
    rel_badge = ""
    if rel:
        c = REL_COLOR.get(rel, "#6b7280")
        rel_badge = (
            f'<span style="display:inline-block;background:{c};color:#ffffff;border-radius:12px;'
            f'padding:3px 11px;font-size:12px;font-weight:700;line-height:1.4;">관련도 {html.escape(rel)}</span>'
        )

    # AI 요약이 있으면 요약 박스, 없으면 초록 미리보기
    body = ""
    has_ai = any(p.get(k) for k in ("type", "method", "result", "why"))
    if has_ai:
        rows = ""
        for label, key in [("유형", "type"), ("방법", "method"), ("결과", "result"), ("관련 이유", "why")]:
            val = p.get(key, "")
            if val:
                rows += (
                    f'<tr>'
                    f'<td style="color:#6b7280;font-size:12px;font-weight:700;padding:2px 10px 2px 0;'
                    f'white-space:nowrap;vertical-align:top;">{label}</td>'
                    f'<td style="font-size:13px;color:#374151;padding:2px 0;line-height:1.6;">{html.escape(val)}</td>'
                    f'</tr>'
                )
        body = (
            f'<table style="width:100%;margin:10px 0 2px;border-collapse:collapse;'
            f'background:#f9fafb;border-radius:6px;">'
            f'<tr><td style="padding:8px 12px;"><table style="border-collapse:collapse;">{rows}</table></td></tr>'
            f'</table>'
        )
    elif p.get("abstract"):
        body = (
            f'<p style="margin:10px 0 2px;font-size:13px;color:#4b5563;line-height:1.65;">'
            f'{html.escape(snippet(p["abstract"]))}</p>'
        )

    return (
        f'<table role="presentation" width="100%" style="border-collapse:separate;margin:0 0 14px;">'
        f'<tr><td style="background:#ffffff;border:1px solid #e5e7eb;border-left:4px solid {accent};'
        f'border-radius:8px;padding:16px 18px;">'
        f'<a href="{html.escape(p["link"])}" style="font-size:16px;font-weight:700;color:#111827;'
        f'text-decoration:none;line-height:1.5;display:block;">{t}</a>'
        + (f'<div style="margin:9px 0 3px;">{rel_badge}</div>' if rel_badge else '<div style="height:6px;"></div>')
        + f'<div style="color:#6b7280;font-size:12px;line-height:1.5;">{meta}</div>'
        f'<div style="color:#9ca3af;font-size:12px;margin-top:3px;line-height:1.5;">{authors}</div>'
        f"{body}"
        f'<div style="margin-top:12px;"><a href="{html.escape(p["link"])}" '
        f'style="font-size:13px;font-weight:600;color:{accent};text-decoration:none;">원문 보기 →</a></div>'
        f'</td></tr></table>'
    )


def build_html(buckets, cfg):
    today = dt.date.today().strftime("%Y년 %m월 %d일")
    total = sum(len(b["cited"]) + len(b["new"]) for b in buckets)
    parts = [
        '<div style="background:#f3f4f6;padding:28px 12px;font-family:-apple-system,BlinkMacSystemFont,'
        '\'Apple SD Gothic Neo\',\'Malgun Gothic\',sans-serif;">'
        '<div style="max-width:600px;margin:0 auto;">'
        '<div style="text-align:center;margin-bottom:24px;">'
        '<h1 style="font-size:23px;color:#111827;margin:0 0 6px;font-weight:800;">📚 이번 주 논문</h1>'
        f'<p style="color:#6b7280;font-size:13px;margin:0;">{today}&nbsp;·&nbsp;총 {total}편</p></div>'
    ]
    for b in buckets:
        n = len(b["cited"]) + len(b["new"])
        parts.append(
            f'<h2 style="font-size:17px;color:#111827;font-weight:800;margin:26px 0 12px;'
            f'padding-bottom:8px;border-bottom:2px solid #d1d5db;">'
            f'{html.escape(b["category"])} '
            f'<span style="font-size:13px;color:#9ca3af;font-weight:600;">{n}편</span></h2>'
        )
        if b["cited"]:
            parts.append(
                '<p style="font-size:12px;color:#2563eb;font-weight:700;margin:0 0 8px;'
                'letter-spacing:0.02em;">🔵 최근 2년 피인용 상위</p>'
            )
            for p in b["cited"]:
                parts.append(paper_card(p, "#2563eb"))
        if b["new"]:
            parts.append(
                '<p style="font-size:12px;color:#ea580c;font-weight:700;margin:6px 0 8px;'
                'letter-spacing:0.02em;">🟠 최신 논문</p>'
            )
            for p in b["new"]:
                parts.append(paper_card(p, "#ea580c"))
    parts.append(
        '<p style="color:#9ca3af;font-size:11px;margin-top:32px;text-align:center;line-height:1.6;">'
        'Europe PMC 데이터로 자동 생성 · 카테고리 수정: '
        '_Tools/paper-digest/config.json</p></div></div>'
    )
    return "\n".join(parts)


def send_email(html_body, cfg, secrets):
    pw = secrets.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not pw:
        return False
    today = dt.date.today().strftime("%m/%d")
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = f"📚 이번 주 논문 — {today}"
    msg["From"] = formataddr((cfg["sender_name"], cfg["sender_email"]))
    msg["To"] = cfg["recipient_email"]
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=SSL_CTX) as s:
        s.login(cfg["sender_email"], pw)
        s.sendmail(cfg["sender_email"], [cfg["recipient_email"]], msg.as_string())
    log(f"이메일 발송 완료 → {cfg['recipient_email']}")
    return True


REL_EMOJI = {"높음": "🟢 높음", "보통": "🟡 보통", "낮음": "⚪ 낮음"}


def impact_text(p):
    """FWCI = 같은 분야·같은 해 논문 평균 대비 몇 배 인용됐나. 리뷰·분야 크기 편향을 걷어낸 값."""
    fwci = p.get("fwci")
    cited = p.get("oa_cited")
    if fwci is None or (cited is not None and cited < 5):
        return "—"  # 인용이 적으면 FWCI가 불안정하다
    parts = [f"FWCI {fwci:.1f}배"]
    if p.get("pct_top1"):
        parts.append("분야 상위 1%")
    elif p.get("pct_top10"):
        parts.append("분야 상위 10%")
    return " · ".join(parts)


def journal_text(p):
    name = p.get("j_name") or p.get("journal") or ""
    if p.get("j_2yr") is None:
        return f"{name} · 지표 없음" if name else ""
    bits = f"2년 평균인용 {p['j_2yr']:.1f}"
    if p.get("j_h"):
        bits += f" · h-index {p['j_h']}"
    out = f"**{name}** · {p.get('j_tier', '')} ({bits})"
    if p.get("j_pub"):
        out += f" · {p['j_pub']}"
    return out


def paper_embed(p, color):
    """디스코드 embed 1개(논문 1편).

    인용·저널·신뢰를 한 점수로 섞지 않고 나란히 보여준다. 판단은 사용자 몫.
    """
    fields = []
    # 1줄: 유형 / 인용 / 영향력
    if p.get("type"):
        fields.append({"name": "유형", "value": p["type"][:250], "inline": True})
    cited = p.get("oa_cited")
    if cited is None:
        cited = p.get("cited")
    if cited is not None:
        fields.append({"name": "인용", "value": f"{cited}회", "inline": True})
    fields.append({"name": "영향력", "value": impact_text(p), "inline": True})

    jt = journal_text(p)
    if jt:
        fields.append({"name": "📕 저널", "value": jt[:1000], "inline": False})
    if p.get("warnings"):
        fields.append({"name": "⚠️ 주의", "value": " · ".join(p["warnings"])[:1000],
                       "inline": False})
    if p.get("method"):
        fields.append({"name": "📊 모델·방법", "value": p["method"][:1000], "inline": False})
    if p.get("result"):
        fields.append({"name": "🎯 핵심 결과", "value": p["result"][:1000], "inline": False})
    if p.get("relevance"):
        rel = REL_EMOJI.get(p["relevance"], p["relevance"])
        why = f" — {p['why']}" if p.get("why") else ""
        fields.append({"name": "🔗 연결성", "value": (rel + why)[:1000], "inline": False})

    byline = " · ".join(x for x in [(p.get("authors") or "")[:80],
                                    f"{p['journal']} {p['year']}".strip()] if x)
    foot_bits = [f"PMID {p['pmid']}" if p.get("pmid") else "",
                 f"DOI {p['doi']}" if p.get("doi") else ""]
    if p.get("rcr") is not None:
        foot_bits.append(f"RCR {p['rcr']:.2f}")
    foot = " · ".join(x for x in foot_bits if x)
    embed = {
        "title": (p["title"] or "제목 없음")[:250],
        "url": p["link"],
        "color": color,
        "fields": fields,
    }
    if byline:
        embed["author"] = {"name": byline[:256]}
    if foot:
        embed["footer"] = {"text": foot[:2000]}
    if not p.get("method") and p.get("abstract"):
        embed["description"] = snippet(p["abstract"], 300)
    return embed


def _discord_post(webhook_url, payload):
    import urllib.error

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "weekly-paper-digest/1.0"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limit
                time.sleep(2)
                continue
            log(f"  디스코드 오류 {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")
            return False
        except Exception as e:  # noqa: BLE001
            log(f"  디스코드 재시도 {attempt + 1}/3: {e}")
            time.sleep(2)
    return False


def send_discord(buckets, cfg, webhook_url):
    """카테고리별로 헤더 + embed(최대 10개/메시지)를 웹훅으로 발송."""
    today = dt.date.today().strftime("%Y-%m-%d")
    total = sum(len(b["cited"]) + len(b["new"]) for b in buckets)
    ok = _discord_post(webhook_url, {
        "content": f"# 📚 이번 주 논문\n**{today}** · 총 {total}편",
    })
    for b in buckets:
        embeds = [paper_embed(p, 0x2563EB) for p in b["cited"]]
        embeds += [paper_embed(p, 0xEA580C) for p in b["new"]]
        # 디스코드는 메시지당 embed 10개 제한 → 안전하게 분할
        header = f"## {b['category']}  🔵피인용 {len(b['cited'])} · 🟠최신 {len(b['new'])}"
        for i in range(0, len(embeds), 10):
            chunk = embeds[i:i + 10]
            payload = {"embeds": chunk}
            if i == 0:
                payload["content"] = header
            ok = _discord_post(webhook_url, payload) and ok
            time.sleep(0.6)
    if ok:
        log(f"디스코드 발송 완료 ({total}편)")
    return ok


def save_preview(html_body):
    out = os.path.join(BASE, "logs", f"preview_{dt.date.today()}.html")
    doc = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>이번 주 논문 미리보기</title></head><body>"
        + html_body + "</body></html>"
    )
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    log(f"미리보기 저장: {out}")


def main(dry_run=False):
    log("=== 이번 주 논문 수집 시작 ===")
    cfg = load_config()
    secrets = load_secrets()

    # 1) 후보 수집 (카테고리당 넉넉히)
    buckets = collect_candidates(cfg)
    pool = _pool(buckets)
    if not pool:
        log("수집된 논문이 없습니다. 종료.")
        return 1

    # 2) 검증: 실측 인용수·FWCI·철회 여부·저널 지표
    openalex_enrich(pool)
    journal_metrics(pool)

    # 3) 신뢰 필터 → 선별 (최신 슬롯은 Claude 사전선별)
    ask = claude_backend(cfg, secrets)
    hist = select_papers(buckets, cfg, make_prescreener(cfg, ask))
    selected = _flatten(buckets)
    if not selected:
        log("필터를 통과한 논문이 없습니다. 종료.")
        return 1

    # 4) 선정된 논문만 RCR 보강 + 요약 생성
    fetch_icite(buckets)
    enrich_with_claude(buckets, cfg, ask)

    # 5) 설정된 채널로 발송 (여러 개면 모두)
    if dry_run:
        log("--dry-run: 발송 생략, 미리보기 HTML만 저장.")
        save_preview(build_html(buckets, cfg))
        log("=== 완료 (dry-run) ===")
        return 0

    sent = False
    if secrets.get("DISCORD_WEBHOOK_URL"):
        sent = send_discord(buckets, cfg, secrets["DISCORD_WEBHOOK_URL"]) or sent
    if secrets.get("GMAIL_APP_PASSWORD"):
        sent = send_email(build_html(buckets, cfg), cfg, secrets) or sent
    if not sent:
        log("발송 채널 미설정 — 미리보기 HTML만 저장.")
        save_preview(build_html(buckets, cfg))

    # 발송에 성공했을 때만 이력에 남긴다 (실패분은 다음 주에 다시 후보가 된다)
    if sent:
        save_history(hist, selected)
        save_manifest(buckets)
    log("=== 완료 ===")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(dry_run="--dry-run" in sys.argv))
    except Exception as e:  # noqa: BLE001
        log(f"치명적 오류: {e}")
        sys.exit(1)
