# HTML 산출물 — 형식과 내용

HTML을 만들 때 **형식(디자인)** 과 **내용(무엇을 어떻게 쓰나)** 을 나눠 관리한다.

```
내용 규칙   내용-규칙.md          ← 어떤 템플릿을 쓰든 항상 적용
   형식     ├ 볼트 고정 디자인    designs/notebook · designs/deck   (재현성이 필요한 것)
            └ effective-html 스킬  html · wireframe · prototype · plan · diagram  (그 외)
   검사     check_html.py         ← 만든 뒤 반드시. 통과해도 눈으로 한 번 더
```

## 사용 규약 (Claude용)

1. **[`내용-규칙.md`](내용-규칙.md) 을 먼저 읽는다.** 템플릿과 무관하게 항상 적용된다.
   가장 흔한 사고는 **볼트 문서를 그대로 옮겨 지침문이 산출물에 남는 것**이다.
2. **형식을 고른다.**
   - **재현성이 필요한 것**(학습노트·연구노트처럼 같은 계열을 계속 만드는 것) → `notebook`.
     CSS를 그대로 인라인하고 **색·폰트·레이아웃을 임의로 바꾸지 않는다.**
   - **발표 슬라이드** → `deck` 은 **출발점**이지 의무가 아니다. 주제에 맞게 새로 잡아도 되지만
     **슬라이드 셸(`.slide` > `.slide-inner`)과 자동 축소 스크립트는 유지**한다 — 잘림 검사가 여기 걸려 있다.
   - **그 외(리포트·설명서·와이어프레임·프로토타입·다이어그램)** → `html` 스킬이 상황에 맞게 라우팅한다.
3. 마크업 관례는 `designs/<name>.example.html` 을 따른다.
4. self-contained 1파일 — 이미지는 base64. **발표물은 폰트도 파일에 넣는다**(현장에 인터넷이 없을 수 있다).
   읽는 문서는 CDN 폰트가 끊겨도 시스템 폰트로 떨어지므로 허용.
5. 다 만들면 **`python3 _Tools/html-templates/check_html.py <파일>`** 로 검사한다.

## 등록된 디자인

