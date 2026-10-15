#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
과목 학습노트 폴더(04_References/Notes/<Subject>/) -> 단일 self-contained HTML.

- 디자인은 _Tools/html-templates/designs/notebook.css 를 그대로 인라인(색·폰트 변경 금지).
  학습노트/문제 전용 스타일만 EXTRA_CSS 로 덧붙인다.
- 본문 마크다운은 pandoc 으로 변환. Obsidian 콜아웃(> [!warning] 제목)은
  pandoc 전에 fenced div 로 치환해 살린다.
- "## C. 예상문제 …" 절은 파싱해서 인터랙티브 문제로 렌더한다:
  보기 클릭 -> 정오 표시 + 해설 즉시 공개, 점수·진행률 집계, localStorage 저장.
  따라서 원본의 "정답과 해설" 표는 HTML 에서 제거된다(스포일러 방지).

사용법:
  python3 _Tools/course-html/build_course_html.py [노트폴더] [출력.html]
기본값:
  노트폴더 = 04_References/Notes/General-Microbiology
  출력     = ./<과목>-학습노트.html (현재 폴더)
볼트 경로는 환경변수 VAULT, 없으면 이 스크립트 기준 두 단계 위(<볼트>/_Tools/course-html/).

의존성: python3, pandoc
"""
import html
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

VAULT = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2]).expanduser()
DEFAULT_SRC = VAULT / "04_References" / "Notes" / "General-Microbiology"

# 폴더명 → 화면에 쓸 한국어 제목. 없으면 폴더명을 그대로 쓴다.
SUBJECT_TITLES = {
    "General-Microbiology": "미생물학개론",
    "Microbiome-Analysis": "마이크로바이옴 분석",
    "Bioinformatics": "생물정보학",
    "Analytical-Chemistry": "분석화학",
    "Advanced-Microbiology": "최신미생물학",
}


def subject_title(src):
    return SUBJECT_TITLES.get(src.name, src.name)
DEFAULT_OUT = None   # None → ./<과목>-학습노트.html
CSS_FILE = Path(__file__).resolve().parents[1] / "html-templates" / "designs" / "notebook.css"
PANDOC = shutil.which("pandoc") or "/opt/homebrew/bin/pandoc"

CALLOUT_KIND = {
    "warning": ("경고", "warn"),
    "important": ("중요", "imp"),
    "note": ("노트", "note"),
    "tip": ("팁", "tip"),
    "info": ("정보", "note"),
    "example": ("예시", "note"),
    "question": ("질문", "tip"),
}
MARKS = "①②③④⑤"


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# ---------------------------------------------------------------- 인라인 변환
def inline_md(s: str, docmap=None) -> str:
    """문제·보기·해설처럼 짧은 인라인 마크다운을 HTML 로."""
    s = html.escape(s)
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00C{len(codes)-1}\x00"

    s = re.sub(r"`([^`]+)`", stash, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", s)
    s = wikilinks(s, docmap or {})
    for i, c in enumerate(codes):
        s = s.replace(f"\x00C{i}\x00", f"<code>{c}</code>")
    return s


def wikilinks(s: str, docmap: dict) -> str:
    def rep(m):
        target = norm(m.group(1).split("#")[0].strip())
        label = (m.group(2) or m.group(1)).strip()
        if target in docmap:
            return f'<a class="wl" href="#" data-doc="{docmap[target]}">{label}</a>'
        return f'<span class="wl-off">{label}</span>'

    return re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]", rep, s)


# ---------------------------------------------------------------- 마크다운 전처리
def strip_frontmatter(text: str):
    meta = {}
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            text = text[end + 5 :]
    return meta, text


def convert_callouts(lines):
    """> [!warning] 제목 … 블록을 pandoc fenced div 로."""
    out, i = [], 0
    while i < len(lines):
        m = re.match(r"^>\s*\[!(\w+)\]\s*(.*)$", lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        kind = m.group(1).lower()
        label, css = CALLOUT_KIND.get(kind, ("노트", "note"))
        title = m.group(2).strip()
        body = []
        i += 1
        while i < len(lines) and lines[i].startswith(">"):
            body.append(re.sub(r"^>\s?", "", lines[i]))
            i += 1
        out.append("")
        out.append(f"::: {{.cal .cal-{css}}}")
        out.append(f'<div class="cal-h"><span class="cal-tag">{html.escape(label)}</span>'
                   f'<span class="cal-t">{inline_md(title)}</span></div>')
        out.append("")
        out.extend(body)
        out.append(":::")
        out.append("")
    return out


def to_html(md: str) -> str:
    r = subprocess.run(
        [PANDOC, "--from", "markdown+fenced_divs+lists_without_preceding_blankline-smart-superscript-subscript",
         "--to", "html5", "--wrap=none"],
        input=md, capture_output=True, text=True, check=True,
    )
    return r.stdout


# ---------------------------------------------------------------- 문제 파싱
def parse_quiz(lines):
    """(questions, remaining_lines). questions = [{n, stem, opts, group, ans, exp}]"""
    ci = next((i for i, l in enumerate(lines) if l.startswith("## C.")), None)
    di = next((i for i, l in enumerate(lines) if l.startswith("## D.")), None)
    if ci is None or di is None:
        return [], lines

    block = lines[ci:di]
    ai = next((i for i, l in enumerate(block) if re.match(r"^#{3,4}\s*정답과 해설", l)), len(block))
    qpart, apart = block[:ai], block[ai:]

    questions, group = [], ""
    j = 0
    while j < len(qpart):
        line = qpart[j].strip()
        if line.startswith("####"):
            group = line.lstrip("#").strip()
        m = re.match(r"^\*\*(\d+)\.\*\*\s*(.+)$", line)
        if m:
            n, stem = int(m.group(1)), m.group(2).strip()
            k = j + 1
            while k < len(qpart) and not qpart[k].strip():
                k += 1
            opts = []
            if k < len(qpart) and qpart[k].strip().startswith(MARKS[0]):
                raw = qpart[k].strip()
                parts = [p.strip() for p in re.split(f"(?=[{MARKS}])", raw) if p.strip()]
                for p in parts:
                    opts.append(p[1:].strip() if p[0] in MARKS else p)
                j = k
            questions.append({"n": n, "stem": stem, "opts": opts, "group": group})
        j += 1

    answers = {}
    for line in apart:
        m = re.match(rf"^\|\s*(\d+)\s*\|\s*([{MARKS}])\s*\|\s*(.*?)\s*\|\s*$", line.strip())
        if m:
            answers[int(m.group(1))] = (MARKS.index(m.group(2)) + 1, m.group(3).strip())

    for q in questions:
        a = answers.get(q["n"])
        q["ans"], q["exp"] = (a[0], a[1]) if a else (0, "")

    # 원본 "## C. 예상문제" 헤딩은 인터랙티브 블록으로 갈아끼우되,
    # 사이드바 앵커가 사라지지 않도록 같은 레벨의 헤딩을 남긴다.
    head = re.sub(r"^##\s*", "", lines[ci]).strip()
    rest = lines[:ci] + [f"## {head} — 인터랙티브", "", "\x00QUIZ\x00", ""] + lines[di:]
    return questions, rest


def render_quiz(questions, docmap) -> str:
    total = len(questions)
    parts = [
        '<div class="quiz">',
        '<div class="quiz-bar">',
        f'<div class="qb-title">예상문제 <b>{total}</b>문항 — 보기를 고르면 정답과 해설이 바로 나온다</div>',
        '<div class="qb-stat js-only"><span id="qb-done">0</span>/<span id="qb-total">'
        f'{total}</span> 풀이 · 정답 <span id="qb-ok">0</span> '
        '(<span id="qb-rate">0</span>%)</div>',
        '<div class="qb-track js-only"><div class="qb-fill" id="qb-fill"></div></div>',
        '<button class="qb-reset js-only" id="qb-reset" type="button">전체 초기화</button>',
        "</div>",
    ]
    cur = None
    for q in questions:
        if q["group"] != cur:
            if cur is not None:
                parts.append("</div>")
            cur = q["group"]
            gid = "qg-" + re.sub(r"\W+", "-", cur)[:40]
            parts.append(f'<div class="quiz-group" id="{gid}">')
            parts.append(f'<div class="qg-h">{inline_md(cur, docmap)}</div>')
        n = q["n"]
        parts.append(f'<div class="q" data-n="{n}" data-ans="{q["ans"]}">')
        # 라디오를 형제 맨 앞에 두면 :checked ~ 선택자만으로 정오·해설을 낼 수 있다
        # (JS 를 못 쓰는 뷰어 — 예: Dropbox iOS 미리보기 — 에서도 문제가 풀린다).
        for i in range(1, len(q["opts"]) + 1):
            ans = " ans" if i == q["ans"] else ""
            parts.append(
                f'<input type="radio" class="qr i{i}{ans}" name="q{n}" id="q{n}o{i}">'
            )
        parts.append(
            f'<div class="q-stem"><span class="q-num">{n}</span>'
            f'<span>{inline_md(q["stem"], docmap)}</span></div>'
        )
        parts.append('<div class="q-opts">')
        for i, o in enumerate(q["opts"], 1):
            is_ans = " is-ans" if i == q["ans"] else ""
            parts.append(
                f'<label class="q-opt i{i}{is_ans}" for="q{n}o{i}" data-i="{i}">'
                f'<span class="q-mark">{MARKS[i-1]}</span>'
                f'<span class="q-txt">{inline_md(o, docmap)}</span></label>'
            )
        parts.append("</div>")
        parts.append(
            '<div class="q-exp">'
            '<div class="q-verdict v-ok">정답</div>'
            '<div class="q-verdict v-no">오답</div>'
            f'<div class="q-exp-b"><b>정답 {MARKS[q["ans"]-1] if q["ans"] else "?"}</b> — '
            f'{inline_md(q["exp"], docmap)}</div>'
            '<button class="q-again" type="button">다시 풀기</button></div>'
        )
        parts.append("</div>")
    if cur is not None:
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------- 문서 처리
def heading_ids(md_lines, docid):
    """마크다운 헤딩 순서대로 (level, text, id) 목록."""
    out, in_code = [], False
    for line in md_lines:
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            out.append([len(m.group(1)), m.group(2).strip(),
                        f"{docid}-h{len(out)}"])
    return out


def apply_ids(html_text, heads):
    """pandoc 이 붙인 id 를 우리가 정한 결정적 id 로 교체."""
    it = iter(heads)

    def rep(m):
        try:
            h = next(it)
        except StopIteration:
            return m.group(0)
        return f'<h{m.group(1)} id="{h[2]}">'

    return re.sub(r"<h([1-6])[^>]*>", rep, html_text)


def build():
    src = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_SRC
    out = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else \
        (DEFAULT_OUT or Path.cwd() / f"{subject_title(src)}-학습노트.html")

    files = sorted(src.glob("*.md"), key=lambda p: (not norm(p.stem).startswith("MOC"), norm(p.stem)))
    if not files:
        sys.exit(f"노트를 찾지 못했다: {src}")

    docmap = {norm(p.stem): f"doc{i}" for i, p in enumerate(files)}
    docs = []
    quiz_html = ""

    for i, path in enumerate(files):
        docid = f"doc{i}"
        meta, text = strip_frontmatter(path.read_text(encoding="utf-8"))
        lines = text.splitlines()

        questions = []
        if "예상문제" in norm(path.stem) or any(l.startswith("## C. 예상문제") for l in lines):
            questions, lines = parse_quiz(lines)
            if questions:
                quiz_html = render_quiz(questions, docmap)

        title = next((l.lstrip("#").strip() for l in lines if l.startswith("# ")), norm(path.stem))
        body_lines = [l for l in lines if not l.startswith("# ")]
        heads = [h for h in heading_ids(body_lines, docid)]

        md = "\n".join(convert_callouts(body_lines))
        body = to_html(md)
        body = apply_ids(body, heads)
        body = wikilinks(body, docmap)
        # pandoc 이 자리표시자를 <p> 로 감싸므로 <p> 째로 걷어낸다
        # (div 를 p 안에 넣으면 잘못된 HTML 이라 뷰어에 따라 깨진다).
        body = re.sub(r"<p>\s*\x00QUIZ\x00\s*</p>", lambda m: quiz_html, body)
        body = body.replace("\x00QUIZ\x00", quiz_html)
        # pandoc 은 <table> 과 <table style="width:100%;"> 두 형태를 낸다.
        # 여는 태그를 하나라도 놓치면 </div> 가 남아 #main 이 조기 종료된다.
        body = re.sub(r"<table[^>]*>", lambda m: '<div class="tw">' + m.group(0), body)
        body = re.sub(r"</table>", "</table></div>", body)

        num = re.match(r"^(\d{2})-", norm(path.stem))
        docs.append({
            "id": docid,
            "title": title,
            "short": norm(path.stem),
            "num": num.group(1) if num else "",
            "tags": meta.get("tags", ""),
            "created": meta.get("created", ""),
            "body": body,
            "secs": [h for h in heads if h[0] == 2],
            "nq": len(questions),
        })

    css = CSS_FILE.read_text(encoding="utf-8")
    page = render_page(docs, css, src.name, sum(d["nq"] for d in docs),
                       title=sys.argv[3] if len(sys.argv) > 3 else subject_title(src))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"OK  {out}  ({out.stat().st_size/1024:.0f} KB, 문서 {len(docs)}개, "
          f"문항 {sum(d['nq'] for d in docs)}개)")


# ---------------------------------------------------------------- 페이지 조립
EXTRA_CSS = """
/* --- 학습노트 전용 (notebook 디자인 위에 덧붙임) --- */
/* JS 가 도는 환경에서만 "한 번에 한 노트". JS 를 막는 뷰어(Dropbox iOS 미리보기 등)
   에서는 전 노트가 그냥 이어져 보이고 사이드바 링크는 앵커로 동작한다. */
