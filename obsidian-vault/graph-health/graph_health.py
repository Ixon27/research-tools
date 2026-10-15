#!/usr/bin/env python3
"""graph_health.py — Obsidian 볼트 그래프 건강검진.

볼트의 .md 노트를 스캔해 그래프 위생 문제를 찾는다:
  1. 깨진 wikilink   — [[대상]]이 실제 노트를 가리키지 않음
  2. 고아 노트        — 들어오는 링크 0 + 어떤 MOC에도 등록 안 됨
  3. MOC 미등록 노트   — MOC-*.md 어디에서도 링크 안 됨 (그래프 연결 규칙 위반)
  4. frontmatter 결손 — tags 또는 created 누락

Obsidian 링크 해석을 모사한다(basename 우선 + 경로 링크 + 대소문자 무시).
외부 의존 없음(표준 라이브러리만).

사용법:
    python3 graph_health.py                 # 요약을 stdout에
    python3 graph_health.py --report        # 00_Inbox/graph-health-YYYY-MM-DD.md 로 리포트 저장
    python3 graph_health.py --vault <경로>  # 볼트 경로 지정(기본: 이 스크립트 기준 상위)
"""
from __future__ import annotations
import argparse
import datetime as _dt
import os
import re
import sys
import unicodedata
from collections import defaultdict

# 링크 대상 인덱스를 만들 때 절대 들어가지 않을 폴더(무거움/무관).
SKIP_WALK = {".obsidian", ".trash", ".git", "MM"}   # MM은 5.6GB 심링크 — path로만 확인
# 그래프 '노드'(고아·MOC 분석 대상)에서 제외할 폴더. (링크 대상으로는 유효)
# .claude·_Tools는 커맨드·스크립트 문서라 Obsidian 그래프 대상이 아니다.
NON_NODE_DIRS = {"_Templates", "Attachments", ".claude", "_Tools"}
# 링크 '출처'로 파싱하지 않을 문서 파일(예시 링크가 많아 노이즈).
NON_SOURCE_NAMES = {"AGENTS.md", "CLAUDE.md"}
# 'MOC 미등록' 판정 대상 — 재사용되는 개념·방법론·논문 노트만.
# 프로젝트 STATUS·SPEC·session-log는 폴더 문맥으로 찾으므로 MOC 등록 대상이 아니다.
MOC_SCOPE_PREFIXES = ("04_References/Notes", "04_References/Papers")

WIKILINK_RE = re.compile(r"!?\[\[([^\]]+?)\]\]")   # [[..]] 및 임베드 ![[..]]
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
FENCED_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)  # 코드펜스
INLINE_CODE_RE = re.compile(r"`[^`]*`")                    # 인라인 코드


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def strip_code(text: str) -> str:
    """코드펜스·인라인코드 제거 — bash `[[ ]]`·Python 리스트가 wikilink로 오인되지 않게."""
    text = FENCED_RE.sub("", text)
    return INLINE_CODE_RE.sub("", text)


def collect_files(vault: str) -> list[str]:
    """링크 대상이 될 수 있는 모든 파일(무거운/무관 폴더만 제외)."""
    out = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in SKIP_WALK]
        for f in files:
            out.append(os.path.relpath(os.path.join(root, f), vault))
    return out


def is_node(rel: str) -> bool:
    """그래프 노드(고아·MOC 분석 대상) 여부: .md이고 제외폴더/문서 아님."""
    if not rel.endswith(".md"):
        return False
    parts = rel.split(os.sep)
    if any(p in NON_NODE_DIRS for p in parts):
        return False
    if os.path.basename(rel) in NON_SOURCE_NAMES:
        return False
    return True


def parse_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key = line.split(":", 1)[0].strip()
            fm[key] = line.split(":", 1)[1].strip()
    return fm


def normalize_link(target: str) -> str:
    """[[대상|별칭]] / [[대상#섹션]] / [[대상^블록]] 에서 대상만 추출.
    표 안에서는 파이프가 `\\|`로 이스케이프되므로 그것도 별칭 구분자로 처리."""
    target = target.replace("\\|", "|")        # 표 이스케이프 파이프 복원
    target = target.split("|", 1)[0]          # 별칭 제거
    target = target.split("#", 1)[0]          # 섹션 제거
    target = target.split("^", 1)[0]          # 블록 제거
    return target.strip().rstrip("\\").strip()  # 잔여 백슬래시 제거


def build_index(vault: str, files: list[str]):
    """모든 파일을 basename(소문자)→[상대경로], 경로(소문자)→상대경로 로 색인.
    .md는 확장자 없이도 매칭되게 별칭 등록(Obsidian이 .md를 생략 허용)."""
    by_base = defaultdict(list)
    by_path = {}
    for rel in files:
        low = nfc(rel.lower())                 # NFC 통일(macOS 파일명 NFD 대응)
        by_path[low] = rel
        by_base[os.path.basename(low)].append(rel)
        if low.endswith(".md"):                # 확장자 생략 형태도 등록
            stem = low[:-3]
            by_path[stem] = rel
            by_base[os.path.basename(stem)].append(rel)
    return by_base, by_path


