# pipeline-check — 프로젝트·논문 폴더 구조 점검

`02_Papers/` · `03_Projects/` 의 각 폴더가 볼트 표준과 건식 파이프라인 배치표를 지키는지 본다. 외부 의존 없음(Python 표준 라이브러리만).

## 무엇을 잡나

| 항목 | 기준 문서 |
|------|------|
| **고정 폴더 골격**을 벗어난 하위 폴더 이름 | `guide-02-03-폴더구조` — `methods/`→`protocols/` 처럼 고칠 곳을 알려준다 |
| 필수 4종(`README.md`·`AGENTS.md`·`STATUS.md`·`session-logs/`) 존재 | 같은 문서 — 우산 트랙 예외 반영 |
| `README.md` 헤딩에 진행 상태·blocker 가 있나 | 같은 문서 공통규칙 3 (지도 ↔ 현황판 분리) |
| `AGENTS.md` 150줄 상한 (상태형) | 같은 문서 |
| 파이프라인 산출물이 제 위치에 있나 | `dry-research-pipeline` 배치표 |
| `analysis-plan` 에 「사전 예측」·「n 의 단위」 절이 있나 | 같은 문서 4단계 |
| 한 폴더 안 넘버링 접두어 혼용 | 가이드 공통규칙 1 |
| 파일명 볼트 전체 유일성 | 가이드 공통규칙 3 |
| 연구 유형이 등록표에 있나 | `research-type-registry` |
| 02 `AGENTS.md` 에 `- **파생 프로젝트**:` 줄이 있나 | `guide-02-03-폴더구조` 「논문의 파생 프로젝트 명시」 |

## 사용법

```bash
cd <볼트>
python3 _Tools/pipeline-check/pipeline_check.py            # 터미널로
python3 _Tools/pipeline-check/pipeline_check.py --report   # 00_Inbox/pipeline-check-YYYY-MM-DD.md
python3 _Tools/pipeline-check/pipeline_check.py --only Scalp   # 폴더 하나만
```

## 설계 원칙 (고칠 때 지킬 것)

- **산출물 부재는 오류가 아니다.** 아직 그 단계에 도달하지 않았다는 정보로 보고한다. 빈 파일을 만들라고 재촉하지 않는다 — 「빈 폴더를 미리 만들지 않는다」 규칙과 충돌하기 때문.
- **유형 목록을 하드코딩하지 않는다.** `04_References/Pipelines/research-type-registry.md` 를 파싱한다. 유형이 늘면 등록표에 행만 추가하면 되고 이 스크립트는 안 고친다.
- **산출물은 접미사로 찾는다.** 파일명 접두어는 폴더명이 아니라 고유어다(`Envtox-mouse` → `Envtox-analysis-plan.md`). 접두어를 폴더명으로 고정하면 오탐이 난다.
- **`session-logs/` 안은 산출물 탐색에서 뺀다.** 그날의 기록이라 같은 접미사가 우연히 걸릴 수 있다.
- **골격 밖 폴더를 무조건 오류로 보지 않는다.** `isolates/`·`<균주명>/` 같은 대상별 하위 폴더는 정상이라 참고로만 띄우고, `methods/`·`mechanism/` 처럼 골격 이름과 겹치는 자리만 오류로 올린다(`FOLDER_ALIASES`).
- **README 검사는 헤딩만 본다.** 본문의 "진행 상태는 여기 적지 않는다" 같은 면책 문구를 잡으면 정상 README 가 전부 위반으로 뜬다 — 2026-08-27 에 실제로 그랬다.
- `AGENTS.md`·`STATUS.md`·`README.md` 는 파일명 유일성 검사에서 제외한다 — 폴더마다 있어야 하는 구조 파일이다.

## 함께 쓰는 도구

- `graph-health` — wikilink·MOC·frontmatter 위생. 파일을 개명·이동한 **직후** 함께 돌린다.
