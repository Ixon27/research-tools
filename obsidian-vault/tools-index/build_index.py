#!/usr/bin/env python3
"""build_index.py — 볼트 도구 안내 노트 자동 생성.

`.claude/commands/`의 슬래시 커맨드와 `_Tools/`의 스크립트를 훑어
`_Tools/도구-안내.md` 한 장으로 목록화한다. 커맨드 설명(frontmatter description)이
원본(single source of truth)이므로, 툴을 고치고 이 스크립트를 다시 돌리면 안내가 갱신된다.

사용법:  python3 build_index.py
"""
from __future__ import annotations
import datetime as dt
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.abspath(os.path.join(HERE, "..", ".."))

# 커맨드/스크립트별 "어디서 실행" · "산출물 위치" (아는 것만; 없으면 —)
RUN_FROM = {
    "vault": "볼트 루트 (`cd <볼트> && claude`)",
}
OUTPUT_OF = {
    "review-paper": "02_Papers/NN-주제/ (references·manuscript)",
    "research-paper": "02_Papers/NN-주제/manuscript/",
    "genome-report": "03_Projects/WGS/<균주>/ 또는 02_Papers/",
    "conference-abstract": "01_Research/Conferences/<연도-학회-초록ID>/",
    "graph-health": "00_Inbox/graph-health-날짜.md",
    "lit-review": "_Tools/lit-review/out/날짜/ 또는 --out 경로",
    "paper-digest": "디스코드·이메일 발송(주간)",
    "course-html": "<작업폴더>/수업/…/<과목>-학습노트.html",
    "lab-deck": "<작업폴더>/<프로젝트>/presentation/<이름>-deck.html",
    "html-templates": "디자인 CSS·내용 규칙 제공 + HTML 산출물 검사 결과",
}


def first_sentence(text: str) -> str:
    text = text.strip().strip('"')
    m = re.split(r"(?<=[.。])\s", text, maxsplit=1)
    return m[0].strip() if m else text


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def command_desc(txt: str) -> str:
    m = re.match(r"^---\s*\n(.*?)\n---", txt, re.DOTALL)
    if m:
        dm = re.search(r'description:\s*"?(.+?)"?\s*$', m.group(1), re.MULTILINE)
        if dm:
            return first_sentence(dm.group(1))
    h = re.search(r"^#\s+(.+)$", txt, re.MULTILINE)
    return h.group(1).strip() if h else "(설명 없음)"


SKIP_HEAD = ("참조", "출력", "트리거", "사용법", "산출", "실행 흐름", "실행흐름")


def step_headings(txt: str) -> list[str]:
    """워크플로우 단계 추출. 커맨드마다 단계가 ## 또는 ### 라서 둘 다 보고,
    메타 섹션(참조·출력·실행 흐름 래퍼 등)은 제외. ### 단계가 있으면 그걸 우선."""
    lvl2 = [h.strip() for h in re.findall(r"^##\s+(.+)$", txt, re.MULTILINE)]
    lvl3 = [h.strip() for h in re.findall(r"^###\s+(.+)$", txt, re.MULTILINE)]
    lvl2 = [h for h in lvl2 if not h.startswith(SKIP_HEAD)]
    lvl3 = [h for h in lvl3 if not h.startswith(SKIP_HEAD)]
    # ### 단계가 여러 개면 그것이 실제 단계(2단계 구조). 아니면 ## 사용.
    return lvl3 if len(lvl3) >= len(lvl2) and lvl3 else lvl2


def scan_commands(cmd_dir: str, scope: str) -> list[dict]:
    out = []
    if not os.path.isdir(cmd_dir):
        return out
    for fn in sorted(os.listdir(cmd_dir)):
        if not fn.endswith(".md"):
            continue
        txt = read(os.path.join(cmd_dir, fn))
        name = fn[:-3]
        out.append({
            "name": name,
            "desc": command_desc(txt),
            "run": RUN_FROM[scope],
            "output": OUTPUT_OF.get(name, "—"),
            "steps": step_headings(txt),
        })
    return out


