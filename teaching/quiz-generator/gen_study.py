# -*- coding: utf-8 -*-
"""문제은행 -> 즉답 학습 HTML.

gen.py 가 만드는 '확인시험'(다 풀고 제출 -> 채점)과 달리, 이 스크립트는
보기를 고르는 순간 정오·해설이 바로 뜨는 학습용 페이지를 만든다.
문항 번호와 보기 순서는 gen.py 와 같은 회전 규칙을 쓰므로 노트의 번호와 일치한다.
"""
import io, os, re, json, html as H
from bank import TITLE, SECTIONS   # 문제은행: bank.py (형식은 bank.py 예시 참고)

CIRCLE = ["①", "②", "③", "④"]
OUT_HTML = os.environ.get('QUIZ_STUDY_OUT', f'{TITLE}_즉답학습.html')


def to_html(s):
    s = H.escape(s, quote=False)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<i>\1</i>', s)
    return s.replace('\n', '<br>')


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

# ---------- 정답 위치 균등화 (gen.py 와 동일한 회전) ----------
_CIRC_IDX = {c: i for i, c in enumerate(CIRCLE)}


def _balance(sections):
    out, t = [], 0
    for title, qs in sections:
        nq = []
        for q, opts, ans, exp in qs:
            a = ans - 1
            k = (t - a) % 4
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

# ---------- 본문 ----------
cards, answers, meta, idx = [], {}, [], 0
for si, (title, qs) in enumerate(SECTIONS):
    short = title.split(' · ')[0]
    cards.append(
        '\n        <h2 class="section-title" data-sec="%d">%s'
        '<span class="sec-count">%d문항</span>'
        '<span class="sec-score" id="secscore%d"></span></h2>'
        % (si, H.escape(title), len(qs), si))
    for q, opts, ans, exp in qs:
        idx += 1
        answers['q%d' % idx] = ans
        meta.append(si)
        ol = "\n".join(
            '                <li><button type="button" class="opt" '
            'data-q="%d" data-v="%d">'
            '<span class="mark">%s</span>'
            '<span class="otext">%s</span>'
            '<span class="verdict"></span></button></li>'
            % (idx, i + 1, CIRCLE[i], to_html(o))
            for i, o in enumerate(opts))
        cards.append('''
        <div class="card" id="q%d-card" data-sec="%d" data-q="%d">
            <div class="qhead">
                <span class="qnum">%d</span>
                <span class="qchap">%s</span>
                <button type="button" class="redo" data-q="%d" hidden>다시 풀기</button>
            </div>
            <div class="qtext">%s</div>
            <ul class="opts">
%s
            </ul>
            <div class="exp" id="q%d-exp" hidden>
                <div class="exp-head"><span class="exp-ans">정답 %s</span><span class="exp-you"></span></div>
                <div class="exp-body">%s</div>
            </div>
        </div>''' % (idx, si, idx, idx, H.escape(short), idx,
                     to_html(q), ol, idx, CIRCLE[ans - 1], to_html(exp)))

body = "\n".join(cards)
tabs = "\n".join(
    '        <button type="button" class="tab" data-sec="%d">%s</button>'
    % (si, H.escape(t.split(' · ')[0] + ' ' + t.split(' · ')[1]))
    for si, (t, _) in enumerate(SECTIONS))

