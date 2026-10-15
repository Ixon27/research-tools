#!/usr/bin/env python3
"""이번 주 논문 → NotebookLM 연동.

weekly_papers.py 가 디스코드로 보낸 12편을 받아
  1) MM/paper-digest-pdf-drop/ 의 PDF 를 논문에 매칭 (파일명 무관, PDF 안의 DOI·제목으로)
  2) NotebookLM 주차 노트북에 업로드
  3) 논문별 정리본 생성 (주간 종합 브리핑은 만들지 않는다)
  4) 논문 1편당 한국어 팟캐스트 1개(deep-dive, 10~15분) 생성 → 64kbps 로 줄여 MM/ 에 보관
  5) 04_References/Weekly-papers/ 에 주차 노트 작성
  6) 디스코드에는 완료 한 줄만 (오디오 파일은 볼트에만 둔다)

weekly_papers.py 와 분리해 둔다 — NotebookLM 쪽이 깨져도 논문 발송은 살아 있어야 한다.
"""

import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import weekly_papers as W  # noqa: E402  (log·epmc_search·normalize·_discord_post 재사용)

VAULT = os.path.abspath(os.path.join(BASE, "..", ".."))
MM = os.path.expanduser(os.environ.get("PAPER_DIGEST_MEDIA", "~/Desktop/MM"))  # PDF 드롭·팟캐스트 보관 폴더의 상위
DROP = os.path.join(MM, "paper-digest-pdf-drop")
AUDIO_ROOT = os.path.join(MM, "paper-digest-audio")
NOTE_DIR = os.path.join(VAULT, "04_References", "Weekly-papers")
NLM = os.path.expanduser("~/.local/bin/notebooklm")

# NotebookLM 오디오 한도는 '최근 24시간 안에 6편' 이다 (2026-09-07 확정 — 고정 리셋 시각이 아니다).
# 12편을 몰아서 요청하면 뒤쪽이 통째로 날아가므로 월 6편 · 화 6편으로 나눈다.
PODCAST_DAILY_CAP = 6

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def week_tag(today=None):
    d = today or dt.date.today()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def nlm(*args, timeout=600, parse_json=False):
    """notebooklm CLI 호출. (성공여부, 표준출력 또는 파싱된 JSON) 을 돌려준다."""
    cmd = [NLM] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()[:300]
    out = r.stdout.strip()
    if parse_json:
        try:
            return True, json.loads(out)
        except Exception:  # noqa: BLE001
            return False, out[:300]
    return True, out


# ── 1) 이번 주 논문 + PDF 매칭 ────────────────────────────────────────

class PaperLookupError(RuntimeError):
    """발송분 논문 정보를 하나라도 못 얻으면 던진다 — 빠진 채 진행하지 않는다."""


def load_papers():
    """이번 주 발송분을 디스코드와 같은 순서·분류로 불러온다.

    last_digest.json 이 카테고리 구성과 논문 정보(`papers`)를 갖고 있다. 정보가 있으면
    Europe PMC 를 조회하지 않는다. 없는 논문만 조회하되, 끝내 실패하면 그 논문을 빼고
    가지 않고 PaperLookupError 로 멈춘다 — 2026-09-21 W39 에서 503 연속으로 1편이
    조용히 빠진 채 노트북이 만들어졌다. history.json 만 있으면 분류 없이 진행한다.
    """
    mpath = os.path.join(BASE, "last_digest.json")
    order = []
    known = {}
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            man = json.load(f)
        known = man.get("papers", {})
        for c in man.get("categories", []):
            for i in c.get("cited", []):
                order.append((i, c["name"], "cited"))
            for i in c.get("new", []):
                order.append((i, c["name"], "new"))
    if not order:
        with open(os.path.join(BASE, "history.json"), encoding="utf-8") as f:
            hist = json.load(f)
        today = dt.date.today().isoformat()
        ids = [k for k, v in hist.items() if v == today] or list(hist)
        order = [(i, "", "") for i in sorted(ids)]
        W.log("last_digest.json 없음 — 분류 없이 진행")

    papers = []
    failed = []
    for i, cat, slot in order:
        if i in known:
            p = dict(known[i])
        else:
            p = _lookup_epmc(i)
            if p is None:
                failed.append(i)
                continue
        p["category"], p["slot"] = cat, slot
        papers.append(p)
    if failed:
        raise PaperLookupError(
            f"논문 {len(failed)}편 정보를 못 얻었습니다 (Europe PMC 응답 없음): {', '.join(failed)}"
        )
    return papers


