#!/usr/bin/env python3
"""학습노트 폴더 → **노트 1편당 HTML 1개** (읽기용, self-contained).

    python3 _Tools/course-html/build_note_pages.py <노트폴더> <출력폴더> [표시제목]

`build_course_html.py` 가 전 노트를 한 파일에 묶어 문제까지 풀게 하는 뷰어라면,
이쪽은 **한 편씩 열어 읽는 페이지**다. 한 화면에 한 노트만 있으므로 스크롤·인쇄·공유가 쉽다.

- 디자인·마크다운 변환·콜아웃 처리는 `build_course_html.py` 의 함수를 그대로 쓴다
- 사이드바 = 그 노트의 `##` 목차 + 다른 노트로 가는 링크(같은 폴더의 .html 로 이동)
- 위키링크는 같은 세트 안의 노트면 그 노트의 HTML 로, 아니면 밑줄 없는 글자로 남는다
- **JavaScript 를 전혀 쓰지 않는다.** JS 를 막는 뷰어에서도, 인쇄해도 그대로 보인다
- **번호가 붙은 강의 노트(`01-`~)만** 만든다. MOC·개념 노트처럼 번호 없는 노트는 강의 밖에서
  덧붙인 것이라 이 페이지 세트에 섞지 않는다
- 문제 노트(`## C. 예상문제 …`)는 통합 뷰어와 똑같이 **보기를 고르면 정답·해설이 나오는**
  인터랙티브 블록으로 만든다. 원본의 정답표는 페이지에서 빠지므로 미리 보이지 않는다
- 목차 페이지 `00-목차.html` 을 함께 만든다 (각 노트의 "핵심 한 줄 요약" 을 뽑아 붙인다)
"""
import html
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_course_html as B  # noqa: E402

INDEX_NAME = "00-목차.html"

# 문제 페이지에만 붙인다. 정오 표시·해설 공개는 CSS(:checked)가 하므로, 이 스크립트가
# 없어도(JS 를 막는 뷰어) 문제는 그대로 풀린다. 여기서 더하는 건 집계·초기화·기록뿐이다.
QUIZ_JS = """<script>
document.body.classList.add('js');
(function(){
  var qs=[].slice.call(document.querySelectorAll('.q'));
  var KEY='notepage-quiz:'+document.title;
  var done=document.getElementById('qb-done'), ok=document.getElementById('qb-ok'),
      rate=document.getElementById('qb-rate'), fill=document.getElementById('qb-fill');
  function save(){
    var s={};
    qs.forEach(function(q){var r=q.querySelector('.qr:checked'); if(r)s[q.dataset.n]=r.id;});
    try{localStorage.setItem(KEY,JSON.stringify(s));}catch(e){}
  }
  function upd(){
    var d=0,c=0;
    qs.forEach(function(q){
      var r=q.querySelector('.qr:checked');
      if(r){d++; if(r.classList.contains('ans'))c++;}
    });
    if(done)done.textContent=d;
    if(ok)ok.textContent=c;
    if(rate)rate.textContent=d?Math.round(c/d*100):0;
    if(fill)fill.style.width=(qs.length?d/qs.length*100:0)+'%';
  }
  try{
    var saved=JSON.parse(localStorage.getItem(KEY)||'{}');
    Object.keys(saved).forEach(function(k){
      var el=document.getElementById(saved[k]); if(el)el.checked=true;
    });
  }catch(e){}
  document.addEventListener('change',function(e){
    if(e.target.classList&&e.target.classList.contains('qr')){upd();save();}
  });
  document.addEventListener('click',function(e){
    var again=e.target.closest&&e.target.closest('.q-again');
    if(again){
      var q=again.closest('.q');
      q.querySelectorAll('.qr').forEach(function(r){r.checked=false;});
      upd(); save(); return;
    }
    if(e.target.id==='qb-reset'){
      document.querySelectorAll('.qr').forEach(function(r){r.checked=false;});
      upd(); save();
    }
  });
  upd();
})();
</script>"""

