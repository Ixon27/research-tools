# -*- coding: utf-8 -*-
"""문제은행 → ① HTML 확인시험  ② 시험대비 노트의 예상문제 절 을 동시에 생성."""
import io, os, re, json, html as H
from bank import TITLE, SECTIONS   # 문제은행: bank.py (형식은 bank.py 예시 참고)

CIRCLE = ["①", "②", "③", "④"]

# 선택: 환경변수 QUIZ_NOTE 에 노트(.md) 경로를 주면 그 노트의 '# C. 예상문제' ~ '# D. 마무리 체크' 사이를 문항으로 갈아 끼운다
NOTE = os.environ.get('QUIZ_NOTE')
OUT_HTML = os.environ.get('QUIZ_OUT', f'{TITLE}_확인시험.html')


def to_html(s):
    s = H.escape(s, quote=False)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<i>\1</i>', s)
    return s.replace('\n', '<br>')


def to_md_cell(s):
    return s.replace('\n', ' ')


# ---------- 무결성 검사 ----------
seen = set()
for title, qs in SECTIONS:
    for q, opts, ans, exp in qs:
        assert len(opts) == 4, (title, q[:30], len(opts))
        assert ans in (1, 2, 3, 4), (title, q[:30], ans)
        key = re.sub(r'\W', '', q)[:50]
        assert key not in seen, ('중복 문항: ' + q[:50])
        seen.add(key)

TOTAL = sum(len(qs) for _, qs in SECTIONS)

# ---------- 정답 위치 균등화 ----------
# 원본은 정답이 ②에 쏠려 있다. 보기를 회전(rotation)시켜 정답 위치를 1→2→3→4 로 돌린다.
# 회전이므로 보기 사이의 상대 순서는 유지되고, 해설이 참조하는 ①②③④ 는 같은 회전으로 재매핑한다.
_CIRC_IDX = {c: i for i, c in enumerate(CIRCLE)}

def _balance(sections):
    out, t = [], 0
    for title, qs in sections:
        nq = []
        for q, opts, ans, exp in qs:
            a = ans - 1
            k = (t - a) % 4                      # 원래 i번 보기 -> 새 (i+k)%4 번
            t = (t + 1) % 4
            new_opts = [None] * 4
            for i, o in enumerate(opts):
                new_opts[(i + k) % 4] = o
            new_exp = re.sub(r'[①②③④]',
                             lambda m: CIRCLE[(_CIRC_IDX[m.group(0)] + k) % 4], exp)
            nq.append((q, new_opts, (a + k) % 4 + 1, new_exp))
        out.append((title, nq))
    return out

SECTIONS = _balance(SECTIONS)

# ---------- HTML ----------
cards, answers, idx = [], {}, 0
for title, qs in SECTIONS:
    cards.append(f'\n        <h2 class="section-title">{H.escape(title)} <span class="sec-count">{len(qs)}문항</span></h2>')
    for q, opts, ans, exp in qs:
        idx += 1
        answers[f'q{idx}'] = str(ans)
        ol = "\n".join(
            f'                <li class="option-item"><label>'
            f'<input type="radio" name="q{idx}" value="{i+1}"> '
            f'<span>{CIRCLE[i]} {to_html(o)}</span></label></li>'
            for i, o in enumerate(opts))
        cards.append(f'''
        <div class="question-card" id="q{idx}-card">
            <div class="question-title">{idx}. {to_html(q)}</div>
            <ul class="options">
{ol}
            </ul>
            <div class="explanation" id="q{idx}-exp">
                <strong>[정답: {CIRCLE[ans-1]}]</strong><br>
                {to_html(exp)}
            </div>
        </div>''')

body = "\n".join(cards)
answers_js = json.dumps(answers, ensure_ascii=False, indent=8)
sections_js = json.dumps([[t, len(qs)] for t, qs in SECTIONS], ensure_ascii=False)