def resolve(target: str, by_base, by_path, vault: str, all_paths) -> str | None:
    if not target:
        return None
    key = nfc(target.lower())                  # NFC 통일
    if "/" in target:                          # 경로 링크(자산·MM 포함)
        hit = by_path.get(key) or by_path.get(key + ".md")
        if hit:
            return hit
        # Obsidian은 부분경로를 꼬리(suffix)로도 해석: 경로 끝이 일치하면 매칭.
        for cand in (key, key + ".md"):
            for low, rel in all_paths.items():
                if low == cand or low.endswith("/" + cand):
                    return rel
        # MM/ 등 심링크 실경로 확인(인덱스에 없는 폴더). 한글은 NFD/NFC 둘 다 시도.
        for form in ("NFC", "NFD"):
            p = os.path.join(vault, unicodedata.normalize(form, target))
            if os.path.exists(p):
                return target
        return None
    hits = by_base.get(key)                     # basename 링크(노트·자산 공통)
    if hits:
        return hits[0]                          # 모호하면 첫 번째(Obsidian은 최단경로)
    return None


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    default_vault = os.path.abspath(os.path.join(here, "..", ".."))
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=default_vault)
    ap.add_argument("--report", action="store_true", help="00_Inbox/에 리포트 .md 저장")
    args = ap.parse_args()
    vault = os.path.abspath(args.vault)

    files = collect_files(vault)
    by_base, by_path = build_index(vault, files)
    all_paths = {nfc(rel.lower()): rel for rel in files}   # 꼬리 경로 매칭용(NFC)
    notes = [f for f in files if is_node(f)]    # 그래프 노드(.md, 제외폴더/문서 아님)
    sources = notes                             # 링크 출처 = 노드(STATUS·session-log 포함, 템플릿·AGENTS.md·CLAUDE.md 제외)

    incoming = defaultdict(int)                 # rel → 들어오는 링크 수
    moc_registered: set[str] = set()            # MOC에서 링크된 rel
    broken: list[tuple[str, str]] = []          # (출처 rel, 깨진 대상)
    empty_links: list[str] = []                 # [[]] 빈 링크가 있는 노트
    fm_missing: list[tuple[str, list[str]]] = []

    for rel in sources:
        try:
            with open(os.path.join(vault, rel), encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue

        if is_node(rel):
            fm = parse_frontmatter(text)
            miss = [k for k in ("tags", "created") if k not in fm]
            if miss:
                fm_missing.append((rel, miss))

        is_moc = os.path.basename(rel).startswith("MOC")
        for raw in WIKILINK_RE.findall(strip_code(text)):
            # [[#섹션]] / [[^블록]] = 같은 노트 내부 링크(정상 문법). 대상이 자기 자신이라 검사 제외.
            if raw.lstrip().startswith(("#", "^")):
                continue
            tgt = normalize_link(raw)
            if not tgt:
                if rel not in empty_links:
                    empty_links.append(rel)
                continue
            dest = resolve(tgt, by_base, by_path, vault, all_paths)
            if dest is None:
                broken.append((rel, tgt))
            else:
                if dest != rel:
                    incoming[dest] += 1
                if is_moc:
                    moc_registered.add(dest)

    non_moc = [n for n in notes if not os.path.basename(n).startswith("MOC")]
    orphans = [n for n in non_moc if incoming.get(n, 0) == 0 and n not in moc_registered]
    unregistered = [n for n in non_moc
                    if n not in moc_registered
                    and n.replace(os.sep, "/").startswith(MOC_SCOPE_PREFIXES)]

    lines = []
    lines.append(f"# 그래프 헬스체크 — {_dt.date.today().isoformat()}")
    lines.append("")
    lines.append(f"스캔 노드: **{len(notes)}개** · 링크 출처 스캔: {len(sources)}개 파일 "
                 f"(노드 제외: {', '.join(sorted(NON_NODE_DIRS))}; AGENTS.md·CLAUDE.md는 출처 제외)")
    lines.append("")
    lines.append("## 요약")
    lines.append("")
    lines.append(f"- 깨진 wikilink: **{len(broken)}건**")
    lines.append(f"- 빈 링크 `[[]]`: **{len(empty_links)}개 노트**")
    lines.append(f"- 고아 노트(들어오는 링크 0 + MOC 미등록): **{len(orphans)}개**")
    lines.append(f"- MOC 미등록 노트(개념·논문 노트 한정): **{len(unregistered)}개**")
    lines.append(f"- frontmatter 결손(tags/created): **{len(fm_missing)}개**")
    lines.append("")

    def section(title, rows):
        lines.append(f"## {title} ({len(rows)})")
        lines.append("")
        if not rows:
            lines.append("_없음_")
        else:
            lines.extend(rows)
        lines.append("")

    section("깨진 wikilink", [f"- `{src}` → `[[{tgt}]]` (대상 없음)" for src, tgt in sorted(broken)])
    section("빈 링크 [[]]", [f"- `{n}`" for n in sorted(empty_links)])
    section("고아 노트", [f"- `{n}`" for n in sorted(orphans)])
    section(f"MOC 미등록 노트 ({' · '.join(MOC_SCOPE_PREFIXES)} 한정)",
            [f"- `{n}`" for n in sorted(unregistered)])
    section("frontmatter 결손", [f"- `{n}` — 누락: {', '.join(m)}" for n, m in sorted(fm_missing)])

    output = "\n".join(lines)

    if args.report:
        outdir = os.path.join(vault, "00_Inbox")
        os.makedirs(outdir, exist_ok=True)
        outpath = os.path.join(outdir, f"graph-health-{_dt.date.today().isoformat()}.md")
        header = "---\ntags: [graph-health, maintenance]\ncreated: " + _dt.date.today().isoformat() + "\n---\n\n"
        with open(outpath, "w", encoding="utf-8") as fh:
            fh.write(header + output + "\n")
        print(f"리포트 저장: {os.path.relpath(outpath, vault)}")
        # 콘솔에도 요약 6줄만
        print("\n".join(lines[:12]))
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