| 이름 | 파일 | 설명 | 등록일 |
|---|---|---|---|
| **notebook** | `designs/notebook.css` (+ `notebook.example.html`) | **읽는 문서용.** 좌측 남색 그라디언트 사이드바(브랜드+검색+접이식 nav) + sticky topbar + 미니멀 흰 카드(액센트 바 라벨, 부드러운 그림자, 파란 #4a90d9 팔레트). Nunito + Noto Sans KR. | 2026-07-07 |
| **deck** | `designs/deck.css` + `designs/deck-fonts.css` (+ `deck.example.html`) | **발표·랩미팅용 슬라이드.** 화면 한 장 = 슬라이드 하나(scroll-snap), ← → 키로 이동, 넘치면 자동 축소, 슬라이드마다 레퍼런스 각주. notebook과 같은 팔레트에 **남색 그라디언트 반전 슬라이드**. Pretendard를 파일에 넣어 둬서 오프라인·미설치 환경에서도 같게 보인다. | 2026-08-14 |

> 새 디자인 추가 시: `designs/<name>.css` + `designs/<name>.example.html` 만들고 위 표에 한 줄 등록.

## effective-html 스킬 (전역 설치됨)

`~/.claude/skills/` 에 6개가 깔려 있다 — 출처 `github.com/plannotator/effective-html` (MIT).

| 스킬 | 언제 |
|---|---|
| `html` | **라우터.** 리포트·설명서·랜딩·발표·도구 등 HTML이 산출물이면 여기서 시작해 아래로 넘긴다 |
| `design-artifact` | 색·타이포·구성·톤이 아직 안 정해졌을 때 |
| `html-wireframe` | 구조·정보 위계·흐름을 먼저 시험할 때 (저충실도) |
| `html-prototype` | 다듬은 목업이나 동작하는 흐름이 필요할 때 |
| `html-plan` | 계획·로드맵·실행 순서가 주 내용일 때 |
| `html-diagram` | 관계·순서·구조 자체가 주 내용일 때 |

> ⚠️ 이 스킬들은 *"이전 산출물의 팔레트를 재현하지 말라"* 고 명시한다.
> **`notebook` 과는 목적이 반대**이므로, 같은 계열을 계속 만드는 것에만 고정 디자인을 쓴다.
> 발표물은 스킬의 발표 일반론을 따르되 **볼트 고유 항목(내용 규칙·셸 구조·산출 위치·검사)은 `/lab-deck`** 에 있다.
> **내용 규칙은 어느 쪽이든 똑같이 적용된다.**

## 검사

```bash
python3 _Tools/html-templates/check_html.py <파일.html>
python3 _Tools/html-templates/check_html.py <파일.html> --sizes 1920x1080,1440x900
```

정적으로 **외부 리소스·이모지·서술형 제목·명사형 아닌 제목·볼트 용어 유출·작성자 말투**를,
headless Chrome 렌더로 **가로 스크롤·JS 오류**를 본다.

> **「명사형 아닌 제목」은 warn 이고 걸린 제목을 전부 찍는다** (2026-08-31 추가).
> 원래는 `-습니다/-입니다` 만 봐서 `-는가` · `-한다` · `-된다` 로 끝나는 제목을 통째로 놓쳤고,
> `h3`(카드 소제목)는 아예 안 봤다. 다만 명사형 여부는 정규식으로 완전히 갈리지 않아
> (「네 가지」·「단가」 같은 꼬리) **err 가 아니라 warn 으로 두고 사람이 판정**한다.
> `-다` 로 끝나는 정상 명사는 `NOUN_DA` 집합에 추가하면 오탐이 사라진다.
슬라이드(`.slide`)가 있으면 **잘리는 슬라이드**를 추가로 센다 —
자동 축소 때문에 **잘려도 눈에 잘 안 띄어서** 이 검사가 가장 중요하다.
통과(exit 0)해도 **좌표 실수와 겹침은 못 잡으므로 눈으로 한 번 더** 본다.

## deck 을 쓸 때

`deck.css` 를 그대로 쓰려면 **`deck-fonts.css` 를 먼저** 인라인한다 (431 KB, Pretendard 400·600 서브셋).

> **`deck-fonts.css` 는 이 저장소에 넣지 않았다**(폰트 재배포 라이선스). [Pretendard 공식 배포본](https://github.com/orioncactus/pretendard)(SIL OFL 1.1)의 400·600 woff2 를 base64 로 `@font-face` 에 넣어 같은 이름으로 만든다. 없어도 슬라이드는 동작하고, 글꼴만 시스템 기본 글꼴로 바뀐다.
디자인을 새로 잡더라도 **셸 구조와 자동 축소 스크립트는 `deck.example.html` 에서 가져온다.**
발표물 전용 절차와 셀프체크는 `/lab-deck` 커맨드에.

## 마크업 관례 (deck)

```
<section class="slide t1" data-topic="왼쪽 아래 위치 라벨">
  <div class="slide-inner">          ← 이 두 겹 구조는 반드시 지킨다 (자동 축소가 여기 걸린다)
    <div class="eyebrow">머리말</div>
    <h2>명사형 제목</h2>
    …  .row2 / .fact-list / table / .card(.hi) / dl.terms / .fig > svg / .note
    <div class="refs">저자 연도, 저널 권:쪽<br>…</div>
  </div>
</section>
…
<div id="topicLabel"></div><div id="counter"></div>
<script> … 키보드 이동 + 카운터 + 자동 축소 … </script>
```

`.invert` = 남색 반전(주제 구분·결정 장) · `.t1/.t2/.t3` = 주제별 강조색 ·
`.tag warn|key` = 이모지 대신 쓰는 인라인 표시 · `.pill ok|warn|dead` = 상태 · `.dim` = 흐린 부연.
전체 스켈레톤은 `designs/deck.example.html`.

## 마크업 관례 (notebook)

```
<div id="wrap">
  <nav class="sidebar">
    <div class="brand">🧬 제목</div>
    <div class="brand-sub">부제</div>
    <input class="sb-search" placeholder="검색…">
    <div class="nav-group open">
      <button class="nav-head">섹션 <span class="nav-cnt">N</span> <span class="nav-arrow">▶</span></button>
      <div class="nav-items"><a class="nav-link" href="#id">항목</a>…</div>
    </div>
  </nav>
  <div id="main">
    <div class="topbar"><h1>제목</h1><span class="meta">메타</span></div>
    <div class="container">
      <div class="section-block">
        <div class="block-h">대섹션</div><div class="block-sub">설명</div>
        <div class="exp-card" id="id">
          <div class="exp-head"><span class="exp-date">라벨</span><span class="exp-project">태그</span></div>
          <div class="exp-title">카드 제목</div>
          <div class="field"><div class="field-label">필드명</div><div class="field-body">내용</div></div>
        </div>
      </div>
      <div class="footer">footer</div>
    </div>
  </div>
</div>
```