PAGE_CSS = """
/* --- 노트 1편 = 페이지 1개 (읽기용) --- */
.nav-note{display:flex;align-items:center;gap:8px;padding:7px 18px;font-size:13px;
  color:rgba(255,255,255,.75);text-decoration:none;border-left:3px solid transparent}
.nav-note:hover{color:#fff;background:rgba(255,255,255,.08)}
.nav-note.cur{color:#fff;background:rgba(255,255,255,.14);border-left-color:var(--primary);
  font-weight:700}
.nav-note .nav-ico{width:18px;text-align:center;font-size:11px;opacity:.75}
.nav-cap{padding:14px 18px 6px;font-size:10.5px;font-weight:800;letter-spacing:.06em;
  color:rgba(255,255,255,.38)}
.pager{display:flex;gap:10px;margin-top:26px}
.pager a{flex:1;min-width:0;padding:13px 16px;border-radius:var(--radius);
  background:var(--card);border:1px solid var(--border);text-decoration:none;
  color:var(--dark);font-size:13.5px;font-weight:700}
.pager a:hover{box-shadow:0 .3rem 1.2rem rgba(58,59,69,.14)}
.pager .to-next{text-align:right}
.pager .lbl{display:block;font-size:11px;font-weight:600;color:var(--muted);
  margin-bottom:3px}
.toc-list{list-style:none;padding:0;margin:0}
.toc-list li{display:flex;gap:14px;padding:14px 2px;border-bottom:1px solid var(--border)}
.toc-list li:last-child{border-bottom:none}
.toc-num{flex:0 0 34px;font-size:13px;font-weight:800;color:var(--primary);
  padding-top:2px}
.toc-t{font-size:15px;font-weight:700;color:var(--dark);text-decoration:none}
.toc-t:hover{color:var(--primary)}
.toc-s{margin-top:4px;font-size:13.5px;color:#5b5e68;line-height:1.65}
@media(max-width:820px){
  /* 문제 페이지는 js 클래스가 붙으므로, 좁은 화면 레이아웃을 여기서 못 박는다 */
  #wrap{display:block}
  .sidebar{position:static;width:100%;height:auto;transform:none;padding-bottom:12px}
  #main{margin-left:0}
}
@media print{
  .sidebar,.pager,.topbar{display:none!important}
  #main{margin-left:0}
  .container{max-width:none;padding:0}
  .exp-card{border:none;box-shadow:none;padding:0}
}
"""


def norm(s):
    return unicodedata.normalize("NFC", s)


def wikilinks_to_files(s, filemap):
    """[[노트]] → 같은 폴더의 그 노트 HTML 로. 세트 밖이면 글자만 남긴다."""
    def rep(m):
        target = norm(m.group(1).split("#")[0].strip())
        label = (m.group(2) or m.group(1)).strip()
        if target in filemap:
            return f'<a class="wl" href="{html.escape(filemap[target])}">{html.escape(label)}</a>'
        return f'<span class="wl-off">{html.escape(label)}</span>'

    return re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]", rep, s)


def one_liner(lines):
    """'## 핵심 한 줄 요약' 아래 첫 문단. 없으면 빈 문자열."""
    for i, l in enumerate(lines):
        if l.startswith("## ") and "핵심 한 줄 요약" in l:
            buf = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("#") or nxt.strip() in ("---", ""):
                    if buf:
                        break
                    continue
                buf.append(nxt.strip())
            return " ".join(buf)
    return ""


def sort_key(p):
    st = norm(p.stem)
    m = re.match(r"^(\d{2})-", st)
    if st.startswith("MOC"):
        return (0, 0, st)
    return (1, int(m.group(1)), st) if m else (2, 0, st)


def shell(title, subject, page_title, sidebar, main, css, script=""):
    return f"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(page_title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
{css}
</style>
</head><body>
<div id="wrap">
  <nav class="sidebar">
    <div class="brand">🧫 {html.escape(title)}</div>
    <div class="brand-sub">{html.escape(subject)}</div>
    {sidebar}
  </nav>
  <div id="main">
{main}
  </div>
