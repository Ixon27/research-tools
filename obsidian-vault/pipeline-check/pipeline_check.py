#!/usr/bin/env python3
"""pipeline_check.py — Obsidian 볼트 프로젝트·논문 폴더 구조 점검.

`02_Papers/` · `03_Projects/` 의 각 폴더를 두 문서에 대조한다:
  · [[guide-02-03-폴더구조]]          — 고정 폴더 골격, 필수 4종, 넘버링·이름 규칙, AGENTS.md 상한
  · [[dry-research-pipeline]] 배치표  — 건식 파이프라인 산출물이 제 위치에 있나
  · [[research-type-registry]]        — 이 프로젝트의 연구 유형이 등록표에 있나

**산출물 부재는 오류가 아니다.** 아직 그 단계에 도달하지 않았다는 정보로 보고한다.
유형 목록을 이 스크립트에 하드코딩하지 않는다 — 등록표를 파싱한다.

외부 의존 없음(표준 라이브러리만).

사용법:
    python3 pipeline_check.py                 # 요약+상세를 stdout에
    python3 pipeline_check.py --report        # 00_Inbox/pipeline-check-YYYY-MM-DD.md 로 저장
    python3 pipeline_check.py --vault <경로>  # 볼트 경로 지정(기본: 이 스크립트 기준 상위 2단계)
    python3 pipeline_check.py --only <이름>   # 폴더 하나만
"""
from __future__ import annotations
import argparse
import datetime as _dt
import re
import sys
import unicodedata
from pathlib import Path

# ── 볼트 관습 상수 ────────────────────────────────────────────────────────────
SCAN_ROOTS = ("02_Papers", "03_Projects")
REQUIRED = ("README.md", "AGENTS.md", "STATUS.md", "session-logs")  # STATUS 는 접미 변형 허용
CLAUDE_LIMIT_STATE = 150      # 프로젝트·논문 상태형 AGENTS.md
REGISTRY = "04_References/Pipelines/research-type-registry.md"

# 고정 폴더 골격 — 이 이름만 쓴다. 번호 접두어는 붙이지 않는다(session-logs 와 섞이므로).
# 여기 없는 폴더는 '대상별 하위 폴더'(isolates/·<균주명>/)이거나 규격 이탈이다.
SKELETON = {
    "03_Projects": {"background", "analysis", "experiments", "protocols", "admin", "session-logs"},
    "02_Papers":   {"manuscript", "figures", "references", "analysis",
                    "submission", "admin", "session-logs"},
}
# 이름이 흔들리기 쉬운 자리 — 왼쪽을 보면 오른쪽으로 고치라고 알린다.
FOLDER_ALIASES = {
    "methods": "protocols", "mechanism": "background", "axes": "background",
    "presentation": "admin", "docs": "background", "results": "analysis",
    "data": "analysis", "scripts": "(볼트 아님 — MM/Project/<P>/scripts/)",
    "manuscripts": "manuscript", "figure": "figures", "reference": "references",
}

# 건식 파이프라인 산출물: (접미사, 기대 위치, 무엇인지)
#   접미사로 찾는 이유 — 파일명 접두어는 폴더명이 아니라 '고유어'다
#   (Envtox-mouse → Envtox-analysis-plan.md). 접두어 고정은 오탐을 만든다.
ARTIFACTS = [
    ("-eda-report.md",           "analysis/", "EDA 보고"),
    ("-hypothesis-validation.md", "",          "가설 gap 검증"),
    ("-public-data-audit.md",    "",          "공개 코호트 판정"),
    ("-analysis-plan.md",        "analysis/", "분석 계획(사전 등록)"),
    ("-toolchain.md",            "analysis/", "도구·DB 버전"),
    ("-honesty-log.md",          "",          "정직성 로그"),
]
# analysis-plan 안에 있어야 하는 절 (헤딩 존재만 본다)
PLAN_SECTIONS = [("사전 예측", "사전 예측"), ("n 의 단위", "n 의 단위")]