.doc{display:block;scroll-margin-top:74px}
body.js .doc{display:none}
body.js .doc.on{display:block}
body:not(.js) .js-only{display:none!important}
.nojs-tip{margin:0 0 16px;padding:10px 14px;border-radius:9px;background:#fdf7ec;
  border:1px solid #f0dcb4;font-size:12.5px;color:#7a6231}
body.js .nojs-tip{display:none}
.note-body{font-size:15px;color:#3f4149}
.note-body h2{font-size:19px;font-weight:800;color:var(--dark);margin:30px 0 12px;
  padding-bottom:8px;border-bottom:2px solid var(--border)}
.note-body h2:first-child{margin-top:4px}
.note-body h3{font-size:16.5px;font-weight:800;color:var(--dark);margin:22px 0 8px}
.note-body h4{font-size:14.5px;font-weight:800;color:var(--primary);margin:18px 0 6px}
.note-body h5,.note-body h6{font-size:14px;font-weight:700;color:var(--dark);margin:12px 0 4px}
.note-body p{margin:0 0 11px}
.note-body ul,.note-body ol{padding-left:22px;margin:8px 0}
.note-body li{margin:4px 0}
.note-body li>p{margin:0 0 4px}
.note-body hr{border:none;border-top:1px solid var(--border);margin:26px 0}
.note-body{overflow-wrap:anywhere}
.note-body code{background:#eef1f6;padding:1px 6px;border-radius:4px;font-size:13.5px;
  overflow-wrap:anywhere}
.note-body pre{background:#2f3340;color:#e6e6e6;padding:13px 16px;border-radius:8px;
  overflow-x:auto;font-size:13px;margin:10px 0;line-height:1.6}
.note-body pre code{background:none;padding:0;color:inherit}
.note-body blockquote{border-left:3px solid var(--primary);padding:8px 16px;margin:12px 0;
  background:#f2f7fd;color:#4a5568;border-radius:0 8px 8px 0}
.note-body blockquote p:last-child{margin-bottom:0}
.tw{overflow-x:auto;margin:12px 0}
.note-body table{border-collapse:collapse;font-size:13.5px;width:100%;min-width:420px}
.note-body th,.note-body td{border:1px solid var(--border);padding:7px 11px;
  text-align:left;vertical-align:top}
.note-body th{background:var(--bg);font-weight:800;color:var(--dark);white-space:nowrap}
.note-body tr:nth-child(even) td{background:#fafbfd}
.note-body strong{color:var(--dark);font-weight:800}
.wl{color:var(--primary);font-weight:700;border-bottom:1px dashed rgba(74,144,217,.5)}
.wl:hover{background:#eaf3fc}
.wl-off{color:var(--light);font-weight:600}

/* 콜아웃 */
.cal{margin:14px 0;padding:12px 16px;border-radius:10px;border:1px solid var(--border);
  border-left:4px solid var(--primary);background:#f8fafd}
.cal>p:last-child{margin-bottom:0}
.cal-h{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.cal-tag{font-size:10.5px;font-weight:800;letter-spacing:.4px;padding:2px 8px;
  border-radius:999px;background:var(--primary);color:#fff}
.cal-t{font-size:13.5px;font-weight:800;color:var(--dark)}
.cal-warn{border-left-color:#e8a33d;background:#fdf7ec}
.cal-warn .cal-tag{background:#e8a33d}
.cal-imp{border-left-color:#d9534f;background:#fdf1f0}
.cal-imp .cal-tag{background:#d9534f}
.cal-tip{border-left-color:#4bbf9a;background:#eefaf5}
.cal-tip .cal-tag{background:#4bbf9a}

/* 문제 */
.quiz{margin:8px 0 4px}
.quiz-bar{position:sticky;top:60px;z-index:30;background:var(--card);border:1px solid var(--border);
  border-radius:var(--radius);box-shadow:var(--shadow);padding:14px 18px;margin-bottom:18px;
  display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px}
.qb-title{font-size:13.5px;font-weight:700;color:var(--dark)}
.qb-stat{font-size:13px;color:var(--light);font-weight:700}
.qb-stat b,.qb-stat span{color:var(--primary)}
.qb-track{flex:1 1 160px;height:7px;border-radius:999px;background:var(--bg);overflow:hidden;
  border:1px solid var(--border)}
.qb-fill{height:100%;width:0;background:linear-gradient(90deg,#4a90d9,#36b9cc);transition:width .3s}
.qb-reset{border:1px solid var(--border);background:var(--bg);color:var(--light);font-family:inherit;
  font-size:12px;font-weight:700;padding:6px 12px;border-radius:999px;cursor:pointer}
.qb-reset:hover{color:#d9534f;border-color:#f0c6c4;background:#fdf1f0}
.qg-h{font-size:14px;font-weight:800;color:var(--dark);margin:26px 0 10px;padding-left:11px;
  position:relative}
.qg-h::before{content:'';position:absolute;left:0;top:3px;width:3px;height:15px;
  background:var(--primary);border-radius:2px}
.q{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:18px 20px;margin-bottom:14px;scroll-margin-top:150px}
.q-stem{display:flex;gap:10px;font-size:15px;font-weight:700;color:var(--dark);
  line-height:1.6;margin-bottom:12px}
.q-num{flex:0 0 26px;height:26px;border-radius:8px;background:var(--bg);border:1px solid var(--border);
  display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;
  color:var(--light)}
.q-opts{display:flex;flex-direction:column;gap:7px}
.qr{position:absolute;opacity:0;width:0;height:0;pointer-events:none}
.q-opt{display:flex;gap:9px;align-items:flex-start;text-align:left;width:100%;
  padding:10px 13px;border:1px solid var(--border);background:#fcfdff;border-radius:9px;
  font-family:inherit;font-size:14px;line-height:1.55;color:var(--text);cursor:pointer;
  transition:background .12s,border-color .12s}
.q-opt:hover{background:#eef4fb;border-color:#bcd7f0}
.q-mark{flex:0 0 auto;font-weight:800;color:var(--light)}
/* 답을 고른 뒤 (JS 없이 :checked 만으로 동작) */
.qr:checked ~ .q-opts .q-opt{cursor:default}
.qr:checked ~ .q-opts .q-opt:hover{background:#fcfdff;border-color:var(--border)}
.qr.i1:not(.ans):checked ~ .q-opts .q-opt.i1,
.qr.i2:not(.ans):checked ~ .q-opts .q-opt.i2,
.qr.i3:not(.ans):checked ~ .q-opts .q-opt.i3,
.qr.i4:not(.ans):checked ~ .q-opts .q-opt.i4{background:#fdeeed;border-color:#eeaaa6}
.qr.i1:not(.ans):checked ~ .q-opts .q-opt.i1:hover,
.qr.i2:not(.ans):checked ~ .q-opts .q-opt.i2:hover,
.qr.i3:not(.ans):checked ~ .q-opts .q-opt.i3:hover,
.qr.i4:not(.ans):checked ~ .q-opts .q-opt.i4:hover{background:#fdeeed;border-color:#eeaaa6}
.qr.i1:not(.ans):checked ~ .q-opts .q-opt.i1 .q-mark,
.qr.i2:not(.ans):checked ~ .q-opts .q-opt.i2 .q-mark,
.qr.i3:not(.ans):checked ~ .q-opts .q-opt.i3 .q-mark,
.qr.i4:not(.ans):checked ~ .q-opts .q-opt.i4 .q-mark{color:#d9534f}
.qr.i1:not(.ans):checked ~ .q-opts .q-opt.i1::after,
.qr.i2:not(.ans):checked ~ .q-opts .q-opt.i2::after,
.qr.i3:not(.ans):checked ~ .q-opts .q-opt.i3::after,
.qr.i4:not(.ans):checked ~ .q-opts .q-opt.i4::after{content:'선택';margin-left:auto;
  font-size:11px;font-weight:800;color:#d9534f}
.qr:checked ~ .q-opts .q-opt.is-ans,
.qr:checked ~ .q-opts .q-opt.is-ans:hover{background:#e9f8f1;border-color:#7bcfae}
.qr:checked ~ .q-opts .q-opt.is-ans .q-mark{color:#2f9e75}
.qr:checked ~ .q-opts .q-opt.is-ans::after{content:'정답';margin-left:auto;font-size:11px;
  font-weight:800;color:#2f9e75}
.q-exp{display:none;margin-top:12px;padding:13px 15px;border-radius:9px;background:var(--bg);
  border:1px solid var(--border)}
.qr:checked ~ .q-exp{display:block}
.q-verdict{font-size:13px;font-weight:800;margin-bottom:6px;display:none}
.v-ok{color:#2f9e75}
.v-no{color:#d9534f}
.qr.ans:checked ~ .q-exp .v-ok{display:block}
.qr:not(.ans):checked ~ .q-exp .v-no{display:block}
.q-exp-b{font-size:13.5px;line-height:1.75;color:#4b4d57}
.q-exp-b b{color:var(--dark)}
.q-again{margin-top:9px;border:1px solid var(--border);background:var(--card);color:var(--light);
  font-family:inherit;font-size:11.5px;font-weight:700;padding:4px 11px;border-radius:999px;
  cursor:pointer}
.q-again:hover{color:var(--primary);border-color:#bcd7f0}

.nav-sub{display:block;padding:5px 18px 5px 34px;font-size:12px;font-weight:600;
  color:rgba(255,255,255,.55);border-left:3px solid transparent}
.nav-sub:hover{color:#fff;background:rgba(255,255,255,.06)}
.nav-link.active{color:#fff;background:rgba(255,255,255,.12);border-left-color:var(--primary)}
.doc-meta{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.chip{font-size:10.5px;font-weight:700;color:var(--light);padding:2px 9px;border-radius:999px;
  background:var(--bg);border:1px solid var(--border)}
.topbar .meta{white-space:nowrap}
@media(max-width:820px){
  .container{padding:18px 16px 70px}
  .exp-card{padding:18px 16px}
  .quiz-bar{top:56px}
  .q{padding:15px 14px}
  /* JS 없는 뷰어에선 사이드바를 접을 수 없으니 본문 위에 펼쳐 둔다 */
  body:not(.js) #wrap{display:block}
  body:not(.js) .sidebar{position:static;width:100%;height:auto;transform:none;
    padding-bottom:12px}
  body:not(.js) #main{margin-left:0}
  body:not(.js) .hamburger{display:none}
}
"""

JS = r"""
document.body.classList.add('js');   // JS 가 실제로 돌 때만 "한 번에 한 노트" 모드
const docs = Array.from(document.querySelectorAll('.doc'));
const links = Array.from(document.querySelectorAll('.nav-link[data-doc]'));

function showDoc(id, anchor){
  docs.forEach(d => d.classList.toggle('on', d.id === id));
  links.forEach(a => a.classList.toggle('active', a.dataset.doc === id));
  document.querySelectorAll('.nav-group').forEach(g => {
    g.classList.toggle('open', g.dataset.doc === id);
  });
  const t = document.getElementById('topTitle');
  const cur = document.getElementById(id);
  if (cur && t) t.textContent = cur.dataset.title;
  if (anchor){
    const el = document.getElementById(anchor);
    if (el){ el.scrollIntoView({behavior:'smooth', block:'start'}); return; }
  }
  window.scrollTo({top:0});
  if (window.innerWidth <= 820) document.querySelector('.sidebar').classList.remove('open');
}

document.addEventListener('click', e => {
  const head = e.target.closest('.nav-head');
  if (head){ e.preventDefault(); showDoc(head.dataset.doc); return; }
  const sub = e.target.closest('.nav-sub');
  if (sub){ e.preventDefault(); showDoc(sub.dataset.doc, sub.dataset.anchor); return; }
  const wl = e.target.closest('.wl');
  if (wl){ e.preventDefault(); showDoc(wl.dataset.doc); return; }
  const ham = e.target.closest('.hamburger');
  if (ham){ document.querySelector('.sidebar').classList.toggle('open'); return; }
});

/* 사이드바 검색 */
const search = document.querySelector('.sb-search');
search.addEventListener('input', () => {
  const q = search.value.trim().toLowerCase();
  document.querySelectorAll('.nav-group').forEach(g => {
    const hitHead = g.querySelector('.nav-head').textContent.toLowerCase().includes(q);
    let hitSub = false;
    g.querySelectorAll('.nav-sub').forEach(s => {
      const hit = !q || s.textContent.toLowerCase().includes(q);
      s.classList.toggle('hidden', !hit);
      if (hit && q) hitSub = true;
    });
    g.classList.toggle('hidden', !(!q || hitHead || hitSub));
    if (q && hitSub) g.classList.add('open');
  });
});

/* 문제 — 정오 표시·해설 공개는 CSS(:checked)가 하고, JS 는 집계와 저장만 얹는다 */
const KEY = 'gm-quiz-v1';
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch(e){ state = {}; }
function save(){ try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e){} }

function tally(){
  const qs = document.querySelectorAll('.q');
  let done = 0, ok = 0;
  qs.forEach(q => {
    const picked = q.querySelector('.qr:checked');
    if (picked){ done++; if (picked.classList.contains('ans')) ok++; }
  });
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('qb-done', done); set('qb-ok', ok);
  set('qb-rate', done ? Math.round(ok/done*100) : 0);
  const fill = document.getElementById('qb-fill');
  if (fill) fill.style.width = (qs.length ? done / qs.length * 100 : 0) + '%';
}

function clear(q){
  q.querySelectorAll('.qr').forEach(r => { r.checked = false; });
}

document.querySelectorAll('.q').forEach(q => {
  const n = q.dataset.n;
  const saved = state[n];
  if (saved){
    const r = q.querySelector('.qr.i' + saved);
    if (r) r.checked = true;
  }
  q.querySelectorAll('.qr').forEach(r => {
    r.addEventListener('change', () => {
      const m = r.className.match(/\bi(\d)\b/);
      state[n] = m ? +m[1] : 0;
      save(); tally();
    });
  });
  const again = q.querySelector('.q-again');
  if (again) again.addEventListener('click', () => {
    delete state[n]; save(); clear(q); tally();
    q.scrollIntoView({block:'nearest'});
  });
});

const reset = document.getElementById('qb-reset');
if (reset) reset.addEventListener('click', () => {
  state = {}; save();
  try { localStorage.removeItem(KEY); } catch(e){}
  document.querySelectorAll('.q').forEach(clear);
  tally();
});

tally();

/* 해시가 노트 id 면 그 노트를, 섹션 id 면 그 섹션이 속한 노트를 연다 */
(function(){
  const h = location.hash.slice(1);
  if (!h) { showDoc(docs[0].id); return; }
  if (document.getElementById(h) && document.getElementById(h).classList.contains('doc')){
    showDoc(h); return;
  }
  const el = document.getElementById(h);
  const owner = el && el.closest('.doc');
  if (owner) showDoc(owner.id, h); else showDoc(docs[0].id);
})();
"""


def render_page(docs, css, subject, nq, title=None):
    title = title or subject
    nav = []
    for d in docs:
        cnt = f'<span class="nav-cnt">{d["nq"]}문항</span>' if d["nq"] else ""
        nav.append(f'<div class="nav-group" data-doc="{d["id"]}">')
        # button 이 아니라 a — JS 를 못 쓰는 뷰어에서도 앵커로 이동한다
        nav.append(
            f'<a class="nav-head nav-link" href="#{d["id"]}" data-doc="{d["id"]}">'
            f'<span class="nav-ico">{d["num"] or "◆"}</span>'
            f'<span>{html.escape(d["title"].split("(")[0].strip())}</span>{cnt}'
            f'<span class="nav-arrow js-only">▶</span></a>'
        )
        nav.append('<div class="nav-items">')
        for _lv, txt, hid in d["secs"]:
            nav.append(
                f'<a class="nav-sub" href="#{hid}" data-doc="{d["id"]}" data-anchor="{hid}">'
                f'{html.escape(txt)}</a>'
            )
        nav.append("</div></div>")

    body = []
    for d in docs:
        chips = []
        if d["created"]:
            chips.append(f'<span class="chip">작성 {html.escape(d["created"])}</span>')
        if d["nq"]:
            chips.append(f'<span class="chip">인터랙티브 {d["nq"]}문항</span>')
        body.append(
            f'<article class="doc" id="{d["id"]}" data-title="{html.escape(d["title"])}">'
            f'<div class="section-block"><div class="block-h">{html.escape(d["title"])}</div>'
            f'<div class="doc-meta">{"".join(chips)}</div>'
            f'<div class="exp-card"><div class="note-body">{d["body"]}</div></div>'
            f"</div></article>"
        )

    today = date.today().isoformat()
    return f"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} 학습노트</title>
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
{css}
{EXTRA_CSS}
</style>
</head><body>
<div id="wrap">
  <nav class="sidebar">
    <div class="brand">🧫 {html.escape(title)}</div>
    <div class="brand-sub">{html.escape(subject)} · 학습노트 {len(docs)}편 · 예상문제 {nq}문항</div>
    <input class="sb-search" placeholder="노트·섹션 검색…">
    {"".join(nav)}
  </nav>
  <div id="main">
    <div class="topbar">
      <button class="hamburger">☰</button>
      <h1 id="topTitle">{html.escape(title)}</h1>
      <span class="meta">빌드 {today}</span>
    </div>
    <div class="container">
      <div class="nojs-tip">이 뷰어는 JavaScript 를 실행하지 않아 노트 {len(docs)}편이 위아래로
      이어져 보입니다. 문제 풀이(보기 선택 → 정답·해설)는 그대로 됩니다.
      점수 집계·노트 전환·검색까지 쓰려면 Safari·Chrome 같은 브라우저로 여세요.</div>
      {"".join(body)}
      <div class="footer">볼트 · 04_References/Notes/{html.escape(subject)} 에서 생성 ·
      _Tools/course-html/build_course_html.py</div>
    </div>
  </div>
</div>
<script>
{JS}
</script>
</body></html>
"""


if __name__ == "__main__":
    build()
