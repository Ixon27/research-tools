# graph-health — 볼트 그래프 건강검진

Obsidian 볼트의 `.md` 노트를 스캔해 그래프 위생 문제를 찾는다. 외부 의존 없음(Python 표준 라이브러리만).

## 무엇을 잡나

| 항목 | 의미 |
|------|------|
| 깨진 wikilink | `[[대상]]`이 실제 노트·자산을 가리키지 않음 |
| 빈 링크 `[[]]` | 대상이 비어 있는 링크(오타·미완성) |
| 고아 노트 | 들어오는 링크 0 + 어떤 MOC에도 등록 안 됨 |
| MOC 미등록 노트 | `MOC-*.md` 어디에서도 링크 안 됨 (그래프 연결 규칙 위반) |
| frontmatter 결손 | `tags` 또는 `created` 누락 |

## 사용법

```bash
cd <볼트>/_Tools/graph-health
python3 graph_health.py            # 요약+상세를 터미널에
python3 graph_health.py --report   # 00_Inbox/graph-health-YYYY-MM-DD.md 로 저장(Obsidian에서 열람)
```

## 볼트 관습에 맞춘 처리 (오탐 억제)

- **코드블록 무시** — bash `[[ ]]` 테스트·Python 리스트가 wikilink로 오인되지 않게 코드펜스·인라인코드 제거 후 스캔.
- **NFC/NFD 정규화** — macOS 한글 파일명(NFD)과 링크 텍스트(NFC) 매칭. (`[[01-1_NAS서버_QIIME2_README]]` 같은 한글 노트 정상 인식)
- **경로 꼬리 매칭** — `[[Paenibacillus-terrigena/03_DNA-extraction]]`처럼 부분경로를 Obsidian식 suffix로 해석.
- **자산·MM 확인** — `.png`/`.pdf`/`.xlsx` 및 `MM/` 심링크 대상은 디스크에서 존재 확인(첨부 임베드를 깨진 링크로 오판 안 함).
- **제외** — 링크 대상 색인에서 `.obsidian`·`.trash`·`.git`·`MM`(무거운 심링크)는 walk 제외(경로 링크는 디스크로 확인). 그래프 노드 분석에서 `_Templates`·`Attachments`·`AGENTS.md` 제외(별도 체계·문서라 예시 링크 노이즈).

## 정기 실행 (선택)

paper-digest처럼 cron으로 주 1회 리포트를 만들 수 있다. 예) 매주 월요일 08:00:

```cron
0 8 * * 1 cd <볼트>/_Tools/graph-health && /usr/bin/python3 graph_health.py --report
```

리포트는 `00_Inbox/`에 쌓이므로 주간 정리 때 함께 확인.