NUM_PREFIX = re.compile(r"^(\d{2})[_-]")
# `**연구 유형**:` 처럼 마크다운 강조가 끼어도 잡히게 한다 —
# 2026-08-27 에 `**` 때문에 11개가 전부 "미기재"로 오탐됐다.
TYPE_LINE = re.compile(r"연구\s*유형[*`\s]*[:：|]\s*(.+)")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# ── 등록표 파싱 (유형 목록의 정본) ────────────────────────────────────────────
def load_types(vault: Path) -> tuple[list[str], list[str]]:
    """(활성 유형, 후보 유형). 등록표가 없으면 빈 목록 + 경고는 호출부에서."""
    t = read(vault / REGISTRY)
    if not t:
        return [], []
    # (문자, 이름) 쌍으로 받는다 — 이름 대조는 꼬리 문구 때문에 잘 깨진다.
    active = [f"{m.group(1)}. {m.group(2).strip()}" for m in
              re.finditer(r"^###\s+([A-Z])\.\s*(.+?)\s*$", t, re.M)]
    cand: list[str] = []
    m = re.search(r"##\s*후보 유형.*?\n(.*?)(?=\n##\s|\Z)", t, re.S)
    if m:
        for row in re.finditer(r"^\|\s*([^|\n]+?)\s*\|", m.group(1), re.M):
            cell = row.group(1).strip()
            if cell and not set(cell) <= set("-: ") and cell != "유형":
                cand.append(cell)
    return active, cand


def strip_paren(s: str) -> str:
    return re.sub(r"\s*[（(].*?[)）]\s*", " ", s).strip()