def _lookup_epmc(pmid, rounds=3, wait=30):
    """Europe PMC 에서 논문 1편. epmc_search 자체 재시도(3회·3초) 위에 30초 간격으로
    3라운드 더 — 503 이 몇 분 이어지는 날을 넘기기 위해."""
    for n in range(rounds):
        r = W.epmc_search(f"EXT_ID:{pmid}", "CITED desc", 1)
        if r:
            return W.normalize(r[0])
        if n < rounds - 1:
            W.log(f"  EPMC 응답 없음 ({pmid}) — {wait}초 뒤 재시도 {n + 2}/{rounds}")
            time.sleep(wait)
    return None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def match_pdfs(papers):
    """drop 폴더의 PDF 를 논문에 붙인다. 파일명은 보지 않는다."""
    by_doi = {p["doi"].lower(): p for p in papers if p.get("doi")}
    for p in papers:
        p["pdf"] = None
    unmatched = []
    for f in sorted(glob.glob(os.path.join(DROP, "*.pdf"))):
        try:
            txt = subprocess.run(["pdftotext", "-f", "1", "-l", "2", f, "-"],
                                 capture_output=True, text=True, timeout=120).stdout
        except Exception:  # noqa: BLE001
            txt = ""
        hit = None
        for d in DOI_RE.findall(txt):
            d = d.rstrip(".,);").lower()
            for k, p in by_doi.items():
                if k == d or d.startswith(k) or k.startswith(d):
                    hit = p
                    break
            if hit:
                break
        if not hit:
            head = _norm(txt[:3000])
            for p in papers:
                key = _norm(p["title"])[:60]
                if key and key in head:
                    hit = p
                    break
        if hit and not hit["pdf"]:
            hit["pdf"] = f
        else:
            unmatched.append(os.path.basename(f))
    missing = [p for p in papers if not p["pdf"]]
    return missing, unmatched


def notify(webhook, content):
    if webhook:
        W._discord_post(webhook, {"content": content[:1900]})


def report_pdf_status(papers, missing, unmatched, webhook, final=False):
    if not missing and not unmatched:
        W.log(f"PDF 매칭 {len(papers)}/{len(papers)}편 — 이상 없음")
        return
    lines = []
    if missing:
        head = "PDF 없이 진행합니다" if final else "12:30 까지 넣으면 반영됩니다"
        lines.append(f"⚠️ **PDF {len(missing)}편 빠졌어요** ({head})")
        lines += [f"· {p['title'][:80]}" for p in missing]
    if unmatched:
        lines.append(f"매칭 안 된 파일 {len(unmatched)}개: " + ", ".join(unmatched[:5]))
    msg = "\n".join(lines)
    W.log(msg.replace("**", ""))
    notify(webhook, msg)


# ── 2) NotebookLM 노트북 구성 ────────────────────────────────────────

MIN_CHARS = 1000  # 이보다 적게 들어갔으면 소스 추가에 실패한 것으로 본다


def build_notebook(papers, tag):
    ok, data = nlm("create", f"이번 주 논문 {tag}", "--json", parse_json=True)
    if not ok:
        return None, f"노트북 생성 실패: {data}"
    nb = (data.get("notebook") or data).get("id")
    W.log(f"노트북 생성: {nb}")

    for i, p in enumerate(papers):
        src = p["pdf"] or p["link"]
        typ = "file" if p["pdf"] else "url"
        ok, out = nlm("source", "add", "-n", nb, "--type", typ,
                      "--timeout", "300", "--json", src, timeout=900, parse_json=True)
        if not ok:  # rate limit 등 — 한 번 쉬고 재시도
            W.log(f"  소스 추가 재시도: {p['title'][:40]}")
            import time
            time.sleep(20)
            ok, out = nlm("source", "add", "-n", nb, "--type", typ,
                          "--timeout", "300", "--json", src, timeout=900, parse_json=True)
        if not ok:
            p["source_id"] = None
            W.log(f"  ✗ {p['title'][:50]} — {out}")
            continue
        sid = (out.get("source") or out).get("id")
        p["source_id"] = sid
        # 처리가 끝나기 전에는 본문이 0자로 잡히고 rename 도 조용히 무시된다.
        # 반드시 ready 를 기다린 뒤에 이름을 바꾼다.
        nlm("source", "wait", "-n", nb, sid, timeout=900)
        ok_r, out_r = nlm("source", "rename", "-n", nb, sid, p["title"][:200], timeout=120)
        if not ok_r:
            W.log(f"  이름 변경 실패({p['title'][:35]}): {out_r}")
        W.log(f"  ✓ {p['title'][:50]}")
        import time
        time.sleep(3)  # 연속 추가 시 rate limit 회피
    return nb, None


def attach_notebook(papers, nb):
    """이미 만들어 둔 노트북의 소스를 제목으로 논문에 다시 붙인다 (중단 후 재개용)."""
    ok, data = nlm("source", "list", "-n", nb, "--json", timeout=300, parse_json=True)
    items = (data.get("sources") if isinstance(data, dict) else data) or []
    by_title = {(s.get("title") or "").strip(): s.get("id") for s in items}
    for p in papers:
        p["source_id"] = by_title.get(p["title"][:200].strip())
        if not p["source_id"] and p.get("pdf"):  # 아직 파일명인 상태일 수 있다
            p["source_id"] = by_title.get(os.path.basename(p["pdf"]))
        if not p["source_id"]:  # 제목이 잘렸을 수 있으니 앞부분으로 다시 찾는다
            key = p["title"][:40]
            for t, sid in by_title.items():
                if t.startswith(key):
                    p["source_id"] = sid
                    break
        if not p["source_id"]:
            W.log(f"  소스 못 찾음: {p['title'][:45]}")
            continue
        cur = next((t for t, sid in by_title.items() if sid == p["source_id"]), "")
        if cur != p["title"][:200].strip():
            nlm("source", "rename", "-n", nb, p["source_id"], p["title"][:200], timeout=120)
    return nb


