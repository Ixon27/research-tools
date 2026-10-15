#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
연구노트 -> 단일 self-contained HTML 빌더 + 파일 감시기.

각 실험(## YYYY.MM.DD — 제목)에서 아래 필드를 추출해 카드로 렌더:
  실험일자 · 이름 · 실험제목 · 실험목적 · 실험 내용 · 결과·해석 · 주의할 점 및 보완할 점
(실험 재료/원본 메모 등 내부용·타인이 볼 필요 없는 항목은 제외)

- 상단에 월별 실험 캘린더(실험한 날 하이라이트 + 클릭 시 해당 실험으로 이동)
- 내부 파일 참조([[위키링크]])는 읽는 사람에게 의미 없으므로 링크 없이 텍스트로 정리,
  '상세: [[..]]' 류 참조 안내와 부록 섹션은 아예 숨김(SHOW_APPENDIX)
- --watch 로 실행하면 볼트 변경 시 자동 재빌드

의존성: python3, pandoc
"""
import base64
import calendar
import hashlib
import html
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

# ---- 설정 ------------------------------------------------------------------
# 볼트 경로: 환경변수 VAULT, 없으면 이 스크립트가 <볼트>/_Tools/notebook-html/ 에 있다고 보고 두 단계 위
VAULT = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2]).expanduser()
NOTES_DIR = VAULT / "01_Research" / "연구노트"
OUTPUT = Path(os.environ.get("NOTEBOOK_HTML_OUT", "~/Dropbox/연구노트/연구노트.html")).expanduser()
# 연구노트가 아닌 파일(작성 지침·색인 등)은 렌더 대상에서 제외.
# 예: 연구노트/AGENTS.md 는 "실험목적/실험 내용" 필드를 설명하는 지침이라
#     그대로 두면 그 예시 헤딩이 실험 카드로 잘못 렌더된다.
EXCLUDE_STEMS = {"AGENTS", "CLAUDE", "README"}
# 부록(위키링크로 모은 참조 문서) 섹션·사이드바 노출 여부.
# 연구노트는 그날 본문만으로 완결되므로 외부 공유 html에서는 숨긴다.
SHOW_APPENDIX = False
POLL_SECONDS = 2
TITLE = "연구노트"
PANDOC = shutil.which("pandoc") or "/opt/homebrew/bin/pandoc"
WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"]
calendar.setfirstweekday(6)  # 일요일 시작
# ---------------------------------------------------------------------------

# ---- 노트 인덱스 & 상호참조 레지스트리 -------------------------------------
NOTE_INDEX = {}          # name(NFC, 확장자 제외) -> [Path, ...] (볼트 전역 .md)
ENTRY_FILE_ANCHOR = {}   # 연구노트 파일 stem -> 그 파일 첫 엔트리 anchor
APPENDIX = {}            # base(NFC) -> {anchor,title,path,group,body_md,...}


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def note_md_files():
    """연구노트 폴더의 렌더 대상 .md만 반환 (AGENTS.md·CLAUDE.md 등 메타 파일 제외)."""
    return [p for p in NOTES_DIR.rglob("*.md")
            if norm(p.stem) not in EXCLUDE_STEMS]


def build_note_index():
    """볼트 전역 .md 파일 인덱스 (wikilink 해소용)."""
    NOTE_INDEX.clear()
    for root, _dirs, files in os.walk(VAULT):
        if ".obsidian" in root or "/.git" in root:
            continue
        for f in files:
            if f.endswith(".md"):
                NOTE_INDEX.setdefault(norm(f[:-3]), []).append(Path(root) / f)


def wl_base(target: str) -> str:
    """wikilink 타깃에서 순수 노트 base 이름 추출 ([[a/b#c|alias]] -> b)."""
    base = norm(target.split("#", 1)[0].split("/")[-1].strip())
    return base[:-3] if base.endswith(".md") else base


def resolve_note(base: str, prefer_dir=None):
    """base 이름 -> Path. 같은 폴더 우선(파일명 충돌 대비)."""
    paths = NOTE_INDEX.get(norm(base))
    if not paths:
        return None
    if prefer_dir:
        for p in paths:
            if p.parent == prefer_dir:
                return p
    return paths[0]


def slugify(text: str) -> str:
    text = norm(text).replace("/", "__").replace(" ", "-")
    out = re.sub(r"[^0-9A-Za-z가-힣_\-]", "", text)
    return out or "x" + hashlib.md5(text.encode()).hexdigest()[:8]


def strip_frontmatter(text: str):
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            return text[end + 4:].lstrip("\n"), meta
    return text, meta


def find_attachment(name: str):
    target = norm(name)
    for root, _dirs, files in os.walk(VAULT):
        if ".obsidian" in root or "/.git" in root:
            continue
        for f in files:
            if norm(f) == target:
                return Path(root) / f
    return None


def embed_image(name: str) -> str:
    p = find_attachment(name)
    if not p or not p.exists():
        return f"*[이미지: {name}]*"
    mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    data = base64.b64encode(p.read_bytes()).decode()
    return f'<img alt="{html.escape(name)}" src="data:{mime};base64,{data}">'


SRC_TAGS = "📁📝💬🔬"  # 내부 출처 마커 (타인에겐 의미 없음)


def strip_memo(text: str) -> str:
    """개인 메모 관련 내용·출처 마커 제거 (타인 공유용)."""
    # 메모를 언급하는 괄호 주석 통째 제거:  (… 메모 …)
    text = re.sub(r"\s*\([^()]*메모[^()]*\)", "", text)
    # 📝 메모 "인용" 콜아웃 제거
    text = re.sub(r'📝️?\s*메모\s*"[^"]*"\.?', "", text)
    # 출처 이모지 마커 제거 (📁 자료 / 📝 메모 / 💬 카톡 등)
    text = re.sub(rf"[{SRC_TAGS}]️?\s*", "", text)
    return text


def fix_cjk_bold(text: str) -> str:
    """한글 경계에서 pandoc이 못 잡는 **굵게** 를 <strong>으로 직접 변환."""
    parts = re.split(r"(```.*?```)", text, flags=re.S)  # 코드블록 보호
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"\*\*(\S(?:[^*\n]*?\S)?)\*\*",
                          r"<strong>\1</strong>", parts[i])
    return "".join(parts)


def strip_detail_refs(text: str) -> str:
    """'상세: [[..]]' 류 내부 문서 참조 안내를 html에서 제거.
    읽는 사람에겐 의미 없는 내부 링크 안내라, 위키링크를 텍스트로 바꾸기 전에 통째로 뺀다.
    (위키링크가 뒤따르는 '상세…'만 대상 — '상세시트'·'상세는 별도 기록' 같은 실제 내용은 보존.)"""
    # 1) 불릿+(출처태그)+짧은 라벨+상세+링크로만 이뤄진 순수 참조 리스트 항목 → 줄 통째 제거
    text = re.sub(
        r"(?m)^[ \t]*[-*][ \t]*(?:[📁📝💬🔬]️?\s*)?[^\n\[.]*?상세[^\n\[.]*?"
        r"(?:\[\[[^\]]+?\]\][ \t·]*)+\.?[ \t]*$",
        "", text)
    # 2) 문장 중간·끝에 붙은 '상세 … [[..]]' 참조 꼬리 제거 (앞 문장은 보존)
    text = re.sub(
        r"상세[^\n\[.]*?(?:\[\[[^\]]+?\]\][ \t·]*)+\.?",
        "", text)
    # 3) 참조가 빠져 빈 껍데기가 된 리스트 항목 삭제
    text = re.sub(r"(?m)^[ \t]*[-*][ \t]*$\n?", "", text)
    return text


def clean_refs(text: str) -> str:
    """내부 참조·메모 정리 + CJK 굵게 보정."""
    text = re.sub(r"!\[\[([^\]]+?)\]\]",
                  lambda m: embed_image(m.group(1).split("|")[0].strip()), text)
    text = strip_detail_refs(text)

    def link_sub(m):
        # 위키링크는 읽는 사람에게 의미 없는 내부 참조 → 링크 없이 라벨 텍스트만 남긴다.
        target, _, alias = m.group(1).partition("|")
        return (alias or target.strip()).strip()
    text = re.sub(r"\[\[([^\]]+?)\]\]", link_sub, text)
    text = strip_memo(text)
    text = fix_cjk_bold(text)
    return re.sub(r"[ \t]{2,}", " ", text)


def inline_plain(text: str) -> str:
    """짧은 필드(제목/이름/일자)용: 마크다운 마커 제거한 순수 텍스트."""
    text = re.sub(r"\[\[([^\]]+?)\]\]",
                  lambda m: m.group(1).split("|")[-1].strip(), text)
    text = strip_memo(text)
    text = re.sub(r"[*`]+", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


MERMAID_RE = re.compile(
    r'<pre class="mermaid"><code>(.*?)</code></pre>', re.S)


def render_mermaid(h: str) -> str:
    """pandoc의 mermaid 코드블록을 mermaid.js가 읽는 형태로 변환."""
    return MERMAID_RE.sub(r'<pre class="mermaid">\1</pre>', h)


def md_html(text: str, shift: int = 0) -> str:
    """markdown -> html (pandoc). 빈 문자열은 그대로.
    shift>0 이면 heading 레벨을 낮춤(부록 문서용)."""
    text = clean_refs(text).strip()
    if not text:
        return ""
    cmd = [PANDOC, "-f", "gfm+tex_math_dollars", "-t", "html", "--mathml"]
    if shift:
        cmd.append(f"--shift-heading-level-by={shift}")
    res = subprocess.run(
        cmd, input=text.encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return render_mermaid(res.stdout.decode("utf-8"))


# ---- 필드 매핑 (#### 소제목 -> 표준 키) -----------------------------------
def field_key(heading: str):
    h = heading.strip()
    if h.startswith("실험일자"):
        return "date"
    if h.startswith("이름"):
        return "name"
    if h.startswith("실험제목"):
        return "title"
    if h.startswith("실험목적"):
        return "purpose"
    if h.startswith("실험 내용") or h.startswith("실험내용"):
        return "content"
    if h.startswith("주의"):
        return "cautions"
    if h.startswith("결과") or h.startswith("해석"):
        return "result"
    return None  # 재료/원본메모/출처 등은 제외


def parse_entry_fields(body: str) -> dict:
    """엔트리 본문(#### ...)을 필드 dict 로."""
    fields = {}
    parts = re.split(r"^####\s+(.+?)\s*$", body, flags=re.M)
    # parts[0] = 소제목 이전 텍스트(무시), 이후 [heading, content, heading, content...]
    for i in range(1, len(parts) - 1, 2):
        key = field_key(parts[i])
        if key and key not in fields:
            fields[key] = parts[i + 1].strip()
    return fields


DATE_RE = re.compile(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})")


def parse_date(date_text: str):
    m = DATE_RE.search(date_text or "")
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            datetime(y, mo, d)
            return (y, mo, d)
        except ValueError:
            return None
    return None


def expand_dates(date_text: str):
    """실험일자 텍스트에서 실제 실험한 날들을 모두 반환.
    범위(A – B)면 A~B 전 구간을, 단일이면 그 날만. (y,m,d) 리스트."""
    found = []
    for m in DATE_RE.finditer(date_text or ""):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            found.append(datetime(y, mo, d))
        except ValueError:
            pass
    if not found:
        return []
    start, end = found[0], found[-1]
    if end < start or (end - start).days > 180:  # 비정상/개방형 범위는 시작만
        return [(start.year, start.month, start.day)]
    days, cur = [], start
    while cur <= end:
        days.append((cur.year, cur.month, cur.day))
        cur += timedelta(days=1)
    return days


def collect_entries():
    """모든 노트에서 실험 엔트리 추출. dict 리스트 반환."""
    entries = []
    files = sorted(note_md_files(), key=lambda p: norm(str(p)).lower())
    for p in files:
        rel = norm(str(p.relative_to(NOTES_DIR)))
        group = rel.split("/")[0]
        raw = p.read_text(encoding="utf-8")
        body, meta = strip_frontmatter(raw)
        default_name = meta.get("이름", "")
        # ## 헤딩으로 엔트리 분할
        chunks = re.split(r"^##\s+(?!#)(.+?)\s*$", body, flags=re.M)
        for i in range(1, len(chunks) - 1, 2):
            heading = chunks[i].strip()
            content = chunks[i + 1]
            f = parse_entry_fields(content)
            # 실험이 아닌 내비게이션 섹션(관련 노트/목록 등)은 제외
            if not parse_date(f.get("date") or heading) and not (
                    f.get("purpose") or f.get("content") or f.get("cautions")):
                continue
            title = f.get("title") or re.sub(r"^[\d.\-–~\s]+—?\s*", "", heading)
            date_text = f.get("date") or heading
            entries.append({
                "group": group,
                "file_stem": norm(p.stem),
                "dir": p.parent,
                "heading": heading,
                "title": inline_plain(title).strip("★ ").strip(),
                "name": inline_plain(f.get("name") or default_name),
                "date_text": inline_plain(date_text),
                "date": parse_date(date_text),
                "dates": expand_dates(date_text),
                "purpose": f.get("purpose", ""),
                "content": f.get("content", ""),
                "result": f.get("result", ""),
                "cautions": f.get("cautions", ""),
                "anchor": "",  # 아래에서 채움
            })
    # 정렬: 날짜순(날짜 없는 것은 뒤로)
    entries.sort(key=lambda e: (e["date"] is None, e["date"] or (9999, 99, 99)))
    for idx, e in enumerate(entries):
        e["anchor"] = f"exp-{idx}-{slugify(e['title'])[:24]}"
    return entries


# ---- 캘린더 ---------------------------------------------------------------
def build_calendar(entries) -> str:
    by_month = {}  # (y,m) -> {day: [entry,...]}
    for e in entries:
        for (y, m, d) in e["dates"]:
            slot = by_month.setdefault((y, m), {}).setdefault(d, [])
            if e not in slot:
                slot.append(e)
    if not by_month:
        return ""
    cards = []
    for (y, m) in sorted(by_month):
        days = by_month[(y, m)]
        head = "".join(f'<div class="cal-wd">{w}</div>' for w in WEEKDAYS)
        cells = []
        for week in calendar.monthcalendar(y, m):
            for day in week:
                if day == 0:
                    cells.append('<div class="cal-cell cal-empty"></div>')
                elif day in days:
                    es = days[day]
                    tip = " · ".join(html.escape(x["title"]) for x in es)
                    cells.append(
                        f'<a class="cal-cell cal-hit" href="#{es[0]["anchor"]}" '
                        f'title="{tip}">{day}<span class="cal-dot"></span></a>')
                else:
                    cells.append(f'<div class="cal-cell">{day}</div>')
        uniq = len({id(e) for es in days.values() for e in es})
        cards.append(
            f'<div class="cal-card"><div class="cal-title">{y}년 {m}월'
            f'<span class="cal-count">{uniq}건</span>'
            f'</div><div class="cal-grid">{head}{"".join(cells)}</div></div>')
    return (
        '<section id="calendar" class="section-block">'
        '<h2 class="block-h">📅 실험 캘린더</h2>'
        '<p class="block-sub">실험한 날이 표시됩니다. 날짜를 클릭하면 해당 실험으로 이동합니다.</p>'
        f'<div class="cal-wrap">{"".join(cards)}</div></section>')


# ---- 엔트리 카드 ----------------------------------------------------------
FIELD_META = [
    ("purpose", "실험목적"),
    ("content", "실험 내용"),
    ("result", "결과·해석"),
    ("cautions", "주의할 점 및 보완할 점"),
]


def render_entry(e) -> str:
    blocks = []
    for key, label in FIELD_META:
        h = md_html(e[key])
        if h:
            blocks.append(
                f'<div class="field">'
                f'<div class="field-label">{label}</div>'
                f'<div class="field-body">{h}</div></div>')
    name = html.escape(e["name"]) or "—"
    date_disp = html.escape(e["date_text"])
    return (
        f'<article id="{e["anchor"]}" class="exp-card">'
        f'<div class="exp-head">'
        f'<span class="exp-date">{date_disp}</span>'
        f'<span class="exp-project">{html.escape(e["group"])}</span>'
        f'<span class="exp-name">{name}</span></div>'
        f'<h3 class="exp-title">{html.escape(e["title"])}</h3>'
        f'<div class="exp-body">{"".join(blocks)}</div></article>')


# ---- 부록 (재현에 필요한 상세 프로토콜·방법 문서) -----------------------
# 판단 기준: "그 실험을 모르는 사람이 보고도 재현할 수 있는" 방법·프로토콜만.
# 대시보드/개요/인덱스, 그리고 관찰일지·보고·미팅 같은 서술성 문서는 제외.
APX_EXCLUDE_EXACT = re.compile(r"^(status|claude|spec|readme)$", re.I)
APX_EXCLUDE_SUBSTR = re.compile(
    r"index|overview|개요|목차|"                      # 개요·인덱스류
    r"관찰|observation|"                               # 관찰일지
    r"report|보고|meeting|미팅|회의|리뷰|review",       # 보고·미팅·리뷰
    re.I)


def _apx_excluded(base: str) -> bool:
    return bool(APX_EXCLUDE_EXACT.match(base) or APX_EXCLUDE_SUBSTR.search(base))


def _appendix_targets(entries):
    """엔트리 본문 wikilink 중 부록 후보 (base, path, 참조 프로젝트) 수집.
    참조 프로젝트 = 그 링크를 건 연구노트 엔트리의 group (WGS·PLA_mouse …)."""
    order = []
    seen = set()
    for e in entries:
        for key in ("purpose", "content", "cautions"):
            for m in re.finditer(r"\[\[([^\]]+?)\]\]", e[key] or ""):
                base = wl_base(m.group(1).partition("|")[0])
                if not base or base in seen:
                    continue
                if base in ENTRY_FILE_ANCHOR:      # 연구노트 내부 파일 → 엔트리 링크
                    continue
                if _apx_excluded(base):            # 개요·보고·관찰 등 비재현 문서 제외
                    continue
                p = resolve_note(base, e["dir"])
                if not p or not p.exists():
                    continue
                if NOTES_DIR in p.parents:         # 노트북 파일은 엔트리로 처리
                    continue
                seen.add(base)
                order.append((base, p, e["group"]))
    return order


def collect_appendix(entries):
    """부록 문서 등록 + anchor 배정 + 본문 markdown 준비."""
    APPENDIX.clear()
    cand = _appendix_targets(entries)
    # 참조 프로젝트별로 묶고, 그 안에서 경로순 정렬
    cand.sort(key=lambda t: (norm(t[2]).lower(), norm(str(t[1])).lower()))
    apx = []
    for idx, (base, p, ref_group) in enumerate(cand):
        raw = p.read_text(encoding="utf-8")
        body, _meta = strip_frontmatter(raw)
        mt = re.match(r"\s*#\s+(.+)", body)
        if mt:
            title = inline_plain(mt.group(1))
            body = body[mt.end():]
        else:
            title = base
        info = {
            "base": base, "path": p, "title": title,
            "group": ref_group,                 # 부록 묶음 기준 = 참조한 연구노트 프로젝트
            "src": norm(p.parent.name),         # 실제 원본 폴더(카드에 표시)
            "anchor": f"apx-{idx}-{slugify(title)[:24]}",
            "body_md": body,
        }
        APPENDIX[base] = info
        apx.append(info)
    return apx


def _apx_by_group(apx):
    """부록을 참조 프로젝트별로 묶어 [(group, [info,...]), ...] 반환(순서 유지)."""
    grouped = {}
    for info in apx:
        grouped.setdefault(info["group"], []).append(info)
    return sorted(grouped.items())


def render_appendix(apx) -> str:
    if not apx:
        return ""
    blocks = []
    for g, items in _apx_by_group(apx):
        cards = []
        for info in items:
            h = md_html(info["body_md"], shift=2)  # #->h3, ##->h4 ...
            cards.append(
                f'<article id="{info["anchor"]}" class="apx-card">'
                f'<div class="apx-head">'
                f'<span class="apx-badge">📎 부록</span>'
                f'<span class="exp-project">{html.escape(info["src"])}</span></div>'
                f'<h3 class="apx-title">{html.escape(info["title"])}</h3>'
                f'<div class="apx-body field-body">{h}</div></article>')
        blocks.append(
            f'<h3 class="apx-group-h" id="apx-grp-{slugify(g)}">'
            f'🧪 {html.escape(g)}<span class="apx-group-cnt">{len(items)}건</span></h3>'
            f'{"".join(cards)}')
    return (
        '<section id="appendix" class="section-block">'
        '<h2 class="block-h">📎 부록 — 상세 프로토콜·방법</h2>'
        '<p class="block-sub">실험을 처음 보는 사람도 재현할 수 있도록, '
        '본문에서 참조하는 상세 문서를 프로젝트별로 모았습니다. '
        '본문의 링크를 클릭하면 여기로 이동합니다.</p>'
        f'{"".join(blocks)}</section>')


# ---- 사이드바 (프로젝트 클릭 시 목록 토글) -------------------------------
def render_sidebar(entries, apx) -> str:
    groups = {}
    for e in entries:
        groups.setdefault(e["group"], []).append(e)
    out = ['<a class="nav-link nav-top" href="#calendar">'
           '<span class="nav-ico">📅</span>실험 캘린더</a>']
    for g in sorted(groups):
        links = []
        for e in groups[g]:
            dm = f'{e["date"][1]:02d}.{e["date"][2]:02d} ' if e["date"] else ""
            links.append(
                f'<a class="nav-link nav-sub" href="#{e["anchor"]}">'
                f'<span class="nav-date">{dm}</span>{html.escape(e["title"])}</a>')
        out.append(
            f'<div class="nav-group">'
            f'<button class="nav-head" onclick="toggleGroup(this)">'
            f'<span class="nav-arrow">▸</span>{html.escape(g)}'
            f'<span class="nav-cnt">{len(groups[g])}</span></button>'
            f'<div class="nav-items">{"".join(links)}</div></div>')
    if apx:
        items = []
        for g, infos in _apx_by_group(apx):
            items.append(
                f'<a class="nav-apx-proj" href="#apx-grp-{slugify(g)}">'
                f'{html.escape(g)}</a>')
            items += [
                f'<a class="nav-link nav-sub" href="#{info["anchor"]}">'
                f'{html.escape(info["title"])}</a>' for info in infos]
        out.append(
            f'<div class="nav-group nav-appendix">'
            f'<button class="nav-head" onclick="toggleGroup(this)">'
            f'<span class="nav-arrow">▸</span>📎 부록'
            f'<span class="nav-cnt">{len(apx)}</span></button>'
            f'<div class="nav-items">{"".join(items)}</div></div>')
    return "".join(out)


def build():
    build_note_index()
    entries = collect_entries()
    # 연구노트 파일 stem -> 첫 엔트리 anchor (파일 단위 wikilink 점프용)
    ENTRY_FILE_ANCHOR.clear()
    for e in entries:
        ENTRY_FILE_ANCHOR.setdefault(e["file_stem"], e["anchor"])
    # 부록(재현용 상세 문서) 등록 — SHOW_APPENDIX일 때만. 꺼져 있으면 섹션·사이드바 모두 생략.
    apx = collect_appendix(entries) if SHOW_APPENDIX else []
    cal = build_calendar(entries)
    # 프로젝트별 섹션
    groups = {}
    for e in entries:
        groups.setdefault(e["group"], []).append(e)
    sections = []
    for g in sorted(groups):
        cards = "".join(render_entry(e) for e in groups[g])
        sections.append(
            f'<section id="grp-{slugify(g)}" class="section-block">'
            f'<h2 class="block-h">🧪 {html.escape(g)}</h2>{cards}</section>')
    doc = TEMPLATE.format(
        title=html.escape(TITLE),
        sidebar=render_sidebar(entries, apx),
        calendar=cal,
        sections="".join(sections),
        appendix=render_appendix(apx),
        built_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        count=len(entries),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(doc, encoding="utf-8")
    return len(entries)


TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
:root{{--sb1:#1a2332;--sb2:#2c3e50;--primary:#4a90d9;--info:#36b9cc;
  --warning:#f6c23e;--bg:#f6f8fb;--card:#fff;--text:#4b4d57;
  --dark:#33353f;--light:#8b8fa3;--muted:#b7b9cc;--border:#e6e9f0;
  --shadow:0 .15rem 1.5rem rgba(58,59,69,.12);--radius:12px}}
body{{font-family:'Nunito','Noto Sans KR',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--bg);color:var(--text);line-height:1.7;font-size:15px}}
a{{color:inherit;text-decoration:none}}
#wrap{{display:flex;min-height:100vh}}
/* 사이드바 */
.sidebar{{position:fixed;top:0;left:0;width:250px;height:100vh;
  background:linear-gradient(180deg,var(--sb1),var(--sb2));color:rgba(255,255,255,.82);
  overflow-y:auto;z-index:100;padding-bottom:30px}}
.brand{{display:flex;align-items:center;gap:10px;padding:20px 18px 14px;
  font-size:18px;font-weight:800;color:#fff;letter-spacing:-.3px}}
.brand-sub{{padding:0 18px 12px;font-size:11px;color:rgba(255,255,255,.4)}}
.sb-search{{margin:0 14px 10px;width:calc(100% - 28px);padding:9px 14px;border:none;
  border-radius:999px;font-size:13px;font-family:inherit;background:rgba(255,255,255,.12);
  color:#fff}}
.sb-search::placeholder{{color:rgba(255,255,255,.5)}}
.sb-search:focus{{outline:none;background:rgba(255,255,255,.2)}}
.nav-head{{display:flex;align-items:center;gap:8px;width:100%;text-align:left;
  padding:11px 18px;font-size:13px;font-weight:800;letter-spacing:.2px;cursor:pointer;
  background:none;border:none;color:rgba(255,255,255,.9);font-family:inherit}}
.nav-head:hover{{background:rgba(255,255,255,.06)}}
.nav-arrow{{font-size:9px;transition:transform .18s;color:rgba(255,255,255,.55)}}
.nav-group.open .nav-arrow{{transform:rotate(90deg)}}
.nav-cnt{{margin-left:auto;font-size:10.5px;font-weight:700;color:rgba(255,255,255,.55);
  background:rgba(255,255,255,.12);padding:1px 8px;border-radius:999px}}
.nav-items{{display:none}}
.nav-group.open .nav-items{{display:block;padding-bottom:4px}}
.nav-link{{display:flex;align-items:center;gap:8px;padding:8px 18px;font-size:13.5px;
  font-weight:600;color:rgba(255,255,255,.8);border-left:3px solid transparent}}
.nav-link:hover{{color:#fff;background:rgba(255,255,255,.08);border-left-color:rgba(255,255,255,.35)}}
.nav-top{{margin-bottom:6px}}
.nav-sub{{font-weight:500;font-size:12.5px;padding:6px 16px 6px 30px;color:rgba(255,255,255,.66);
  line-height:1.4}}
.nav-ico{{width:18px;text-align:center}}
.nav-date{{color:var(--primary);font-weight:700;font-size:11px;flex:0 0 auto}}
/* 본문 */
#main{{margin-left:250px;flex:1;min-width:0}}
.topbar{{position:sticky;top:0;z-index:50;height:60px;display:flex;align-items:center;
  gap:14px;padding:0 28px;background:var(--card);box-shadow:0 .1rem .6rem rgba(58,59,69,.08)}}
.topbar h1{{font-size:17px;font-weight:800;color:var(--dark)}}
.topbar .meta{{margin-left:auto;font-size:12px;color:var(--light)}}
.container{{max-width:960px;margin:0 auto;padding:26px 28px 90px}}
.section-block{{margin-bottom:34px}}
.block-h{{font-size:20px;font-weight:800;color:var(--dark);margin-bottom:6px;
  padding-bottom:8px;border-bottom:2px solid var(--border)}}
.block-sub{{font-size:13px;color:var(--light);margin-bottom:16px}}
/* 캘린더 */
.cal-wrap{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}}
.cal-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:14px 16px}}
.cal-title{{font-weight:800;color:var(--dark);font-size:15px;margin-bottom:10px;
  display:flex;align-items:center;justify-content:space-between}}
.cal-count{{font-size:11px;font-weight:700;color:var(--primary);background:#eaf2fb;
  padding:2px 9px;border-radius:999px}}
.cal-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}}
.cal-wd{{text-align:center;font-size:10.5px;font-weight:700;color:var(--muted);padding:2px 0}}
.cal-cell{{position:relative;aspect-ratio:1;display:flex;align-items:center;justify-content:center;
  font-size:12px;color:var(--text);border-radius:7px}}
.cal-empty{{visibility:hidden}}
.cal-hit{{background:var(--primary);color:#fff;font-weight:800;cursor:pointer;
  box-shadow:0 2px 6px rgba(74,144,217,.4)}}
.cal-hit:hover{{background:#3a7bc0;transform:translateY(-1px)}}
.cal-dot{{position:absolute;bottom:3px;width:4px;height:4px;border-radius:50%;background:#fff}}
/* 실험 카드 (미니멀·세련) */
.exp-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:24px 28px;margin-bottom:16px;transition:box-shadow .15s}}
.exp-card:hover{{box-shadow:0 .3rem 2rem rgba(58,59,69,.16)}}
.exp-head{{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}}
.exp-date{{font-size:12px;font-weight:800;color:var(--primary);letter-spacing:.2px}}
.exp-project{{font-size:10.5px;font-weight:700;color:var(--light);
  padding:2px 9px;border-radius:999px;background:var(--bg);border:1px solid var(--border)}}
.exp-name{{margin-left:auto;font-size:11.5px;font-weight:600;color:var(--muted)}}
.exp-title{{font-size:19px;font-weight:800;color:var(--dark);line-height:1.4;
  margin:0 0 6px;padding-bottom:14px;border-bottom:1px solid var(--border)}}
.field{{padding:14px 0}}
.field + .field{{border-top:1px solid #f0f2f6}}
.field-label{{position:relative;font-size:11px;font-weight:800;letter-spacing:.6px;
  color:var(--light);text-transform:uppercase;margin-bottom:9px;padding-left:11px}}
.field-label::before{{content:'';position:absolute;left:0;top:1px;width:3px;height:12px;
  background:var(--primary);border-radius:2px}}
.field-body{{font-size:14.5px;color:#3f4149}}
.field-body p{{margin:0 0 9px}}
.field-body p:last-child{{margin-bottom:0}}
.field-body ul,.field-body ol{{padding-left:20px;margin:6px 0}}
.field-body li{{margin:3px 0}}
.field-body h5,.field-body h6{{font-size:14px;font-weight:700;color:var(--dark);margin:10px 0 4px}}
.field-body blockquote{{border-left:3px solid var(--muted);padding:6px 14px;margin:9px 0;
  background:#fff;color:#6b6e7b;border-radius:0 6px 6px 0}}
.field-body code{{background:#eef1f6;padding:1px 6px;border-radius:4px;font-size:13px}}
.field-body pre{{background:#2f3340;color:#e6e6e6;padding:12px 14px;border-radius:8px;
  overflow-x:auto;font-size:13px;margin:8px 0}}
.field-body pre code{{background:none;padding:0}}
.field-body table{{border-collapse:collapse;margin:10px 0;font-size:13.5px;width:100%}}
.field-body th,.field-body td{{border:1px solid var(--border);padding:6px 11px;text-align:left}}
.field-body th{{background:var(--bg);font-weight:700}}
.field-body img{{max-width:100%;border-radius:8px;margin:6px 0}}
/* 본문 → 부록 점프 링크 */
.field-body a[href^="#"]{{color:var(--primary);font-weight:700;
  border-bottom:1px dashed var(--primary);padding-bottom:1px}}
.field-body a[href^="#"]:hover{{background:#eaf2fb;border-radius:3px}}
.field-body a[href^="#"]::after{{content:'↗';font-size:10px;margin-left:2px;
  vertical-align:super;color:var(--info)}}
/* 스크롤 시 sticky topbar 가림 방지 */
.exp-card,.apx-card,.section-block,.apx-group-h{{scroll-margin-top:74px}}
/* 부록 카드 */
.nav-appendix .nav-head{{color:var(--info)}}
.apx-card{{background:var(--card);border:1px solid var(--border);
  border-left:4px solid var(--info);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:22px 26px;margin-bottom:16px}}
.apx-head{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.apx-badge{{font-size:10.5px;font-weight:800;color:#fff;background:var(--info);
  padding:2px 10px;border-radius:999px;letter-spacing:.3px}}
.apx-group-h{{font-size:16px;font-weight:800;color:var(--info);
  margin:26px 0 12px;padding-bottom:7px;border-bottom:2px dashed var(--info);
  display:flex;align-items:center;justify-content:space-between}}
.apx-group-h:first-child{{margin-top:6px}}
.apx-group-cnt{{font-size:11px;font-weight:700;color:var(--info);
  background:#e8f7fa;padding:2px 9px;border-radius:999px}}
.nav-apx-proj{{display:block;padding:7px 16px 3px 24px;font-size:11px;
  font-weight:800;letter-spacing:.4px;color:var(--info);text-transform:uppercase}}
.apx-title{{font-size:18px;font-weight:800;color:var(--dark);line-height:1.4;
  margin:0 0 12px;padding-bottom:12px;border-bottom:1px solid var(--border)}}
.apx-body h3{{font-size:16.5px;font-weight:800;color:var(--dark);
  margin:18px 0 8px;padding-top:6px}}
.apx-body h4{{font-size:15px;font-weight:700;color:var(--dark);margin:14px 0 6px}}
.apx-body h5,.apx-body h6{{font-size:13.5px;font-weight:700;color:var(--sb2);
  margin:10px 0 4px}}
.apx-body blockquote{{border-left:3px solid var(--info);background:#f0fafc}}
/* mermaid: 코드블록(어두운) 스타일 상속 끊고 밝은 카드로 */
.field-body pre.mermaid{{background:#fbfcfe;color:inherit;padding:12px;
  border:1px solid var(--border);border-radius:10px;text-align:center;
  margin:14px 0;overflow-x:auto;font-family:inherit;line-height:1.4}}
.footer{{text-align:center;color:var(--muted);font-size:12px;margin-top:30px;
  padding-top:18px;border-top:1px solid var(--border)}}
.hidden{{display:none!important}}
/* 반응형 */
.hamburger{{display:none}}
@media(max-width:820px){{
  .sidebar{{transform:translateX(-100%);transition:transform .2s;width:250px}}
  .sidebar.open{{transform:translateX(0)}}
  #main{{margin-left:0}}
  .hamburger{{display:block;background:none;border:none;font-size:22px;cursor:pointer;color:var(--dark)}}
}}
.sidebar::-webkit-scrollbar{{width:5px}}
.sidebar::-webkit-scrollbar-thumb{{background:rgba(255,255,255,.2);border-radius:10px}}
</style>
</head>
<body>
<div id="wrap">
  <aside class="sidebar" id="sidebar">
    <div class="brand">🧬 {title}</div>
    <div class="brand-sub">실험 {count}건 · {built_at} 갱신</div>
    <input class="sb-search" type="text" placeholder="실험 검색…" oninput="doSearch(this.value)">
    <nav>{sidebar}</nav>
  </aside>
  <div id="main">
    <div class="topbar">
      <button class="hamburger" onclick="document.getElementById('sidebar').classList.toggle('open')">☰</button>
      <h1>🧬 {title}</h1>
      <span class="meta">실험 {count}건 · 자동 갱신</span>
    </div>
    <div class="container">
      {calendar}
      {sections}
      {appendix}
      <div class="footer">자동 생성 · {built_at} · 볼트 변경 시 자동 갱신됩니다</div>
    </div>
  </div>
</div>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{
    startOnLoad:true, securityLevel:'loose', theme:'base',
    themeVariables:{{
      background:'#fbfcfe',
      primaryColor:'#eaf2fb', primaryTextColor:'#33353f',
      primaryBorderColor:'#4a90d9', lineColor:'#8b8fa3',
      secondaryColor:'#f6f8fb', tertiaryColor:'#ffffff',
      fontFamily:'Nunito, "Noto Sans KR", sans-serif', fontSize:'14px'
    }}
  }});
</script>
<script>
function toggleGroup(btn){{ btn.parentElement.classList.toggle('open'); }}
function doSearch(q){{
  q=q.trim().toLowerCase();
  document.querySelectorAll('.exp-card,.apx-card').forEach(function(c){{
    c.classList.toggle('hidden', q && c.textContent.toLowerCase().indexOf(q)===-1);
  }});
  document.querySelectorAll('.section-block').forEach(function(s){{
    if(s.id==='calendar')return;
    var vis=s.querySelectorAll('.exp-card:not(.hidden),.apx-card:not(.hidden)').length;
    s.classList.toggle('hidden', q && vis===0);
  }});
  document.querySelectorAll('.nav-group').forEach(function(g){{
    var hit=false;
    g.querySelectorAll('.nav-sub').forEach(function(a){{
      var m=!q || a.textContent.toLowerCase().indexOf(q)!==-1;
      a.classList.toggle('hidden', !m);
      if(m && q) hit=true;
    }});
    if(q) g.classList.toggle('open', hit);   // 검색 시 매칭 그룹 펼침
  }});
}}
</script>
</body>
</html>
"""


def snapshot():
    snap = {}
    for p in note_md_files():
        try:
            snap[str(p)] = p.stat().st_mtime
        except OSError:
            pass
    return snap


def main():
    watch = "--watch" in sys.argv
    n = build()
    print(f"[{datetime.now():%H:%M:%S}] 빌드 완료: 실험 {n}건 -> {OUTPUT}")
    if not watch:
        return
    print(f"감시 시작 (폴링 {POLL_SECONDS}s). Ctrl+C 종료.")
    last = snapshot()
    while True:
        time.sleep(POLL_SECONDS)
        cur = snapshot()
        if cur != last:
            last = cur
            try:
                n = build()
                print(f"[{datetime.now():%H:%M:%S}] 변경 감지 -> 재빌드: {n}건")
            except Exception as e:  # noqa
                print(f"[{datetime.now():%H:%M:%S}] 오류: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