# ── 폴더 하나 점검 ────────────────────────────────────────────────────────────
def check_folder(folder: Path, vault: Path, active: list[str], cand: list[str]) -> dict:
    rel = folder.relative_to(vault).as_posix()
    names = {nfc(p.name): p for p in folder.iterdir() if not p.name.startswith(".")}
    out: dict = {"folder": rel, "issues": [], "info": [], "artifacts": []}

    # 0. 고정 폴더 골격 — 규격에 없는 이름을 쓰고 있나
    allowed = SKELETON[rel.split("/")[0]]
    for n, p in sorted(names.items()):
        if not p.is_dir() or n in allowed:
            continue
        alias = FOLDER_ALIASES.get(n.lower())
        if alias:
            out["issues"].append(f"`{n}/` — 골격에 없는 이름. **`{alias}`** 로 옮긴다")
        else:
            # 대상별 하위 폴더(균주·분리주)는 자체 AGENTS.md 나 하위 파일을 갖는다
            out["info"].append(f"`{n}/` — 골격 밖. 대상별 하위 폴더면 정상, 아니면 골격으로 옮긴다")

    # 1. 필수 4종 — STATUS 는 `<고유어>-STATUS.md` 변형 허용
    readme = names.get("README.md")
    if not readme:
        out["issues"].append("필수 `README.md` 없음 — 폴더 지도 (→ [[TEMPLATE-folder-README]])")
    else:
        # 헤딩만 본다. 본문의 "진행 상태는 여기 적지 않는다" 같은 면책 문구를 잡지 않기 위해서.
        bad = [h for h in re.findall(r"^#{2,4}\s*(.+)$", read(readme), re.M)
               if re.search(r"막혀|blocker|Blocker|진행 상황|즉시 필요|다음 액션|현재 Phase", h)]
        if bad:
            out["issues"].append(
                f"`README.md` 헤딩 「{bad[0]}」 — 진행 상태는 STATUS 가 정본이다. 링크만 건다")
    claude = names.get("AGENTS.md")  # 본문. CLAUDE.md 는 `@AGENTS.md` 포인터
    status = names.get("STATUS.md") or next(
        (p for n, p in names.items() if n.endswith("-STATUS.md")), None)
    slogs = names.get("session-logs")
    umbrella = any(p.is_dir() and (p / "AGENTS.md").exists() for p in names.values())

    if not claude:
        out["issues"].append("필수 `AGENTS.md` 없음")
    if not status:
        out["issues"].append("필수 `STATUS.md` 없음")
    if not (slogs and slogs.is_dir()):
        if umbrella:
            out["info"].append("`session-logs/` 없음 — 우산 트랙 예외(하위 프로젝트에 기록)")
        else:
            out["issues"].append("필수 `session-logs/` 없음")

    # 2. AGENTS.md 줄 수 상한 (상태형 150)
    if claude:
        n = len(read(claude).splitlines())
        if n > CLAUDE_LIMIT_STATE:
            out["issues"].append(f"`AGENTS.md` {n}줄 — 상태형 상한 {CLAUDE_LIMIT_STATE} 초과")

    # 2b. 논문은 어느 프로젝트에서 파생됐는지 명시한다 (없으면 "없음 (이유)")
    if claude and rel.startswith("02_Papers/") and \
            not re.search(r"^- \*\*파생 프로젝트\*\*:\s*\S", read(claude), re.M):
        out["issues"].append("`AGENTS.md` 에 `- **파생 프로젝트**:` 줄 없음 — 03 링크 또는 `없음 (이유)`")

    # 3. 파이프라인 산출물 (부재 = 단계 미도달 정보)
    found_plan = None
    for suffix, expected, label in ARTIFACTS:
        hits = [p for p in folder.rglob(f"*{suffix}")
                if "session-logs" not in p.relative_to(folder).parts]
        if not hits:
            out["artifacts"].append((label, suffix, None, "미도달"))
            continue
        for h in hits:
            loc = h.relative_to(folder).as_posix()
            ok = loc.startswith(expected) if expected else "/" not in loc
            out["artifacts"].append((label, suffix, loc, "제자리" if ok else "위치 어긋남"))
            if not ok:
                out["issues"].append(
                    f"`{loc}` — {label}는 `{expected or './'}` 에 두는 게 배치표")
            if suffix == "-analysis-plan.md":
                found_plan = h

    # 4. analysis-plan 필수 절 (헤딩 존재만)
    if found_plan:
        body = read(found_plan)
        for label, needle in PLAN_SECTIONS:
            if needle not in body:
                out["issues"].append(
                    f"`{found_plan.name}` 에 「{label}」 절 없음 — 사전 등록이 아니다")

    # 5. 넘버링 접두어 혼용 (같은 폴더 안에서)
    #    구조 파일(AGENTS/CLAUDE/STATUS/README/SPEC)과 STATUS 변형은 번호를 안 붙이는 게 정상이라 뺀다.
    tops = [n for n in names
            if n.endswith(".md")
            and n not in {"AGENTS.md", "CLAUDE.md", "STATUS.md", "README.md", "SPEC.md", "INDEX.md"}
            and not n.endswith("-STATUS.md")]
    numbered = [n for n in tops if NUM_PREFIX.match(n)]
    if numbered and len(numbered) != len(tops):
        plain = [n for n in tops if n not in numbered]
        out["issues"].append(
            f"넘버링 접두어 혼용 — 번호 {len(numbered)}개 / 무번호 {len(plain)}개 "
            f"(예: `{numbered[0]}` vs `{plain[0]}`)")

    # 7. 연구 유형이 등록표에 있나
    src = (read(claude) if claude else "") + (read(status) if status else "")
    m = TYPE_LINE.search(src)
    if not m:
        out["info"].append("연구 유형 미기재 — `AGENTS.md` 에 `연구 유형: …` 한 줄 (→ 등록표)")
    else:
        declared = m.group(1).strip()
        letters = set(re.findall(r"등록표\s*([A-Z])", declared))
        known_letters = {a.split(".", 1)[0] for a in active}
        if letters:
            # `등록표 F` 처럼 문자를 적었으면 그것만 본다 — 가장 안 깨지는 방식
            missing = sorted(letters - known_letters)
            if missing:
                out["issues"].append(
                    f"연구 유형에 적힌 등록표 {'·'.join(missing)} 가 등록표에 없다 — 행을 추가한다")
        else:
            head = strip_paren(re.split(r"[—→|]", declared)[0])
            known = [strip_paren(x.split(".", 1)[1]) for x in active] + \
                    [strip_paren(x) for x in cand]
            if not any(k and (k in head or head in k) for k in known):
                out["issues"].append(
                    f"연구 유형 「{head}」 가 등록표에 없음 — 행을 추가하거나 "
                    f"`등록표 <문자>` 를 함께 적는다")
    return out


