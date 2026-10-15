#!/usr/bin/env python3
"""HTML 산출물 자체 검사 — 템플릿·디자인과 무관하게 돈다.

내용 규칙은 `_Tools/html-templates/내용-규칙.md` 에 있고, 이 스크립트는 그중
**기계로 잡을 수 있는 것만** 본다. 나머지는 사람이 봐야 한다.

    python3 _Tools/html-templates/check_html.py <파일.html>
    python3 _Tools/html-templates/check_html.py <파일.html> --sizes 1920x1080,1440x900

슬라이드(.slide)가 있으면 **잘리는 슬라이드**까지 추가로 본다.
자동 축소가 있는 덱은 잘려도 눈에 잘 안 띄기 때문에 이 검사가 가장 중요하다.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/opt/homebrew/bin/chromium",
]

# 내용-규칙 §3 — 볼트 안에서만 쓰는 말
LEAK_PATTERNS = [
    (r"축 ?[①②③]|축[123]\b", "내부 축 번호"),
    (r"확정본|evidence-check|session-log|STATUS\.md", "볼트 문서 이름"),
    (r"\[\[", "wikilink"),
    (r"랩 질문", "「랩 질문」"),
    (r"\[(?:my-decision|reported|confirmed|revised|tentative)\]", "의사결정 태그"),
    (r"20\d{2}-\d{2}-\d{2} ?확정", "날짜 도장"),
]

# 내용-규칙 §5 — 제목은 명사형. 아래는 «명사가 아닌 종결»로 끝나는 꼴만 좁게 잡는다.
#   `-습니다/-입니다` 만 보던 원래 규칙은 `-는가` `-한다` `-된다` 를 통째로 놓쳤다.
PREDICATIVE = re.compile(
    r"("
    r"다"                                   # 한다·된다·본다·아니다 …  (한국어 명사는 거의 -다로 안 끝난다)
    r"|까|죠"                                # -ㄹ까·-죠
    r"|(?:어|아|에|지|해|세|네|고|데)요"          # -해요·-지요  («필요»·«중요» 같은 명사는 안 걸린다)
    r"|(?:는|은|인|한|운|린|난|던|을|였|했|겠)가"   # -는가·-인가·-한가
    r"|(?:는|은|인|한)지"                     # -는지
    r"|(?:느|는)냐"                          # -느냐
    r")$"
)
# -다 로 끝나는 정상 명사 (오탐 방지). 필요하면 여기에 추가한다.
NOUN_DA = {"바다", "소다", "사이다", "레모네이다", "스프레다"}


def nonnoun_titles(src):
    """명사로 끝나지 않는 제목을 (태그, 본문) 으로 돌려준다. h3(카드 소제목)까지 본다."""
    hits = []
    for tag in ("h1", "h2", "h3"):
        for raw in re.findall(r"<%s\b[^>]*>(.*?)</%s>" % (tag, tag), src, re.S):
            txt = re.sub(r"<[^>]+>", "", raw)
            txt = re.sub(r"\s+", " ", txt).strip().rstrip(".·…!?")
            if not txt:
                continue
            last = txt.split()[-1]
            if last in NOUN_DA:
                continue
            if PREDICATIVE.search(txt):
                hits.append((tag, txt))
    return hits


# 내용-규칙 §5·§5-1 — **본문도 명사형·항목형으로 쓴다.**
#   제목과 .lead 만 보던 원래 규칙은 «표 칸·목록이 줄글 서술형으로 차는» 문제를 못 잡았고,
#   그래서 같은 지적이 덱을 만들 때마다 반복됐다 (2026-09-10 신설).
#   여기 패턴은 **오탐이 사실상 없는 종결만** 담는다 — 「명사형 아닌 제목」(warn)과 달리 err 다.
BODY_PRED = re.compile(
    r"("
    r"다"                                       # 한다·된다·아니다 …
    r"|(?:는|은|인|한|운|린|난|던|을|였|했|겠)가"    # -는가·-인가  (의문형)
    r"|(?:는|은|인|한)지"                         # -는지
    r"|(?:느|는)냐"
    r"|(?:습|입)니다"
    r"|(?:어|아|에|지|해|세|네|고|데)요"
    r"|죠|까"
    r")$"
)

# 본문에서 볼 자리 — 표 칸 · 목록 · 용어 풀이 · 그림 설명 · 레퍼런스 · 보조 설명 · 제목
BODY_TAGS = ("td", "li", "dd", "h1", "h2", "h3")
BODY_CLASSES = ("fig-cap", "refs", "note")


def declarative_body(src):
    """본문 조각 중 서술형·의문형으로 끝나는 것을 (슬라이드번호, 태그, 본문)으로 돌려준다."""
    bodies = re.findall(
        r'<section[^>]*class="[^"]*\bslide\b[^"]*"[^>]*>(.*?)</section>', src, re.S)
    if not bodies:
        bodies = [src]
    hits = []
    for i, b in enumerate(bodies, 1):
        b = re.sub(r"<svg\b.*?</svg>", "", b, flags=re.S)   # 그림 안 글자는 이 검사에서 뺀다
        chunks = []
        for tag in BODY_TAGS:
            chunks += [(tag, x) for x in
                       re.findall(r"<%s\b[^>]*>(.*?)</%s>" % (tag, tag), b, re.S)]
        for cls in BODY_CLASSES:
            for raw in re.findall(r'<[^>]+class="%s"[^>]*>(.*?)</[^>]+>' % cls, b, re.S):
                chunks += [(cls, x) for x in re.split(r"<br\s*/?>", raw)]
        for tag, raw in chunks:
            t = re.sub(r"<[^>]+>", "", raw)
            t = re.sub(r"&[a-zA-Z]+;|&#\d+;", " ", t)
            t = re.sub(r"\s+", " ", t).strip()
            if not t:
                continue
            if t[0] in "「『«≪" and t[-1] in "」』»≫":
                continue                                    # 통째로 인용한 문장은 봐준다
            t = t.rstrip(".·…!?」』≫\"'）)]")
            if not t or t.split()[-1] in NOUN_DA:
                continue
            if BODY_PRED.search(t):
                hits.append((i, tag, t[-44:]))
    return hits


# 내용-규칙 §1·§2 — 읽는 사람이 아니라 작성자에게 하는 말
SELF_TALK = [
    "로 인용합니다", "쓰면 안 됩니다", "라고 말하면", "로 팔지 않습니다",
    "프레이밍", "정확한 문장은", "의견을 듣고 싶습니다",
    "다음 장이", "앞 슬라이드", "앞 세 장", "위 표 참조", "아래 절",
]


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def static_checks(src, is_deck):
    """텍스트만 보고 잡을 수 있는 것. (name, 값, 통과, 등급)"""
    out = []

    # 발표물은 현장에서 인터넷 없이 열려야 하므로 오류, 문서형은 시스템 폰트로 떨어지므로 경고
    ext = re.findall(r'(?:src|href)="https?://[^"]*"', src)
    out.append(("외부 리소스", f"{len(ext)}건" + (f" — {ext[0][:60]}" if ext else ""),
                not ext, "err" if is_deck else "warn"))

    # 이모지는 발표물에서 팔레트와 충돌한다. 문서형의 UI 아이콘까지 막지는 않는다
    emoji = re.findall(r"[\U0001F300-\U0001FAFF☀-➿️]", src)
    out.append(("이모지", f"{len(emoji)}개" + (f" — {''.join(sorted(set(emoji))[:6])}" if emoji else ""),
                not emoji, "err" if is_deck else "warn"))

    narrative = re.findall(r"<h[1-3]\b[^>]*>[^<]*(?:습니다|입니다)</h[1-3]>", src)
    out.append(("서술형 제목", f"{len(narrative)}개" + (f" — {narrative[0][:44]}" if narrative else ""),
                not narrative, "err" if is_deck else "warn"))

    # 명사형 여부는 정규식으로 100 % 갈리지 않는다(«네 가지»·«단가» 류). 그래서 err 가 아니라 warn 이고,
    # 걸린 제목을 전부 찍어 사람이 판정하게 한다.
    nonnoun = nonnoun_titles(src)
    out.append(("명사형 아닌 제목", f"{len(nonnoun)}개", not nonnoun, "warn",
                [f"<{t}> {x}" for t, x in nonnoun[:12]]))

    leaks = []
    for pat, name in LEAK_PATTERNS:
        hits = re.findall(pat, src)
        if hits:
            leaks.append(f"{name} {len(hits)}건")
    out.append(("볼트 용어 유출", ", ".join(leaks) if leaks else "0건", not leaks, "err"))

    talk = [t for t in SELF_TALK if t in src]
    out.append(("작성자에게 하는 말투", ", ".join(talk) if talk else "0건", not talk, "warn"))

    # 표 칸·목록·레퍼런스까지 본다. 제목만 보던 규칙이 반복 지적을 못 잡았다 (2026-09-10)
    body_pred = declarative_body(src)
    out.append(("서술형으로 끝나는 본문", f"{len(body_pred)}개", not body_pred,
                "err" if is_deck else "warn",
                [f"{i}장 <{t}> \u2026{x}" for i, t, x in body_pred[:14]]))

    # 절차표의 번호 칸에 «1-1» 같은 하위 번호를 넣으면 좁은 칸에서 «1–» / «1» 두 줄로 꺾인다 (2026-09-27 지적).
    # 하위 단계를 만들지 말고 1, 2, 3 … 으로 다시 매긴다
    subnum = re.findall(r'<t[dh][^>]*class="[^"]*\b(?:n|id)\b[^"]*"[^>]*>\s*(\d+\s*[-–]\s*\d+)\s*</t[dh]>', src)
    subnum += re.findall(r'class="badge">\s*(\d+\s*[-–]\s*\d+)\s*<', src)
    out.append(("번호 칸의 하위 번호", f"{len(subnum)}개" + (f" — {', '.join(subnum[:6])}" if subnum else ""),
                not subnum, "warn"))

    if is_deck:
        bodies = re.findall(
            r'<section[^>]*class="[^"]*\bslide\b[^"]*"[^>]*>(.*?)</section>', src, re.S)

        # 내용-규칙 §5-1 — 제목이 있는 슬라이드에는 레퍼런스 줄이 반드시 있어야 한다.
        # 산문을 걷어내면서 레퍼런스까지 같이 지운 사고가 실제로 나서 warn 에서 err 로 올렸다.
        missing = [b for b in bodies if "<h2>" in b and 'class="refs"' not in b]
        titles = [re.search(r"<h2>(.*?)</h2>", b, re.S) for b in missing]
        out.append(("레퍼런스 줄 없는 본문 슬라이드", f"{len(missing)}장", not missing, "err",
                    [re.sub(r"<[^>]+>", "", t.group(1)).strip() for t in titles if t][:12]))

        # 내용-규칙 §5-1 — 설명용 산문 블록 금지. 설명은 표 칸이나 .calc 로 내린다.
        prose = []
        for b in bodies:
            for cls in ("concl", "foot"):
                prose += [cls] * len(re.findall(r'class="%s\b' % cls, b))
            prose += ["p"] * len(re.findall(r"<p>", b))          # 클래스 없는 문단
        kinds = ", ".join(f"{k} {prose.count(k)}" for k in ("concl", "foot", "p")
                          if prose.count(k))
        out.append(("설명용 산문 블록", kinds if prose else "0개", not prose, "err"))

        # 내용-규칙 §5-1 — 고정폭 상자(.calc) 자체를 쓰지 않는다. 한글이 들어가면 자간이
        # 벌어지고 줄바꿈이 문장 중간에서 끊긴다. 같은 지적을 네 번 받고서 컴포넌트를 없앴다.
        # 계산·단계·목록은 전부 표로 쓴다.
        calcs = re.findall(r'<div class="calc[^"]*"[^>]*>(.*?)</div>', "".join(bodies), re.S)
        heads = [re.sub(r"<[^>]+>", "", c).strip().split("\n")[0][:40] for c in calcs]
        out.append(("고정폭 상자(.calc)", f"{len(calcs)}개", not calcs, "err", heads[:10]))

        # 한 줄 범위(.lead)·표지 부제(.subtitle)도 명사형으로 끝낸다
        lead_sent = []
        for b in bodies:
            for cls in ("lead", "subtitle"):
                for raw in re.findall(r'<p class="%s">(.*?)</p>' % cls, b, re.S):
                    t = re.sub(r"<[^>]+>", "", raw).replace("\n", " ").strip().rstrip(".·…")
                    if t and PREDICATIVE.search(t) and t[-1] not in "요":
                        lead_sent.append(t[:70])
        out.append(("서술형으로 끝나는 한 줄 범위", f"{len(lead_sent)}개", not lead_sent, "err",
                    lead_sent[:10]))
    return out


PROBE = r"""
<script>
window.__err = [];
window.onerror = function (m) { window.__err.push(String(m)); };
setTimeout(async function () {
  var r = { cut: [], scale: {}, err: window.__err };
  try { await document.fonts.ready; } catch (e) {}
  r.fonts = ['400 16px Pretendard', '600 16px Pretendard'].map(function (f) {
    try { return document.fonts.check(f); } catch (e) { return null; }
  });
  r.noshell = 0;
  document.querySelectorAll('.slide').forEach(function (sl, i) {
    var inner = sl.querySelector('.slide-inner');
    if (!inner) { r.noshell++; return; }
    var cs = getComputedStyle(sl);
    var avail = sl.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    var k = parseFloat(inner.dataset.fit || '1');
    var used = inner.scrollHeight * k;
    var id = sl.id || ('#' + (i + 1));
    if (k < 1) r.scale[id] = +k.toFixed(3);
    if (used > avail + 1) r.cut.push(id + ' (' + Math.round(used) + '>' + Math.round(avail) + ')');
  });
  r.hscroll = [document.body.scrollWidth, window.innerWidth];
  var d = document.createElement('pre');
  d.id = 'HTMLCHECK';
  d.textContent = JSON.stringify(r);
  document.body.appendChild(d);
}, 1600);
</script></body>"""


def render_check(chrome, src, srcdir, w, h, is_deck):
    page = src.replace("</body>", PROBE, 1)
    if is_deck:
        page = page.replace(
            "</head>",
            "<style>html{scroll-behavior:auto}body{scroll-snap-type:none}</style></head>", 1)
    fd, tmp = tempfile.mkstemp(suffix=".html", dir=srcdir)
    with os.fdopen(fd, "w") as f:
        f.write(page)
    try:
        r = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={w},{h}", "--virtual-time-budget=6000",
             "--dump-dom", "file://" + tmp],
            capture_output=True, text=True, timeout=90)
        m = re.search(r'<pre id="HTMLCHECK">(.*?)</pre>', r.stdout, re.S)
        if not m:
            return None
        raw = m.group(1).replace("&quot;", '"').replace("&amp;", "&") \
                        .replace("&lt;", "<").replace("&gt;", ">")
        return json.loads(raw)
    finally:
        os.unlink(tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--sizes", default="1920x1080,1440x900,1280x800")
    args = ap.parse_args()

    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        sys.exit(f"파일이 없다: {path}")
    src = open(path).read()

    n_slides = len(re.findall(r'<section[^>]*class="[^"]*\bslide\b', src))
    is_deck = n_slides > 0
    kind = f"슬라이드 {n_slides}장" if is_deck else "문서형"

    bad = False
    print(f"\n검사: {os.path.basename(path)}  ({round(os.path.getsize(path)/1024)} KB · {kind})")
    print("규칙: _Tools/html-templates/내용-규칙.md\n")

    print("── 내용 검사 (템플릿 무관) " + "─" * 32)
    for row in static_checks(src, is_deck):
        name, val, ok, level = row[:4]
        detail = row[4] if len(row) > 4 else []
        mark = "✅" if ok else ("⚠️ " if level == "warn" else "🔴")
        print(f"{mark} {name:24s} {val}")
        for d in (detail if not ok else []):
            print(f"      · {d}")
        if not ok and level != "warn":
            bad = True

    chrome = find_chrome()
    if not chrome:
        print("\n⚠️  Chrome 을 못 찾아 렌더 검사를 건너뛴다"
              + (" — 잘림은 이 검사로만 잡힌다" if is_deck else ""))
        sys.exit(1 if bad else 0)

    print("\n── 렌더 검사 " + "─" * 45)
    for size in args.sizes.split(","):
        w, h = size.strip().split("x")
        res = render_check(chrome, src, os.path.dirname(path), w, h, is_deck)
        if res is None:
            print(f"🔴 {size:>10s}  렌더 실패")
            bad = True
            continue
        cut, err = res.get("cut", []), res.get("err", [])
        noshell = res.get("noshell", 0)
        sw, iw = res.get("hscroll", [0, 0])
        hscroll = sw > iw
        problem = cut or err or hscroll or noshell
        line = f"{'✅' if not problem else '🔴'} {size:>10s}  "
        tight = []
        if is_deck:
            scales = res.get("scale", {})
            worst = min(scales.values(), default=1.0)
            # 내용-규칙 §13 — 축소는 마지막 수단이다. 0.85 밑이면 «내용이 너무 많다» 는 뜻이라 쪼갠다
            tight = sorted([k for k, v in scales.items() if v < 0.85])
            line += f"잘림 {len(cut)}장 · 최소배율 {worst:.3f} · "
        line += f"가로 {sw}/{iw} · JS오류 {len(err)}"
        if res.get("fonts") and any(res["fonts"]) and not all(res["fonts"]):
            line += " · ⚠️ 폰트 일부 미로드"
        print(line)
        if cut:
            print("      → 잘림:", ", ".join(cut))
        if tight:
            print("      → ⚠️  배율 0.85 미만(내용 과다 — 쪼갤 것):", ", ".join(tight))
        if err:
            print("      → JS:", err[0])
        if hscroll:
            print("      → 가로 스크롤 발생")
        if noshell:
            print(f"      → 🔴 .slide-inner 가 없는 슬라이드 {noshell}장 "
                  "— 이 장들은 잘림 검사를 못 한다 (셸 구조를 지켜야 한다)")
        if problem:
            bad = True

    print("\n" + ("🔴 고쳐야 할 것이 있다." if bad else "✅ 통과. 이제 눈으로 볼 차례."))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