</div>
{script}
</body></html>
"""


def build():
    if len(sys.argv) < 3:
        sys.exit("사용법: build_note_pages.py <노트폴더> <출력폴더> [표시제목]")
    src = Path(sys.argv[1]).expanduser()
    out = Path(sys.argv[2]).expanduser()
    title = sys.argv[3] if len(sys.argv) > 3 else B.subject_title(src)

    files = [p for p in sorted(src.glob("*.md"), key=sort_key)
             if re.match(r"^\d{2}-", norm(p.stem))]
    if not files:
        sys.exit(f"노트를 찾지 못했다: {src}")

    filemap = {norm(p.stem): f"{norm(p.stem)}.html" for p in files}
    css = B.CSS_FILE.read_text(encoding="utf-8") + B.EXTRA_CSS + PAGE_CSS
    today = date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)

    notes = []
    for path in files:
        meta, text = B.strip_frontmatter(path.read_text(encoding="utf-8"))
        lines = text.splitlines()
        questions = []
        if "예상문제" in norm(path.stem) or any(l.startswith("## C. 예상문제") for l in lines):
            questions, lines = B.parse_quiz(lines)
        docid = "n" + re.sub(r"\W+", "-", norm(path.stem))[:40]
        heads = B.heading_ids([l for l in lines if not l.startswith("# ")], docid)
        body = B.to_html("\n".join(B.convert_callouts(
            [l for l in lines if not l.startswith("# ")])))
        body = B.apply_ids(body, heads)
        body = wikilinks_to_files(body, filemap)
        body = re.sub(r"<table[^>]*>", lambda m: '<div class="tw">' + m.group(0), body)
        body = re.sub(r"</table>", "</table></div>", body)
        if questions:
            quiz = B.render_quiz(questions, {})
            body = re.sub(r"<p>\s*\x00QUIZ\x00\s*</p>", lambda m: quiz, body)
            body = body.replace("\x00QUIZ\x00", quiz)
        num = re.match(r"^(\d{2})-", norm(path.stem))
        notes.append({
            "stem": norm(path.stem),
            "file": filemap[norm(path.stem)],
            "title": next((l.lstrip("#").strip() for l in lines if l.startswith("# ")),
                          norm(path.stem)),
            "num": num.group(1) if num else "",
            "created": meta.get("created", ""),
            "summary": one_liner(lines) or (
                f"보기를 고르면 정답과 해설이 바로 나오는 {len(questions)}문항"
                if questions else ""),
            "body": body,
            "nq": len(questions),
            "secs": [h for h in heads if h[0] == 2],
        })

    def note_links(cur_stem):
        parts, cap = [], None
        for n in notes:
            want = "문제" if n["nq"] else "강의 노트"
            if want != cap:
                cap = want
                parts.append(f'<div class="nav-cap">{cap}</div>')
            cls = " cur" if n["stem"] == cur_stem else ""
            label = html.escape(n["title"].split("(")[0].strip())
            cnt = f'<span class="nav-cnt">{n["nq"]}문항</span>' if n["nq"] else ""
            parts.append(f'<a class="nav-note{cls}" href="{n["file"]}">'
                         f'<span class="nav-ico">{n["num"] or "◆"}</span>'
                         f'<span>{label}</span>{cnt}</a>')
        return "".join(parts)

    for i, n in enumerate(notes):
        toc = "".join(
            f'<a class="nav-sub" href="#{hid}">{html.escape(txt)}</a>'
            for _lv, txt, hid in n["secs"])
        sidebar = (
            f'<a class="nav-note" href="{INDEX_NAME}">'
            f'<span class="nav-ico">☰</span><span>목차</span></a>'
            + (f'<div class="nav-group open"><div class="nav-cap">이 노트 안</div>'
               f'<div class="nav-items">{toc}</div></div>' if toc else "")
            + note_links(n["stem"])
        )
        prev_n = notes[i - 1] if i else None
        next_n = notes[i + 1] if i + 1 < len(notes) else None
        pager = ['<div class="pager">']
        if prev_n:
            pager.append(f'<a class="to-prev" href="{prev_n["file"]}">'
                         f'<span class="lbl">이전</span>'
                         f'{html.escape(prev_n["title"].split("(")[0].strip())}</a>')
        if next_n:
            pager.append(f'<a class="to-next" href="{next_n["file"]}">'
                         f'<span class="lbl">다음</span>'
                         f'{html.escape(next_n["title"].split("(")[0].strip())}</a>')
        pager.append("</div>")
        chip = (f'<div class="doc-meta"><span class="chip">작성 '
                f'{html.escape(n["created"])}</span></div>' if n["created"] else "")
        main = f"""    <div class="topbar">
      <h1>{html.escape(n["title"])}</h1>
      <span class="meta">{html.escape(title)} · 빌드 {today}</span>
    </div>
    <div class="container">
      <div class="section-block">
        <div class="block-h">{html.escape(n["title"])}</div>
        {chip}
        <div class="exp-card"><div class="note-body">{n["body"]}</div></div>
      </div>
      {"".join(pager)}
      <div class="footer">노트 {i + 1} / {len(notes)}</div>
    </div>"""
        (out / n["file"]).write_text(
            shell(title, f"{title} · 노트 {i + 1}/{len(notes)}",
                  f'{n["title"]} — {title}', sidebar, main, css,
                  script=QUIZ_JS if n["nq"] else ""),
            encoding="utf-8")

    rows = []
    for n in notes:
        summary = (f'<div class="toc-s">{B.inline_md(n["summary"])}</div>'
                   if n["summary"] else "")
        rows.append(
            f'<li><div class="toc-num">{n["num"] or "◆"}</div><div>'
            f'<a class="toc-t" href="{n["file"]}">{html.escape(n["title"])}</a>'
            f'{summary}</div></li>')
    main = f"""    <div class="topbar">
      <h1>{html.escape(title)} — 노트 목차</h1>
      <span class="meta">빌드 {today}</span>
    </div>
    <div class="container">
      <div class="section-block">
        <div class="block-h">노트 {len(notes)}편</div>
        <div class="exp-card"><ul class="toc-list">{"".join(rows)}</ul></div>
      </div>
    </div>"""
    (out / INDEX_NAME).write_text(
        shell(title, f"{title} · 노트 {len(notes)}편", f"{title} 노트 목차",
              note_links(""), main, css), encoding="utf-8")

    total = sum((out / n["file"]).stat().st_size for n in notes)
    print(f"OK  {out}  (페이지 {len(notes) + 1}개, 합계 {total // 1024} KB)")


if __name__ == "__main__":
    build()