DOC = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{TITLE} 확인 시험</title>
<style>
:root {{
    --primary-color: #2b5278; --primary-hover: #1e3a56;
    --bg-color: #f4f6f9; --card-bg: #ffffff; --text-color: #333333;
    --border-color: #e1e4e8;
    --correct-color: #2e7d32; --correct-bg: #e8f5e9;
    --incorrect-color: #c62828; --incorrect-bg: #ffebee;
}}
body {{
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto,
                 'Helvetica Neue', 'Segoe UI', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
    background-color: var(--bg-color); color: var(--text-color);
    line-height: 1.6; margin: 0; padding: 20px;
}}
.container {{
    max-width: 820px; margin: 0 auto; background: var(--card-bg);
    padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05);
}}
.header {{ text-align: center; border-bottom: 2px solid var(--border-color); padding-bottom: 20px; margin-bottom: 24px; }}
.header h1 {{ color: var(--primary-color); font-size: 24px; margin: 0 0 10px 0; }}
.header p {{ color: #666; font-size: 14px; margin: 0; }}
.scope {{ font-size: 13px; color: #888; margin-top: 8px; }}
.toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; margin-bottom: 22px; }}
.toolbar button {{
    padding: 8px 14px; font-size: 13px; border: 1px solid var(--border-color);
    background: #fff; border-radius: 20px; cursor: pointer; color: #444;
}}
.toolbar button:hover {{ border-color: var(--primary-color); color: var(--primary-color); }}
.toolbar button.active {{ background: var(--primary-color); color: #fff; border-color: var(--primary-color); }}
.user-info {{
    display: flex; gap: 15px; margin-bottom: 20px; background: #f8f9fa;
    padding: 15px 20px; border-radius: 8px; border: 1px solid var(--border-color);
}}
.user-info .input-group {{ flex: 1; display: flex; align-items: center; gap: 10px; }}
.user-info label {{ font-weight: bold; font-size: 14px; white-space: nowrap; }}
.user-info input {{ width: 100%; padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }}
.progress {{
    position: sticky; top: 0; z-index: 5; background: var(--card-bg);
    padding: 10px 0 14px 0; font-size: 13px; color: #666; text-align: center;
    border-bottom: 1px solid var(--border-color); margin-bottom: 10px;
}}
.progress-bar {{ height: 6px; background: #e9edf2; border-radius: 3px; margin-top: 6px; overflow: hidden; }}
.progress-bar > div {{ height: 100%; width: 0%; background: var(--primary-color); transition: width 0.2s; }}
.section-title {{
    font-size: 16px; color: var(--primary-color); border-left: 4px solid var(--primary-color);
    padding-left: 12px; margin: 38px 0 18px 0;
}}
.sec-count {{ font-size: 12px; color: #999; font-weight: normal; margin-left: 6px; }}
.question-card {{
    background: #fff; border: 1px solid var(--border-color); border-radius: 8px;
    padding: 20px; margin-bottom: 22px; transition: border-color 0.2s;
}}
.question-card.correct {{ border-color: var(--correct-color); background-color: var(--correct-bg); }}
.question-card.incorrect {{ border-color: var(--incorrect-color); background-color: var(--incorrect-bg); }}
.question-title {{ font-weight: 600; font-size: 16px; margin-bottom: 15px; }}
.options {{ list-style: none; padding: 0; margin: 0; }}
.option-item {{ margin-bottom: 10px; }}
.option-item label {{
    display: flex; align-items: flex-start; padding: 10px 15px;
    border: 1px solid var(--border-color); border-radius: 6px; cursor: pointer;
    background: #fff; transition: all 0.2s;
}}
.option-item label:hover {{ background: #f0f4f8; border-color: var(--primary-color); }}
.option-item input[type="radio"] {{
    margin-right: 12px; margin-top: 5px; width: 16px; height: 16px;
    flex-shrink: 0; accent-color: var(--primary-color);
}}
.explanation {{
    display: none; margin-top: 15px; padding: 12px 15px;
    background: rgba(255,255,255,0.85); border-radius: 6px; font-size: 14px; line-height: 1.6;
}}
.btn-submit {{
    display: block; width: 100%; padding: 15px; background-color: var(--primary-color);
    color: #fff; font-size: 16px; font-weight: bold; border: none; border-radius: 8px;
    cursor: pointer; transition: background-color 0.2s; margin-top: 30px;
}}
.btn-submit:hover {{ background-color: var(--primary-hover); }}
.notice {{
    display: none; margin-top: 12px; padding: 10px 14px; border-radius: 6px;
    background: var(--incorrect-bg); color: var(--incorrect-color); font-size: 14px; text-align: center;
}}
.result-box {{
    display: none; text-align: center; padding: 20px; background: #eef4fa;
    border-radius: 8px; margin-bottom: 25px; border: 1px solid #b8d4f0;
}}
.result-box h2 {{ margin: 0 0 10px 0; color: var(--primary-color); }}
.breakdown {{ margin-top: 12px; font-size: 14px; color: #444; line-height: 1.9; text-align: left; display: inline-block; }}
.wrong-list {{ margin-top: 14px; font-size: 13px; color: #666; }}
.wrong-list a {{ color: var(--primary-color); text-decoration: none; margin: 0 4px; }}
@media (max-width: 600px) {{
    .container {{ padding: 20px; }}
    .user-info {{ flex-direction: column; }}
}}
</style>
</head>
<body>

<div class="container">
    <div class="header">
        <h1>{TITLE} 확인 시험</h1>
        <p>경북대학교 분자미생물학연구실</p>
        <p class="scope">Tortora <i>Microbiology</i> Ch.14 질병과 역학 · Ch.15 병원성 기전 · Ch.16 선천면역 · Ch.17 적응면역 · Ch.27 환경미생물학 · Ch.28 응용·산업미생물학 &nbsp;|&nbsp; 총 <b>{TOTAL}문항</b></p>
    </div>

    <div class="toolbar">
        <button type="button" id="btnFilter" onclick="toggleFilter()">챕터별로 보기</button>
        <button type="button" onclick="clearAll()">답안 초기화</button>
    </div>

    <form id="quizForm">
        <div class="user-info">
            <div class="input-group">
                <label for="studentName">이름:</label>
                <input type="text" id="studentName" placeholder="이름을 입력하세요" required>
            </div>
            <div class="input-group">
                <label for="studentPassword">성적확인비번:</label>
                <input type="password" id="studentPassword" placeholder="비밀번호를 입력하세요" required>
            </div>
        </div>

        <div class="progress">
            <span id="progressText">0 / {TOTAL} 문항 응답</span>
            <div class="progress-bar"><div id="progressFill"></div></div>
        </div>

        <div class="result-box" id="resultBox">
            <h2 id="scoreText">점수: 0 / {TOTAL} 점</h2>
            <p id="resultMessage"></p>
            <div class="breakdown" id="breakdown"></div>
            <div class="wrong-list" id="wrongList"></div>
        </div>
{body}

        <button type="button" class="btn-submit" onclick="gradeQuiz()">제출 및 채점하기</button>
        <div class="notice" id="notice"></div>
    </form>
</div>

<script>
    const answers = {answers_js};

    const sections = {sections_js};
    const TOTAL = {TOTAL};

    function updateProgress() {{
        let n = 0;
        for (let i = 1; i <= TOTAL; i++) {{
            if (document.querySelector('input[name="q' + i + '"]:checked')) n++;
        }}
        document.getElementById('progressText').textContent = n + ' / ' + TOTAL + ' 문항 응답';
        document.getElementById('progressFill').style.width = (n / TOTAL * 100) + '%';
    }}

    document.addEventListener('change', function (e) {{
        if (e.target && e.target.type === 'radio') updateProgress();
    }});

    function clearAll() {{
        document.querySelectorAll('input[type="radio"]').forEach(function (r) {{ r.checked = false; }});
        document.querySelectorAll('.question-card').forEach(function (c) {{ c.classList.remove('correct', 'incorrect'); }});
        document.querySelectorAll('.explanation').forEach(function (x) {{ x.style.display = 'none'; }});
        document.getElementById('resultBox').style.display = 'none';
        document.getElementById('notice').style.display = 'none';
        updateProgress();
        window.scrollTo({{ top: 0, behavior: 'smooth' }});
    }}

    let filterOn = false;
    function toggleFilter() {{
        filterOn = !filterOn;
        const btn = document.getElementById('btnFilter');
        btn.classList.toggle('active', filterOn);
        btn.textContent = filterOn ? '전체 보기' : '챕터별로 보기';
        // 챕터별 보기: 첫 챕터만 남기고 접는다
        let cursor = 0;
        sections.forEach(function (s, si) {{
            const n = s[1];
            for (let k = 1; k <= n; k++) {{
                const card = document.getElementById('q' + (cursor + k) + '-card');
                card.style.display = (!filterOn || si === 0) ? '' : 'none';
            }}
            const titles = document.querySelectorAll('.section-title');
            if (titles[si]) titles[si].style.display = (!filterOn || si === 0) ? '' : 'none';
            cursor += n;
        }});
    }}

    function gradeQuiz() {{
        const studentName = document.getElementById('studentName').value.trim();
        const studentPassword = document.getElementById('studentPassword').value.trim();
        const notice = document.getElementById('notice');

        if (!studentName || !studentPassword) {{
            notice.textContent = '이름과 성적확인비번을 모두 입력해주세요.';
            notice.style.display = 'block';
            return;
        }}
        notice.style.display = 'none';

        let score = 0;
        const perQuestion = [];
        const wrong = [];

        for (let i = 1; i <= TOTAL; i++) {{
            const qKey = 'q' + i;
            const selected = document.querySelector('input[name="' + qKey + '"]:checked');
            const card = document.getElementById(qKey + '-card');
            const exp = document.getElementById(qKey + '-exp');

            card.classList.remove('correct', 'incorrect');
            const ok = !!selected && selected.value === answers[qKey];
            if (ok) {{ score++; card.classList.add('correct'); }}
            else {{ card.classList.add('incorrect'); wrong.push(i); }}
            perQuestion.push(ok);
            exp.style.display = 'block';
            card.style.display = '';
        }}
        document.querySelectorAll('.section-title').forEach(function (t) {{ t.style.display = ''; }});

        let cursor = 0;
        const lines = sections.map(function (s) {{
            const name = s[0], n = s[1];
            const slice = perQuestion.slice(cursor, cursor + n);
            cursor += n;
            const got = slice.filter(Boolean).length;
            const pct = Math.round(got / n * 100);
            return name + ' &nbsp;—&nbsp; <b>' + got + ' / ' + n + '</b> (' + pct + '%)';
        }});
        document.getElementById('breakdown').innerHTML = lines.join('<br>');

        document.getElementById('wrongList').innerHTML = wrong.length
            ? '틀린 문항: ' + wrong.map(function (i) {{ return '<a href="#q' + i + '-card">' + i + '</a>'; }}).join('')
            : '';

        const resultBox = document.getElementById('resultBox');
        const scoreText = document.getElementById('scoreText');
        const resultMessage = document.getElementById('resultMessage');

        resultBox.style.display = 'block';
        const pct = Math.round(score / TOTAL * 100);
        scoreText.textContent = studentName + ' 님의 점수: ' + score + ' / ' + TOTAL + ' 점 (' + pct + '%)';

        if (score === TOTAL) {{
            resultMessage.textContent = '축하합니다! 모든 핵심 개념을 완벽하게 이해하셨습니다.';
            resultMessage.style.color = 'var(--correct-color)';
        }} else if (pct >= 80) {{
            resultMessage.textContent = '잘 하셨습니다. 틀린 문항의 해설만 확인하면 됩니다.';
            resultMessage.style.color = 'var(--correct-color)';
        }} else {{
            resultMessage.textContent = '틀린 문제의 해설을 확인하고 핵심 개념을 다시 복습해보세요.';
            resultMessage.style.color = 'var(--incorrect-color)';
        }}

        window.scrollTo({{ top: resultBox.offsetTop - 20, behavior: 'smooth' }});
    }}

    updateProgress();
</script>

</body>
</html>
'''
io.open(OUT_HTML, 'w', encoding='utf-8').write(DOC)

# ---------- 노트의 예상문제 절 ----------
md = ["# C. 예상문제\n",
      f"총 **{TOTAL}문항**. 예시시험과 같은 4지선다이며, 정의의 경계를 사례·짝짓기로 묻는 형식으로 통일했다. "
      "가리고 풀 수 있도록 정답과 해설은 각 챕터 끝에 따로 두었다. "
      f"같은 문항을 브라우저에서 채점까지 하려면 `{OUT_HTML}` 을 연다.\n"]

idx = 0
for title, qs in SECTIONS:
    md.append(f"\n## {title} ({len(qs)}문항)\n")
    start = idx + 1
    for q, opts, ans, exp in qs:
        idx += 1
        md.append(f"**{idx}.** {q}")
        for i, o in enumerate(opts):
            md.append(f"{CIRCLE[i]} {o}")
        md.append("")
    md.append(f"### 정답과 해설 — {title}\n")
    md.append("| 번호 | 정답 | 해설 |")
    md.append("|---|---|---|")
    j = start
    for q, opts, ans, exp in qs:
        md.append(f"| {j} | {CIRCLE[ans-1]} | {to_md_cell(exp)} |")
        j += 1
    md.append("")

md_block = "\n".join(md) + "\n---\n\n"

if NOTE:
    txt = io.open(NOTE, encoding='utf-8').read()
    i0 = txt.index("# C. 예상문제")
    i1 = txt.index("# D. 마무리 체크")
    txt = txt[:i0] + md_block + txt[i1:]
    io.open(NOTE, 'w', encoding='utf-8').write(txt)

print(f"총 {TOTAL}문항")
for t, qs in SECTIONS:
    print(f"  {t}: {len(qs)}")
print("->", OUT_HTML)
if NOTE:
    print("->", NOTE)