# ── 볼트 전체 ─────────────────────────────────────────────────────────────────
def duplicate_names(vault: Path) -> dict[str, list[str]]:
    """볼트 전체 파일명 유일성. 구조 파일(AGENTS/CLAUDE/STATUS/README)은 예외."""
    seen: dict[str, list[str]] = {}
    exempt = {"AGENTS.md", "CLAUDE.md", "STATUS.md", "README.md"}
    for p in vault.rglob("*.md"):
        parts = p.relative_to(vault).parts
        if parts[0] in {".obsidian", ".trash", ".git", "MM", "_Templates", "_Tools", ".claude"}:
            continue
        n = nfc(p.name)
        if n in exempt:
            continue
        seen.setdefault(n, []).append(p.relative_to(vault).as_posix())
    return {k: v for k, v in seen.items() if len(v) > 1}


def render(results: list[dict], dups: dict, active: list[str], cand: list[str],
           registry_ok: bool) -> str:
    today = _dt.date.today().isoformat()
    L = [f"# 파이프라인 구조 점검 — {today}", ""]
    n_iss = sum(len(r["issues"]) for r in results)
    L += ["## 요약", "",
          f"- 점검 폴더: **{len(results)}개**",
          f"- 손볼 것: **{n_iss}건**",
          f"- 파일명 중복: **{len(dups)}건**",
          f"- 등록표 유형: 활성 {len(active)} · 후보 {len(cand)}"
          + ("" if registry_ok else "  ⚠️ **등록표를 못 읽었다**"), ""]

    L += ["## 손볼 것", ""]
    if n_iss == 0:
        L.append("없음.")
    for r in results:
        if r["issues"]:
            L.append(f"### `{r['folder']}`")
            L += [f"- {i}" for i in r["issues"]] + [""]

    L += ["", "## 파이프라인 진행 (부재는 오류가 아니라 단계 미도달)", "",
          "| 폴더 | EDA | gap | 공개데이터 | 분석계획 | toolchain | 정직성 |",
          "|---|---|---|---|---|---|---|"]
    order = [suffix for suffix, _expected, _label in ARTIFACTS]
    for r in results:
        m = {suf: st for _, suf, _, st in r["artifacts"]}
        cells = ["✅" if m.get(s) == "제자리" else
                 ("⚠️" if m.get(s) == "위치 어긋남" else "—") for s in order]
        L.append(f"| `{r['folder'].split('/')[-1]}` | " + " | ".join(cells) + " |")

    info = [(r["folder"], i) for r in results for i in r["info"]]
    if info:
        L += ["", "## 참고", ""] + [f"- `{f}` — {i}" for f, i in info]

    if dups:
        L += ["", "## 파일명 중복 (wikilink 가 어디로 갈지 보장 안 됨)", ""]
        for name, paths in sorted(dups.items()):
            L.append(f"- `{name}` — " + " · ".join(f"`{p}`" for p in paths))

    L += ["", "---", "",
          "기준 문서: [[guide-02-03-폴더구조]] · [[dry-research-pipeline]] · [[research-type-registry]]", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()

    vault = Path(a.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"볼트를 찾을 수 없다: {vault}", file=sys.stderr)
        return 1

    active, cand = load_types(vault)
    registry_ok = bool(active or cand)

    folders = []
    for root in SCAN_ROOTS:
        d = vault / root
        if not d.is_dir():
            continue
        folders += sorted(p for p in d.iterdir()
                          if p.is_dir() and not p.name.startswith("."))
    if a.only:
        folders = [f for f in folders if a.only in f.name]

    results = [check_folder(f, vault, active, cand) for f in folders]
    text = render(results, duplicate_names(vault), active, cand, registry_ok)

    if a.report:
        out = vault / "00_Inbox" / f"pipeline-check-{_dt.date.today().isoformat()}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(
            f"---\ntags: [maintenance, pipeline-check]\ncreated: "
            f"{_dt.date.today().isoformat()}\n---\n\n" + text, encoding="utf-8")
        print(f"저장: {out.relative_to(vault)}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