def verify_sources(nb, papers):
    """실제로 본문이 들어갔는지 글자 수로 확인한다 (fulltext 는 -o 로 받아야 안 잘린다)."""
    import tempfile
    for p in papers:
        p["chars"] = 0
        if not p.get("source_id"):
            continue
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tmp = tf.name
        ok, _ = nlm("source", "fulltext", "-n", nb, p["source_id"],
                    "-o", tmp, "--force", timeout=300)
        if ok and os.path.exists(tmp):
            p["chars"] = os.path.getsize(tmp)
            os.unlink(tmp)
        p["thin"] = p["chars"] < MIN_CHARS
        if p["thin"]:
            W.log(f"  ⚠️ 본문 부족({p['chars']}자): {p['title'][:45]}")
    return papers


# ── 3) 정리본 ────────────────────────────────────────────────────────

def load_context():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        return json.load(f).get("researcher_context", "")


def ask(nb, prompt, timeout=900, fresh=False, source=None):
    """노트북에 질문한다.

    fresh=True 면 대화를 새로 시작한다. 기본값(이어쓰기)으로 논문 12편 × 3콜을
    돌리면 대화가 계속 쌓여 응답이 268MB 를 넘고 RPC 가 죽는다.
    source 를 주면 그 소스만 보고 답하므로 다른 논문이 섞이지 않는다.
    """
    args = ["ask", "-n", nb]
    if fresh:
        args += ["--new", "--yes"]
    if source:
        args += ["-s", source]
    ok, out = nlm(*args, prompt, timeout=timeout)
    if not ok:
        W.log(f"  질의 실패: {out}")
        return ""
    # CLI 가 붙이는 안내 줄(대화 재개/시작, "Answer:" 머리표)을 떼어낸다
    out = re.sub(r"^(Continuing|Resumed|Starting) conversation.*$", "", out, flags=re.M)
    out = re.sub(r"^Answer:\s*$", "", out, flags=re.M)
    out = re.sub(r"\n(Resumed|Continuing) conversation:.*$", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    # 모델이 앞에 붙이는 인사말·메타설명을 잘라낸다 (본문은 첫 #### 부터)
    m = re.search(r"^####", out, flags=re.M)
    if m:
        out = out[m.start():]
    # 끝에 붙는 "…해 드릴까요?" 식 제안 문단을 잘라낸다 (이모지로 시작하는 꼬리말)
    tail = re.search(r"\n+(?:---\s*\n+)?[\U0001F300-\U0001FAFF\u2600-\u27BF][^\n]*"
                     r"(?:할까요|드릴까요|보시겠|원하시면|정리해 드)[\s\S]*$", out)
    if tail:
        out = out[:tail.start()]
    return out.rstrip().rstrip("-").rstrip()


PROMPT_FILE = os.path.join(BASE, "prompts", "paper-understanding.md")
# NotebookLM 이 받아주는 질문 길이. 실측 2,700 통과 / 3,500 거절 (2026-08-26)
PROMPT_LIMIT = 2700
# 제목은 이 길이에서 자른다 (가장 긴 제목이 상한을 넘기지 않도록)
TITLE_MAX = 70

# 옛 프롬프트. prompts/paper-understanding.md 가 없을 때만 쓴다.
FALLBACK_PROMPT = """'{title}' 이 논문 하나만 한국어로 정리해줘. {thin}

#### 무엇을 왜 했나 / #### 방법 / #### 결과 / #### 한계 / #### 내 연구에 쓸 지점 / #### 용어
불릿 2~4개씩, 문장 전체를 굵게 칠하지 말고, 영어 학술 용어는 음차하지 말 것."""


def load_prompt_parts():
    """정리 요청서를 읽어 (공통, [콜1, 콜2, 콜3]) 로 나눈다.

    프롬프트를 코드가 아닌 파일에 두는 이유: 이 파일 하나만 고치면
    앞으로 모든 논문에 반영되게 하기 위해서다.
    """
    if not os.path.exists(PROMPT_FILE):
        W.log("prompts/paper-understanding.md 없음 — 옛 프롬프트 사용")
        return None, None
    with open(PROMPT_FILE, encoding="utf-8") as f:
        body = f.read()
    body = re.sub(r"<!--[\s\S]*?-->", "", body).strip()
    chunks = re.split(r"^##\s*===\s*(\w+[^=]*?)\s*===\s*$", body, flags=re.M)
    parts = {}
    for i in range(1, len(chunks) - 1, 2):
        parts[chunks[i].strip().upper()] = chunks[i + 1].strip()
    common = parts.pop("COMMON", "")
    calls = [parts[k] for k in sorted(parts) if k.startswith("CALL")]
    if not calls:
        return None, None
    return common, calls


# NotebookLM 이 문장마다 붙이는 출처 번호. `[1]` `[3, 4]` `[12-14]` 형태.
# 옵시디언 노트에는 참고문헌 목록이 없어 숫자만 남으므로 통째로 지운다.
CITE_RE = re.compile(r"[ \t]*\[\d+(?:\s*[,;]\s*\d+|\s*[-–—]\s*\d+)*\]")

# 새 블록이 시작되는 줄 (앞줄에 이어붙이면 안 되는 줄)
# 마지막 `<[a-zA-Z/!]` 는 HTML 태그만 잡는다 — 그냥 `<` 로 두면
# `p < 0.001` 이 접혔을 때 뒷줄을 새 블록으로 오인해 안 이어붙인다.
BLOCK_RE = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|---|\*\*\*|===|<[a-zA-Z/!])")