DOC = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__ 즉답 학습</title>
<style>
:root{
  --ink:#1f2933; --ink-soft:#5b6b7b; --ink-faint:#8b97a3;
  --bg:#f2f5f8; --card:#ffffff; --line:#dfe5ec;
  --brand:#2b5278; --brand-soft:#e8eef6;
  --ok:#1b7f47; --ok-bg:#e7f5ec; --ok-line:#8fd3ae;
  --no:#c0392b; --no-bg:#fdeceb; --no-line:#f0a9a2;
}
*{box-sizing:border-box}
body{
  margin:0; padding:24px 16px 80px;
  font-family:'Pretendard',-apple-system,BlinkMacSystemFont,system-ui,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
  background:var(--bg); color:var(--ink); line-height:1.65; font-size:15px;
}
.wrap{max-width:860px; margin:0 auto}
header{text-align:center; margin-bottom:20px}
header h1{font-size:23px; color:var(--brand); margin:0 0 6px}
header .sub{font-size:13px; color:var(--ink-soft); margin:0}
header .scope{font-size:12.5px; color:var(--ink-faint); margin:8px 0 0; line-height:1.7}
.howto{
  background:var(--brand-soft); border:1px solid #cadaeb; border-radius:10px;
  padding:12px 16px; font-size:13.5px; color:#33506e; margin:16px 0 18px;
}
.bar{
  position:sticky; top:0; z-index:20; background:rgba(242,245,248,.94);
  backdrop-filter:blur(6px); border-bottom:1px solid var(--line);
  padding:10px 0 8px; margin-bottom:14px;
}
.stats{display:flex; gap:18px; justify-content:center; flex-wrap:wrap; font-size:13px; color:var(--ink-soft)}
.stats b{color:var(--ink); font-size:15px}
.stats .hit b{color:var(--ok)} .stats .miss b{color:var(--no)}
.track{height:6px; background:#e2e8ef; border-radius:3px; margin-top:8px; overflow:hidden}
.track>div{height:100%; width:0; background:var(--brand); transition:width .25s}
.tabs{display:flex; gap:6px; flex-wrap:wrap; justify-content:center; margin:14px 0 6px}
.tab, .ctl{
  font:inherit; font-size:12.5px; padding:6px 12px; border:1px solid var(--line);
  background:#fff; color:var(--ink-soft); border-radius:18px; cursor:pointer;
}
.tab:hover,.ctl:hover{border-color:var(--brand); color:var(--brand)}
.tab.on{background:var(--brand); border-color:var(--brand); color:#fff}
.ctl.on{background:var(--no); border-color:var(--no); color:#fff}
.ctls{display:flex; gap:6px; justify-content:center; flex-wrap:wrap; margin-bottom:22px}
.section-title{
  font-size:15px; color:var(--brand); border-left:4px solid var(--brand);
  padding-left:11px; margin:34px 0 16px; display:flex; align-items:center; gap:8px; flex-wrap:wrap;
}
.sec-count{font-size:12px; color:var(--ink-faint); font-weight:400}
.sec-score{font-size:12px; color:var(--ink-soft); font-weight:400; margin-left:auto}
.card{
  background:var(--card); border:1px solid var(--line); border-left:4px solid var(--line);
  border-radius:10px; padding:18px 20px; margin-bottom:16px; scroll-margin-top:110px;
}
.card.hit{border-left-color:var(--ok)}
.card.miss{border-left-color:var(--no)}
.qhead{display:flex; align-items:center; gap:9px; margin-bottom:9px}
.qnum{
  display:inline-flex; align-items:center; justify-content:center; min-width:26px; height:22px;
  background:var(--brand-soft); color:var(--brand); border-radius:11px; font-size:12px; font-weight:700; padding:0 7px;
}
.qchap{font-size:11.5px; color:var(--ink-faint)}
.redo{
  margin-left:auto; font:inherit; font-size:11.5px; color:var(--ink-soft);
  background:#fff; border:1px solid var(--line); border-radius:14px; padding:3px 10px; cursor:pointer;
}
.redo:hover{border-color:var(--brand); color:var(--brand)}
.qtext{font-weight:600; font-size:15.5px; margin-bottom:13px}
.opts{list-style:none; padding:0; margin:0}
.opts li{margin-bottom:8px}
.opt{
  display:flex; align-items:flex-start; gap:10px; width:100%; text-align:left;
  font:inherit; font-size:14.5px; color:var(--ink); background:#fff;
  border:1px solid var(--line); border-radius:8px; padding:11px 14px; cursor:pointer;
  transition:background .15s, border-color .15s;
}
.opt:hover:not([disabled]){background:#f4f8fc; border-color:var(--brand)}
.opt[disabled]{cursor:default}
.mark{color:var(--ink-faint); font-weight:700; flex-shrink:0}
.otext{flex:1}
.verdict{flex-shrink:0; font-size:12px; font-weight:700; align-self:center}
.opt.correct{background:var(--ok-bg); border-color:var(--ok-line)}
.opt.correct .mark, .opt.correct .verdict{color:var(--ok)}
.opt.wrong{background:var(--no-bg); border-color:var(--no-line)}
.opt.wrong .mark, .opt.wrong .verdict{color:var(--no)}
.opt.dim{opacity:.5}
.exp{margin-top:14px; border-top:1px dashed var(--line); padding-top:12px; font-size:14px}
.exp-head{display:flex; gap:10px; align-items:center; margin-bottom:7px; flex-wrap:wrap}
.exp-ans{
  font-weight:700; font-size:12.5px; color:var(--ok);
  background:var(--ok-bg); border:1px solid var(--ok-line); border-radius:12px; padding:2px 10px;
}
.exp-you{font-size:12.5px; font-weight:700; border-radius:12px; padding:2px 10px}
.exp-you.hit{color:var(--ok); background:var(--ok-bg); border:1px solid var(--ok-line)}
.exp-you.miss{color:var(--no); background:var(--no-bg); border:1px solid var(--no-line)}
.exp-body{color:#3d4a57; line-height:1.75}
.empty{
  display:none; text-align:center; color:var(--ink-faint); font-size:14px;
  padding:40px 20px; border:1px dashed var(--line); border-radius:10px; background:#fff;
}
footer{margin-top:34px; font-size:12px; color:var(--ink-faint); text-align:center}
@media (max-width:620px){
  body{padding:16px 10px 60px; font-size:14.5px}
  .card{padding:15px 14px}
  .stats{gap:12px}
}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>__TITLE__ 즉답 학습</h1>
  <p class="sub">경북대학교 분자미생물학연구실</p>
  <p class="scope">Tortora <i>Microbiology</i> 14장 질병과 역학 · 15장 병원성 기전 · 16장 선천면역 · 17장 적응면역 · 27장 환경미생물학 · 28장 응용·산업미생물학 &nbsp;|&nbsp; 총 <b>__TOTAL__문항</b></p>
</header>

<div class="howto">
  보기를 고르면 그 자리에서 정답과 해설이 열린다. 고른 뒤에도 「다시 풀기」로 같은 문항을 되돌릴 수 있고, 푼 기록은 브라우저에 남아 다음에 열어도 이어진다.
</div>

<div class="bar">
  <div class="stats">
    <span>푼 문항 <b id="sDone">0</b> / __TOTAL__</span>
    <span class="hit">정답 <b id="sHit">0</b></span>
    <span class="miss">오답 <b id="sMiss">0</b></span>
    <span>정답률 <b id="sPct">—</b></span>
  </div>
  <div class="track"><div id="fill"></div></div>
</div>

<div class="tabs">
  <button type="button" class="tab on" data-sec="all">전체</button>
__TABS__
</div>

<div class="ctls">
  <button type="button" class="ctl" id="btnWrong">틀린 문항만</button>
  <button type="button" class="ctl" id="btnUnsolved">안 푼 문항만</button>
  <button type="button" class="ctl" id="btnReset">기록 지우기</button>
</div>

<div id="quiz">
__BODY__
</div>

<div class="empty" id="empty">조건에 맞는 문항이 없다.</div>

<footer>인터넷 없이 열어도 동일하게 동작한다.</footer>

</div>

<script>
(function(){
  var ANS = __ANSWERS__;
  var SEC = __META__;
  var SECN = __SECN__;
  var TOTAL = __TOTAL__;
  var KEY = 'micro-study-v1';
  var CIRCLE = ['①','②','③','④'];

  var picked = {};
  try { picked = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch(e) { picked = {}; }

  var secFilter = 'all';
  var mode = 'all';

  function save(){
    try { localStorage.setItem(KEY, JSON.stringify(picked)); } catch(e) {}
  }

  function paint(n){
    var card = document.getElementById('q'+n+'-card');
    var exp  = document.getElementById('q'+n+'-exp');
    var opts = card.querySelectorAll('.opt');
    var redo = card.querySelector('.redo');
    var v = picked['q'+n];

    card.classList.remove('hit','miss');
    opts.forEach(function(b){
      b.classList.remove('correct','wrong','dim');
      b.disabled = false;
      b.querySelector('.verdict').textContent = '';
    });

    if (!v) { exp.hidden = true; redo.hidden = true; return; }

    var a = ANS['q'+n];
    var ok = (v === a);
    card.classList.add(ok ? 'hit' : 'miss');
    opts.forEach(function(b){
      var bv = parseInt(b.dataset.v, 10);
      b.disabled = true;
      if (bv === a) { b.classList.add('correct'); b.querySelector('.verdict').textContent = '정답'; }
      else if (bv === v) { b.classList.add('wrong'); b.querySelector('.verdict').textContent = '내가 고름'; }
      else { b.classList.add('dim'); }
    });
    var you = exp.querySelector('.exp-you');
    you.className = 'exp-you ' + (ok ? 'hit' : 'miss');
    you.textContent = ok ? '맞음' : ('고른 답 ' + CIRCLE[v-1]);
    exp.hidden = false;
    redo.hidden = false;
  }

  function stats(){
    var done = 0, hit = 0;
    var per = SECN.map(function(){ return [0,0]; });
    for (var i=1; i<=TOTAL; i++){
      var v = picked['q'+i];
      if (!v) continue;
      var s = SEC[i-1];
      done++; per[s][1]++;
      if (v === ANS['q'+i]) { hit++; per[s][0]++; }
    }
    document.getElementById('sDone').textContent = done;
    document.getElementById('sHit').textContent = hit;
    document.getElementById('sMiss').textContent = done - hit;
    document.getElementById('sPct').textContent = done ? Math.round(hit/done*100) + '%' : '—';
    document.getElementById('fill').style.width = (done/TOTAL*100) + '%';
    per.forEach(function(p, si){
      var el = document.getElementById('secscore'+si);
      if (el) el.textContent = p[1] ? (p[0] + ' / ' + p[1] + ' 정답') : '';
    });
  }

  function applyFilter(){
    var shown = 0;
    for (var i=1; i<=TOTAL; i++){
      var card = document.getElementById('q'+i+'-card');
      var v = picked['q'+i];
      var vis = (secFilter === 'all' || SEC[i-1] === secFilter);
      if (vis && mode === 'wrong')    vis = (v && v !== ANS['q'+i]);
      if (vis && mode === 'unsolved') vis = !v;
      card.style.display = vis ? '' : 'none';
      if (vis) shown++;
    }
    document.querySelectorAll('.section-title').forEach(function(t){
      var si = parseInt(t.dataset.sec, 10);
      var any = false;
      for (var i=1; i<=TOTAL; i++){
        if (SEC[i-1] === si && document.getElementById('q'+i+'-card').style.display !== 'none') { any = true; break; }
      }
      t.style.display = any ? '' : 'none';
    });
    document.getElementById('empty').style.display = shown ? 'none' : 'block';
  }

  document.getElementById('quiz').addEventListener('click', function(e){
    var opt = e.target.closest('.opt');
    if (opt && !opt.disabled) {
      var n = parseInt(opt.dataset.q, 10);
      picked['q'+n] = parseInt(opt.dataset.v, 10);
      save(); paint(n); stats();
      return;
    }
    var redo = e.target.closest('.redo');
    if (redo) {
      var m = parseInt(redo.dataset.q, 10);
      delete picked['q'+m];
      save(); paint(m); stats();
      if (mode !== 'all') applyFilter();
    }
  });

  document.querySelectorAll('.tab').forEach(function(t){
    t.addEventListener('click', function(){
      document.querySelectorAll('.tab').forEach(function(x){ x.classList.remove('on'); });
      t.classList.add('on');
      secFilter = (t.dataset.sec === 'all') ? 'all' : parseInt(t.dataset.sec, 10);
      applyFilter();
      window.scrollTo({top:0, behavior:'smooth'});
    });
  });

  function toggleMode(name, btn){
    mode = (mode === name) ? 'all' : name;
    document.getElementById('btnWrong').classList.toggle('on', mode === 'wrong');
    document.getElementById('btnUnsolved').classList.toggle('on', mode === 'unsolved');
    applyFilter();
    window.scrollTo({top:0, behavior:'smooth'});
  }
  document.getElementById('btnWrong').addEventListener('click', function(){ toggleMode('wrong'); });
  document.getElementById('btnUnsolved').addEventListener('click', function(){ toggleMode('unsolved'); });

  document.getElementById('btnReset').addEventListener('click', function(){
    picked = {}; save();
    for (var i=1; i<=TOTAL; i++) paint(i);
    stats(); applyFilter();
    window.scrollTo({top:0, behavior:'smooth'});
  });

  for (var i=1; i<=TOTAL; i++) paint(i);
  stats(); applyFilter();
})();
</script>
</body>
</html>
'''

DOC = (DOC.replace('__TITLE__', H.escape(TITLE)).replace('__TOTAL__', str(TOTAL))
          .replace('__TABS__', tabs)
          .replace('__BODY__', body)
          .replace('__ANSWERS__', json.dumps(answers, ensure_ascii=False))
          .replace('__META__', json.dumps(meta))
          .replace('__SECN__', json.dumps([len(qs) for _, qs in SECTIONS])))

io.open(OUT_HTML, 'w', encoding='utf-8').write(DOC)
print('총 %d문항' % TOTAL)
for t, qs in SECTIONS:
    print('  %s: %d' % (t, len(qs)))
print('->', OUT_HTML)