def script_summary(tool_dir: str) -> tuple[str, str]:
    """(요약, 실행법). README H1/첫줄 + .py|.sh 파일명."""
    readme = os.path.join(tool_dir, "README.md")
    summary = "(README 없음)"
    if os.path.isfile(readme):
        with open(readme, encoding="utf-8") as f:
            lines = [l.rstrip() for l in f]
        h1 = next((l[2:] for l in lines if l.startswith("# ")), "")
        body = next((l for l in lines if l and not l.startswith("#") and not l.startswith(">")), "")
        summary = (h1.split("—", 1)[-1].strip() if "—" in h1 else h1) or body[:80]
    runners = sorted(f for f in os.listdir(tool_dir) if f.endswith((".py", ".sh")))
    runner = runners[0] if runners else ""
    return summary, runner


def scan_scripts() -> list[tuple[str, str, str, str]]:
    tools_root = os.path.join(VAULT, "_Tools")
    out = []
    for name in sorted(os.listdir(tools_root)):
        d = os.path.join(tools_root, name)
        if not os.path.isdir(d) or name == "tools-index":
            continue
        summary, runner = script_summary(d)
        if not runner:
            how = "—"
        else:
            prog = "bash" if runner.endswith(".sh") else "python3"
            how = f"`{prog} _Tools/{name}/{runner}`"
        out.append((name, summary, how, OUTPUT_OF.get(name, "—")))
    return out


def workflow_section(cmds: list[dict]) -> str:
    out = []
    for c in cmds:
        out.append(f"### /{c['name']}")
        if c["steps"]:
            out += [f"{i}. {s}" for i, s in enumerate(c["steps"], 1)]
        else:
            out.append("_(단계 헤딩 없음)_")
        out.append("")
    return "\n".join(out)


def table(headers, rows):
    line = "| " + " | ".join(headers) + " |\n"
    line += "|" + "|".join(["---"] * len(headers)) + "|\n"
    for r in rows:
        cells = [str(c).replace("|", "\\|") for c in r]
        line += "| " + " | ".join(cells) + " |\n"
    return line


def main() -> int:
    vault_cmds = scan_commands(os.path.join(VAULT, ".claude", "commands"), "vault")
    scripts = scan_scripts()

    today = dt.date.today().isoformat()
    parts = [
        "---", "tags: [tools, moc, index]", f"created: {today}", "---", "",
        "# 🛠️ 도구 안내 (자동 생성)", "",
        f"> `_Tools/tools-index/build_index.py`가 생성. **직접 수정하지 말 것** — 툴 바꾸면 스크립트를 다시 돌린다. 갱신: {today}", "",
        "도구는 두 종류다. **커맨드**(대화로 `/이름` 또는 자연어로 호출) vs **스크립트**(터미널 `python3`로 실행).", "",
        "## 볼트 커맨드 (볼트 루트에서 claude)", "",
        table(["커맨드", "무엇", "산출물 위치"], [(f"`/{c['name']}`", c["desc"], c["output"]) for c in vault_cmds]),
        "## 스크립트 (터미널 python3)", "",
        table(["도구", "무엇", "실행법", "산출물"], [(n, s, h, o) for n, s, h, o in scripts]),
        "## 커맨드 워크플로우 (무엇을 어떤 순서로 — 뭘 고칠지 판단용)", "",
        "> 커맨드 파일은 `.claude/`(Obsidian이 숨김) 안에 있어 직접 안 열림. 아래는 각 커맨드의 단계 뼈대를 뽑은 것. 고칠 데가 보이면 원본 `.claude/commands/<이름>.md`를 고치고 `build_index.py` 재실행.", "",
        workflow_section(vault_cmds),
        "## 쓰는 법 요약", "",
        "- 커맨드: 해당 폴더에서 `claude` 켜고 `/이름` 입력, 또는 그냥 말로 시켜도 됨.",
        "- 스크립트: 터미널에서 실행하거나, 볼트 세션에서 \"그래프 점검해줘\"·\"논문 수집해줘\"라고 하면 대신 돌려줌.",
        "",
    ]
    outpath = os.path.join(VAULT, "_Tools", "도구-안내.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    print(f"생성: {os.path.relpath(outpath, VAULT)}  (커맨드 {len(vault_cmds)} · 스크립트 {len(scripts)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
