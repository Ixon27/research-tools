# research-tools

미생물학 대학원 연구를 하면서 직접 만들어 쓰는 도구 모음입니다.
문헌 수집, 문서 변환, 그래프 수치 판독, 수업용 퀴즈, Obsidian 연구 볼트 관리까지 용도별로 나눠 두었습니다.

## 도구 목록

### 📚 literature — 문헌 수집·정리

| 도구 | 하는 일 | 필요한 것 |
|---|---|---|
| [lit-review-harvest](literature/lit-review-harvest/) | 한 주제의 논문을 Europe PMC + OpenAlex 에서 전수 수집해 중복 제거한 목록(Markdown·CSV)으로 | Python 표준 라이브러리 |
| [paper-digest](literature/paper-digest/) | 매주 내 분야 논문을 골라 요약해서 디스코드·메일로 발송 + NotebookLM 정리본·팟캐스트 생성 | Claude CLI 또는 API 키, (선택) notebooklm-py |

### 📄 documents — 문서 만들기·변환

| 도구 | 하는 일 | 필요한 것 |
|---|---|---|
| [hwp-tools](documents/hwp-tools/) | 한글(HWP 5.x) 파일 본문 읽기, 기존 양식에 텍스트 채우기 | `olefile` |
| [notebook-html](documents/notebook-html/) | Obsidian 연구노트 → 공유용 HTML 한 장 (캘린더·검색, 변경 시 자동 갱신) | pandoc |
| [course-html](documents/course-html/) | 과목 학습노트 → 예상문제를 직접 풀 수 있는 인터랙티브 HTML | pandoc |
| [html-templates](documents/html-templates/) | 노트·슬라이드용 HTML 디자인 + 결과물 자체 검사기(`check_html.py`) | Python 표준 라이브러리 |

### 📊 data-extraction — 데이터 추출

| 도구 | 하는 일 | 필요한 것 |
|---|---|---|
| [plot-digitizer](data-extraction/plot-digitizer/) | 논문 막대그래프 이미지에서 평균·오차막대 값을 픽셀로 판독 (메타분석용) | `numpy`, `pillow`, poppler |

### 🎓 teaching — 수업

| 도구 | 하는 일 | 필요한 것 |
|---|---|---|
| [quiz-generator](teaching/quiz-generator/) | 문제은행(파이썬 파일) → 채점형 시험 HTML + 즉답 학습 HTML | Python 표준 라이브러리 |

### 🗂️ obsidian-vault — 연구 볼트 관리

| 도구 | 하는 일 | 필요한 것 |
|---|---|---|
| [pipeline-check](obsidian-vault/pipeline-check/) | 프로젝트·논문 폴더가 정해진 구조를 지키는지 점검 | Python 표준 라이브러리 |
| [graph-health](obsidian-vault/graph-health/) | 끊긴 위키링크·고립 노트 등 그래프 위생 점검 | Python 표준 라이브러리 |
| [tools-index](obsidian-vault/tools-index/) | 볼트의 도구·커맨드를 한 노트로 자동 목록화 | Python 표준 라이브러리 |

## 쓰기 전에

- **볼트 도구는 `<볼트>/_Tools/<도구이름>/` 에 넣어 쓰도록 만들었습니다.** 볼트 경로는 환경변수 `VAULT` 로 바꿀 수 있고, 없으면 스크립트 위치에서 두 단계 위를 볼트로 봅니다.
- 폴더 이름(`01_Research/연구노트`, `02_Papers`, `03_Projects`, `04_References` 등)은 제 볼트 구조 기준입니다. 다른 구조라면 각 스크립트 맨 위의 설정 부분을 고쳐 쓰세요.
- 설명서와 코드 주석은 한국어입니다.
- macOS 에서 만들고 썼습니다.

## 라이선스

**All rights reserved.** 자세한 내용은 [LICENSE](LICENSE) 를 보세요.
코드를 읽고 참고하는 것, 출처를 밝히고 학술적으로 인용하는 것은 괜찮습니다. 수정·재배포·다른 프로젝트에 포함하려면 먼저 연락해 주세요.