# `)` 뒤에 조사가 한 칸 떨어져 붙은 경우. 모델이 굵게 규칙을 조사 전반에 잘못 적용한다.
JOSA_RE = re.compile(
    r"\)\s+(의|을|를|은|는|이|가|와|과|로|으로|도|만|에|에서|에게|이나|처럼|보다|부터|까지)"
    r"(도|는|만|의|나)?(?=[\s,.:;)\]]|$)")


def _width(line):
    """터미널 표시 폭. 한글·한자·가나는 두 칸을 차지한다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line)


# CLI 는 80칸에서 줄을 접는다. 표시 폭이 이보다 넓은 줄만 "접힌 줄"로 본다.
WRAP_W = 60


def unwrap(md):
    """CLI 가 80칸에서 접어 놓은 줄을 문단 단위로 다시 편다.

    문장 중간에서 줄이 바뀌면 굵게(`**`)가 두 줄에 걸쳐 열리고 닫혀서
    옵시디언이 `**` 를 글자 그대로 뱉는다 — "중간에 보이는 * 표시"의 정체다.
    소제목도 접히면 `####` 뒤쪽이 본문으로 떨어져 나간다.

    앞줄이 폭 60칸을 넘거나 굵게(`**`)·코드(`` ` ``)가 열린 채 끝났을 때만 잇는다.
    그래야 원래 짧게 끊어 쓴 줄을 잘못 붙이지 않는다.
    """
    out, fence = [], False
    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
            out.append(line)
            continue
        if fence or not line.strip():
            out.append(line)
            continue
        prev = out[-1] if out else ""
        # 앞줄이 폭을 채웠거나, 굵게·코드가 열린 채 끝났으면 접힌 줄이다
        hung = prev.count("**") % 2 == 1 or prev.count("`") % 2 == 1
        if (out and prev.strip() and (_width(prev) >= WRAP_W or hung)
                and not BLOCK_RE.match(line)
                and not out[-1].lstrip().startswith("```")):
            out[-1] = out[-1].rstrip() + " " + line.strip()
            continue
        out.append(line)
    return "\n".join(out)


def tidy(md):
    """볼트 렌더링 규칙에 맞게 다듬는다 (모델이 규칙을 어겨도 여기서 바로잡는다).

    ① 접힌 줄 펴기  ② 출처 번호 `[1, 2]` 제거  ③ 단독 줄 `**굵게**` → `###### 소제목`
    ④ 굵게 닫은 뒤 한글 조사 → 한 칸 띄움  ⑤ `**용어** (뜻)` → `**용어**(뜻)`
    ②③⑤ 는 옵시디언이 `**` 를 글자 그대로 출력해 버리거나 숫자만 남는 케이스다.
    """
    if not md:
        return md
    md = unwrap(md)
    md = CITE_RE.sub("", md)
    out = []
    for line in md.split("\n"):
        st = line.strip()
        m = re.fullmatch(r"\*\*([^*]+)\*\*[:：]?", st)
        if m:
            out.append("###### " + m.group(1).strip())
            continue
        out.append(line)
    md = "\n".join(out)
    md = re.sub(r"\*\*\s+\(", "**(", md)          # `**SCFAs** (단쇄…` → `**SCFAs**(단쇄…`
    md = JOSA_RE.sub(r")\1\2", md)
    # 닫는 ** 뒤에 조사가 붙은 경우만 띄운다.
    # 여는 ** 는 앞이 공백/줄머리라 (?<=\S) 에 걸리지 않는다.
    md = re.sub(r"(?<=\S)\*\*(?=[가-힣])", "** ", md)
    md = re.sub(r"[ \t]+([,.:;])", r"\1", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def make_summaries(nb, papers):
    """논문마다 정리본을 만든다.

    주간 종합 브리핑은 만들지 않는다 — 노트 첫머리를 길게 잡아먹기만 하고
    각 논문으로 바로 내려가는 데 방해가 됐다 (2026-08-26 사용자 확정).
    """
    ctx = load_context()
    common, calls = load_prompt_parts()
    for p in papers:
        if not p.get("source_id"):
            p["summary"] = ""
            continue
        thin = ("이 논문은 초록만 확보돼 있다. 초록 범위에서만 쓰고, "
                "전문이 없어 확인 못 한 항목은 `(전문 미확보)` 라고 적어라.") \
            if p.get("thin") else "전문이 있으니 방법 세부와 실측 수치까지 넣어라."
        if calls:
            # 한 번에 다 요구하면 답이 줄거나 중간이 잘린다 → 세 덩어리로 나눠 묻는다
            got = []
            for j, call in enumerate(calls, 1):
                # 제목이 길면 프롬프트가 통째로 거절당한다. 어느 논문인지 알아볼
                # 정도면 되고, 소스는 -s 로 이미 한 편에 묶여 있다.
                head = common.format(title=p["title"][:TITLE_MAX], context=ctx, thin=thin)
                body = head + "\n\n---\n\n" + call
                # 2,700자를 넘으면 NotebookLM 이 통째로 거절한다 (status 3).
                # 프롬프트를 늘렸다가 12편이 전부 빈 채로 끝난 적이 있다 (2026-08-26).
                if len(body) > PROMPT_LIMIT:
                    W.log(f"  ⚠️ 프롬프트 {len(body)}자 — {PROMPT_LIMIT}자 넘음. "
                          f"prompts/paper-understanding.md 를 줄여라.")
                out = ask(nb, body, fresh=(j == 1), source=p.get("source_id"))
                # 답 대신 "문서를 만들었다" 는 식으로 넘어가는 경우가 있다 →
                # 지정한 #### 소제목이 하나도 없으면 한 번 더 세게 묻는다
                if out and "####" not in out:
                    W.log(f"    소제목 없음 — 재요청: {p['title'][:32]}")
                    out = ask(nb, body + "\n\n(다시. 설명하지 말고 위 `####` 소제목을 "
                                         "글자 그대로 쓴 본문만 출력하라. 파일을 만들지 마라.)",
                              source=p.get("source_id"))
                if out:
                    got.append(tidy(out))
                W.log(f"  정리본 {j}/{len(calls)}: {p['title'][:38]}")
            p["summary_parts"] = got
            p["summary"] = "\n\n".join(got)
        else:
            p["summary"] = tidy(ask(nb, FALLBACK_PROMPT.format(title=p["title"], thin=thin)))
            p["summary_parts"] = [p["summary"]] if p["summary"] else []
            W.log(f"  정리본: {p['title'][:45]}")


# ── 4) 논문별 팟캐스트 ───────────────────────────────────────────────

def artifact_ids(nb):
    ok, data = nlm("artifact", "list", "-n", nb, "--json", timeout=300, parse_json=True)
    if not ok:
        return set()
    items = data.get("artifacts") if isinstance(data, dict) else data
    return {a["id"] for a in (items or []) if a.get("id")}


def audio_name(title):
    return re.sub(r"[^\w가-힣-]+", "_", title)[:70].strip("_") + ".m4a"


def attach_existing_audio(papers, tag):
    """이미 만들어 둔 오디오를 파일명으로 다시 붙인다 (정리본만 다시 뽑을 때)."""
    outdir = os.path.join(AUDIO_ROOT, tag)
    n = 0
    for p in papers:
        f = os.path.join(outdir, audio_name(p["title"]))
        p["audio"] = os.path.basename(f) if os.path.exists(f) else None
        n += bool(p["audio"])
    W.log(f"기존 오디오 {n}편 연결")
    return n


def make_podcasts(papers, tag, webhook, cap=PODCAST_DAILY_CAP, after=None):
    """오늘 몫(cap)만큼만 만든다. after 가 있으면 1편 끝날 때마다 부른다.

    한도를 넘겨 부르면 그 뒤 논문이 전부 실패로 날아가므로 cap 에서 멈추고,
    나머지는 --podcasts-only 이어받기 실행(매일 10:30·17:00)이 채운다.
    """
    outdir = os.path.join(AUDIO_ROOT, tag)
    os.makedirs(outdir, exist_ok=True)
    made = 0
    for p in papers:
        p["audio"] = None
        if not p.get("source_id"):
            continue
        if made >= cap:
            W.log(f"  이번 회차 몫 {cap}편 완료 — 나머지는 이어받기 실행에서")
            break
        before = artifact_ids(p["_nb"])
        ok, out = nlm("generate", "audio", "-n", p["_nb"], "-s", p["source_id"],
                      # long 은 21분48초로 길어 default(13분32초)를 쓴다 — 실측 2026-08-25
                      "--language", "ko", "--format", "deep-dive", "--length", "default",
                      # 평소 11분이면 끝나지만 2026-09-08 에 40분을 넘겨도 in_progress 인
                      # 날이 있었다. 짧게 끊으면 한도 슬롯만 태우고 결과를 못 받는다.
                      "--wait", "--timeout", "5400",
                      (f"'{p['title']}' 이 논문 한 편만 깊이 다뤄줘. 연구 배경, 방법과 실험 설계, "
                       "주요 결과를 수치와 함께, 저자가 인정한 한계까지. "
                       "마이크로바이옴 전공 대학원생이 듣는다고 생각하고 전문 용어는 그대로 쓰되 "
                       "처음 나올 때 풀어서 설명해줘."),
                      timeout=5700)
        if not ok:
            W.log(f"  ✗ 팟캐스트 실패: {p['title'][:45]} — {out}")
            if isinstance(out, str) and ("quota" in out.lower() or "rate" in out.lower()):
                if made:  # 0편이면 조용히 — 매일 도는 실행이라 알림만 쌓인다
                    notify(webhook, f"⚠️ 팟캐스트 한도(24시간에 6편)에 걸렸어요. {made}편까지 만들었습니다.")
                break
            continue
        # generate 의 JSON 형태에 기대지 않고 목록 차이로 새 artifact 를 집는다
        new_ids = artifact_ids(p["_nb"]) - before
        art = next(iter(new_ids), None)
        if not art:
            W.log(f"  ✗ 새 오디오를 찾지 못함: {p['title'][:45]}")
            continue
        raw = os.path.join(outdir, f"_raw_{p['pmid'] or made}.m4a")
        ok2, _ = nlm("download", "audio", "-n", p["_nb"], "-a", art, raw,
                     "--force", timeout=900)
        if not ok2 or not os.path.exists(raw):
            W.log(f"  ✗ 다운로드 실패: {p['title'][:45]}")
            continue
        # 256kbps 원본은 말소리엔 과하다 → 64kbps 로 줄이고 원본은 버린다
        final = os.path.join(outdir, audio_name(p["title"]))
        r = subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "64000", raw, final],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(final):
            os.unlink(raw)
        else:  # 변환 실패하면 원본을 그대로 쓴다
            os.replace(raw, final)
            W.log(f"  변환 실패, 원본 보관: {p['title'][:40]}")
        p["audio"] = os.path.basename(final)
        made += 1
        W.log(f"  🎧 {p['title'][:45]} ({os.path.getsize(final)//1024//1024}MB)")
        if after:
            after(p)
    return made


# ── 5) 옵시디언 주차 노트 ────────────────────────────────────────────

NB_RE = re.compile(r"노트북 `([0-9a-fA-F-]{36})`")


def read_notebook_id(tag):
    """주차 노트 머리말에 적어 둔 노트북 id 를 되읽는다 (이어받기용)."""
    path = os.path.join(NOTE_DIR, f"{tag}-weekly-papers.md")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        m = NB_RE.search(f.read())
    return m.group(1) if m else None


def audio_embed(p, tag):
    """오디오 임베드 한 줄. 파일명만 쓰면 Obsidian 이 못 찾는다 —
    실제 파일은 MM/paper-digest-audio/<tag>/ 에 있으므로 경로를 붙인다."""
    return f"\U0001F3A7 ![[MM/paper-digest-audio/{tag}/{p['audio']}]]"


def patch_note_audio(p, tag):
    """이미 쓰인 주차 노트의 그 논문 자리에 🎧 임베드만 끼워 넣는다.

    노트를 통째로 다시 쓰지 않는다 — 정리본은 첫날 것을 그대로 두고, 한 편 만들
    때마다 반영하므로 둘째 날 도중에 또 한도에 걸려도 만든 만큼은 노트에 남는다.
    """
    path = os.path.join(NOTE_DIR, f"{tag}-weekly-papers.md")
    if not p.get("audio") or not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    embed = audio_embed(p, tag)
    if embed in lines:
        return True
    key = p["title"][:60]
    idx = next((i for i, ln in enumerate(lines)
                if ln.startswith("### ") and key in ln), None)
    if idx is None:
        W.log(f"  노트에서 논문 자리를 못 찾음: {p['title'][:40]}")
        return False
    j = idx + 1
    while j < len(lines) and not lines[j].strip():  # 저널·연도 메타줄
        j += 1
    lines[j + 1:j + 1] = ["", embed]  # 메타줄 다음 (write_note 와 같은 자리)
    with open(path, encoding="utf-8", mode="w") as f:
        f.write("\n".join(lines))
    return True

def fold(label, body, kind="abstract"):
    """접어 둘 본문을 옵시디언 콜아웃으로 감싼다.

    `<details>` 를 쓰면 옵시디언이 그 안의 마크다운을 렌더링하지 않는다 —
    `####` 소제목·불릿·`**` 이 글자 그대로 나오고 줄바꿈까지 뭉개진다.
    콜아웃(`> [!abstract]-`)은 접기도 되고 안쪽 마크다운도 그대로 그려진다.
    타입 뒤의 `-` 가 "접힌 채로 시작"을 뜻한다.
    """
    out = [f"> [!{kind}]- {label}"]
    for line in body.split("\n"):
        out.append("> " + line if line.strip() else ">")
    return out


def write_note(papers, tag, nb):
    """디스코드와 같은 순서·분류로 주차 노트를 쓴다."""
    os.makedirs(NOTE_DIR, exist_ok=True)
    today = dt.date.today().isoformat()
    path = os.path.join(NOTE_DIR, f"{tag}-weekly-papers.md")

    L = [
        "---",
        "tags: [weekly-papers, literature, microbiome]",
        f"created: {today}",
        "---",
        "",
        f"# 이번 주 논문 — {tag}",
        "",
        f"> {today} 수신 {len(papers)}편 · 🔵 피인용 상위 · 🟠 최신",
        f"> 정리·팟캐스트는 NotebookLM 노트북 `{nb}` 에서 생성.",
        "",
    ]

    # 카테고리 순서는 papers 에 들어온 순서를 그대로 따른다
    cats = []
    for p in papers:
        c = p.get("category") or "기타"
        if c not in cats:
            cats.append(c)

    n = 0
    for cat in cats:
        group = [p for p in papers if (p.get("category") or "기타") == cat]
        n_cited = sum(1 for p in group if p.get("slot") == "cited")
        n_new = sum(1 for p in group if p.get("slot") == "new")
        L += [f"## {cat}",
              "",
              f"🔵 피인용 {n_cited}편 · 🟠 최신 {n_new}편",
              ""]
        for p in group:
            n += 1
            mark = "🟠" if p.get("slot") == "new" else "🔵"
            L += [f"### {mark} {n}. {p['title']}", ""]
            meta = [p["journal"], str(p["year"])]
            L += ["  ·  ".join(x for x in meta if x) + f"  ·  [원문]({p['link']})", ""]
            if p.get("audio"):
                L += [audio_embed(p, tag), ""]
            if p.get("thin"):
                L += ["> ⚠️ 초록만 확보된 논문 — 아래 정리는 초록 범위입니다.", ""]
            parts = p.get("summary_parts") or ([p["summary"]] if p.get("summary") else [])
            if not parts:
                L += ["_정리본 생성 실패_", "", "---", ""]
                continue
            # 1번 콜 앞머리의 '한 줄 메시지' 는 접지 않고 바로 보이게 꺼낸다
            first = parts[0]
            m = re.search(r"####\s*한 줄 메시지\s*\n(.+?)(?=\n####|\Z)", first, re.S)
            if m:
                L += [m.group(1).strip(), ""]
                first = first[:m.start()] + first[m.end():]
            folds = [("개요 · 공부 단어장", "abstract"),
                     ("Methods · Results", "example"),
                     ("워크스루 · 핵심 개념", "note")]
            for k, body in enumerate([first] + parts[1:]):
                body = body.strip()
                if not body:
                    continue
                label, kind = folds[k] if k < len(folds) else (f"정리 {k + 1}", "note")
                L += fold(label, body, kind) + [""]
            L += ["---", ""]

    L += [
        "## 관련 노트",
        "",
        "- [[MOC-weekly-papers]] — 주차 노트 인덱스",
        "- [[MOC-04-References]] · [[MOC-study-notes]]",
        "- 프로젝트: [[03_Projects/Envtox-mouse/CLAUDE|Envtox-mouse]] · "
        "[[03_Projects/PLA_mouse/CLAUDE|PLA_mouse]]",
        "",
        f"오디오 파일 위치: `MM/paper-digest-audio/{tag}/`",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    W.log(f"주차 노트 작성: {path}")
    update_moc(tag)
    return path


def update_moc(tag):
    """주차 노트 인덱스(MOC). 없으면 만들고, 있으면 한 줄 추가한다."""
    moc = os.path.join(NOTE_DIR, "MOC-weekly-papers.md")
    line = f"- [[{tag}-weekly-papers]]"
    if not os.path.exists(moc):
        with open(moc, "w", encoding="utf-8") as f:
            f.write("\n".join([
                "---", "tags: [moc, weekly-papers, hub]",
                f"created: {dt.date.today().isoformat()}", "---", "",
                "# MOC — 이번 주 논문",
                "",
                "매주 월요일 자동 수집된 논문 12편의 주차 노트 인덱스. "
                "생성 절차는 `_Tools/paper-digest/README.md` 에 있다.",
                "",
                "## 주차 노트", "", line, "",
                "## 관련 노트", "", "- [[MOC-04-References]]", "",
            ]))
        W.log(f"MOC 생성: {moc}")
        return
    with open(moc, encoding="utf-8") as f:
        body = f.read()
    if line in body:
        return
    body = body.replace("## 주차 노트\n\n", f"## 주차 노트\n\n{line}\n", 1)
    with open(moc, "w", encoding="utf-8") as f:
        f.write(body)


# ── 6) 실행 ─────────────────────────────────────────────────────────

def cleanup_pdfs(papers):
    """업로드에 성공한 PDF 만 지운다. 실패·미매칭분은 남겨 다음 주에 재시도한다."""
    gone = []
    for p in papers:
        if p.get("pdf") and p.get("source_id") and not p.get("thin"):
            try:
                os.remove(p["pdf"])
                gone.append(os.path.basename(p["pdf"]))
            except OSError as e:
                W.log(f"  삭제 실패 {p['pdf']}: {e}")
    if gone:
        W.log(f"PDF {len(gone)}개 삭제: {', '.join(gone[:3])}" + (" 외" if len(gone) > 3 else ""))
    return gone


def resume_podcasts(papers, tag, resume, hook):
    """이어받기 실행 — 정리본은 그대로 두고 남은 팟캐스트만 이어 만든다.

    노트북 id 는 주차 노트 머리말에서 되읽고, 소스는 제목으로 다시 붙인다.
    PDF drop 폴더는 첫날 비워졌으므로 점검하지 않는다.
    """
    if not os.path.exists(os.path.join(NOTE_DIR, f"{tag}-weekly-papers.md")):
        # 매일 도는 스케줄이라 주차 노트가 아직 없는 시간대가 정상적으로 있다.
        W.log(f"{tag} 주차 노트가 아직 없음 — 조용히 종료")
        return 0
    nb = resume or read_notebook_id(tag)
    if not nb:
        W.log(f"이어받을 노트북을 못 찾음 — {tag} 주차 노트가 없거나 머리말이 바뀌었다.")
        notify(hook, f"⚠️ 팟캐스트 이어받기 실패 ({tag}): 노트북 id 를 못 찾았습니다.")
        return 1
    W.log(f"이어받기 — 노트북 {nb}")
    attach_notebook(papers, nb)
    for p in papers:
        p["_nb"] = nb
    attach_existing_audio(papers, tag)

    todo = [p for p in papers if not p.get("audio") and p.get("source_id")]
    if not todo:
        W.log("남은 팟캐스트 없음 — 종료")
        return 0
    W.log(f"남은 팟캐스트 {len(todo)}편")
    made = make_podcasts(todo, tag, hook, after=lambda q: patch_note_audio(q, tag))
    total = sum(1 for p in papers if p.get("audio"))
    left = len(todo) - made
    W.log(f"=== 이어받기 완료 — 이번에 {made}편, 주차 전체 {total}/{len(papers)}편 ===")
    if not made:
        return 0  # 한 편도 못 만들었으면 알리지 않는다
    notify(hook, (f"🎧 **팟캐스트 이어받기** ({tag}) — {made}편 추가, "
                  f"전체 {total}/{len(papers)}편.\n"
                  + (f"· {left}편이 아직 남았습니다 (한도). 다음 실행에서 이어집니다.\n"
                     if left else "")))
    return 0


def main():
    check_only = "--check" in sys.argv
    dry = "--dry-run" in sys.argv
    tag = week_tag()
    W.log(f"=== NotebookLM 연동 시작 ({tag}) ===")
    secrets = W.load_secrets()
    hook = secrets.get("DISCORD_WEBHOOK_URL")

    try:
        papers = load_papers()
    except PaperLookupError as e:
        W.log(f"⛔ {e} — 빠진 채 진행하지 않고 멈춥니다. Europe PMC 복구 뒤 다시 실행하세요.")
        notify(hook, f"⛔ {tag} 연동 중단: {e}\n복구 뒤 `./run_notebook.sh` 를 다시 실행하세요.")
        return 1
    if not papers:
        W.log("이번 주 논문을 찾지 못했습니다. 종료.")
        return 1
    resume = None
    if "--notebook" in sys.argv:
        resume = sys.argv[sys.argv.index("--notebook") + 1]

    if "--podcasts-only" in sys.argv:
        return resume_podcasts(papers, tag, resume, hook)

    missing, unmatched = match_pdfs(papers)
    if resume:
        # 이어받는 경우 PDF 는 이미 노트북에 올라가 있고 원본은 지워졌다.
        # 폴더가 비었다고 "빠졌다"고 알리면 거짓 경보가 된다.
        W.log("이어받기 — drop 폴더 점검 건너뜀 (소스는 노트북에 이미 있음)")
    else:
        report_pdf_status(papers, missing, unmatched, hook, final=not check_only)

    if check_only:
        W.log("=== 점검만 하고 종료 (--check) ===")
        return 0
    if dry:
        for p in papers:
            W.log(f"  {'PDF' if p['pdf'] else 'URL'} | {p['title'][:55]}")
        W.log("=== dry-run 종료 ===")
        return 0

    if resume:
        nb, err = attach_notebook(papers, resume), None
        W.log(f"기존 노트북 이어쓰기: {nb}")
    else:
        nb, err = build_notebook(papers, tag)
    if err or not nb:
        notify(hook, f"⚠️ NotebookLM 연동 실패 (노트북 준비): {err}")
        return 1
    for p in papers:
        p["_nb"] = nb
    verify_sources(nb, papers)
    make_summaries(nb, papers)
    if "--skip-podcasts" in sys.argv:
        made = attach_existing_audio(papers, tag)
    else:
        made = make_podcasts(papers, tag, hook)
    left = sum(1 for p in papers if p.get("source_id") and not p.get("audio"))
    path = write_note(papers, tag, nb)
    gone = [] if "--skip-podcasts" in sys.argv else cleanup_pdfs(papers)

    notify(hook, (
        f"📝 **이번 주 논문 정리 완료** ({tag})\n"
        f"· 정리본: 옵시디언 `04_References/Weekly-papers/{os.path.basename(path)}`\n"
        f"· 팟캐스트 {made}편: `MM/paper-digest-audio/{tag}/`\n"
        + (f"· PDF {len(gone)}개 정리함\n" if gone else "")
        + (f"· 남은 {left}편은 매일 10:30·17:00 이어받기가 채웁니다\n" if left else "")
        + (f"· ⚠️ 초록만 처리된 논문 {sum(1 for p in papers if p.get('thin'))}편\n"
           if any(p.get("thin") for p in papers) else "")
    ))
    W.log("=== 완료 ===")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        W.log(f"치명적 오류: {e}")
        sys.exit(1)
