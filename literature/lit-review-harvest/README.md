# lit-review — 문헌 코퍼스 수집기

리뷰논문·서론 문헌조사를 위해 한 주제의 논문을 **전수 수집**한다. **Europe PMC + OpenAlex**(둘 다 무료·무키), 표준 라이브러리만. `/review-paper` 커맨드의 2단계 엔진.

- **Europe PMC** — 생의학·미생물 특화, 초록 충실
- **OpenAlex** — 전분야 커버리지, 저널(venue)·인용그래프 품질신호
- `both`(기본)면 둘을 합쳐 DOI→제목으로 중복 제거. `source`가 `epmc+openalex`면 두 곳 모두 색인된 논문.

## 사용법

```bash
python3 harvest.py "<쿼리>" [옵션]

python3 harvest.py "gut microbiome obesity" --since 2018 --max 400
python3 harvest.py 'TITLE:"Paenibacillus" AND TITLE_ABS:genome' --source epmc
python3 harvest.py "extremophile thermostability" --source openalex --min-cited 20
```

| 옵션 | 뜻 |
|------|-----|
| `--source {both,epmc,openalex}` | 소스 선택(기본 both) |
| `--max N` | **소스별** 최대 수집 편수(기본 500) |
| `--since YEAR` | 이 연도 이후만 |
| `--min-cited N` | 인용 N회 이상만(수집 후 필터) |
| `--open-only` | OA(전문 무료)만 |
| `--out DIR` | 출력 폴더(기본 `./out/<날짜>`) |

> `both`는 쿼리를 **자유어(키워드)**로 다룬다. Europe PMC 필드문법(`TITLE:` 등)을 쓰려면 `--source epmc`.

## 산출물

- `corpus.md` — 인용순 표(연도·인용·OA·제목·저자·저널·DOI) + 각 논문 초록. Obsidian에서 바로 열람·스크리닝.
- `corpus.csv` — 동일 데이터 표 형식(엑셀·통계용).

중복은 DOI→제목 정규화로 제거. 인용수는 Europe PMC `citedByCount`.

## 쿼리 문법 (Europe PMC)

- 필드: `TITLE:`, `TITLE_ABS:`(제목+초록), `AUTH:`, `JOURNAL:`, `PUB_YEAR:[2020 TO 3000]`, `OPEN_ACCESS:Y`, `HAS_ABSTRACT:Y`
- 불리언: `AND OR NOT`, 구문은 `"..."`, 와일드카드 `*`
- 예시는 `_Tools/paper-digest/config.json`의 category 쿼리 참고.

## Zotero 연동 (선택 — 인용 관리)

`/review-paper`·`/research-paper`가 참고문헌을 만들 때, **Zotero MCP가 연결돼 있으면** 볼트의 Zotero 라이브러리에서 인용을 직접 가져와 bib를 만든다(수기 입력보다 정확·citekey 일관). 연결 안 돼 있으면 lit-review 코퍼스/`04_References/Papers`에서 만든다.

- **필요 조건**: Zotero용 MCP 서버를 Claude Code에 1회 연결해야 한다(사용자 설정). 커뮤니티 Zotero MCP 서버들이 있으며, `claude mcp add ...`로 등록한다 — 정확한 패키지·명령은 그 서버 문서를 따른다.
- 연결 여부는 세션에서 Zotero MCP 도구가 보이는지로 판단하고, **없으면 조용히 코퍼스 방식으로 폴백**한다(추측해서 인용 만들지 않음).

## 주의
- 초록 기반 1차 스크리닝용. 핵심 주장·수치는 전문(본문·그림)으로 확인(`/review-paper` 4단계 검증).
- 인용수는 시점 스냅샷(EPMC=citedByCount, OpenAlex=cited_by_count 중 큰 값). 저널 급 판단은 별도.
- `both`도 완전 전수는 아님(소스별 `--max` 상한). 넓은 주제는 `--max`를 키우거나 쿼리를 좁혀 반복.
