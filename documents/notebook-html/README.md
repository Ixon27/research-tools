# 연구노트 → HTML 공유 도구

`01_Research/연구노트/`의 실험 기록을 **하나의 세련된 HTML**로 자동 변환해
Dropbox 공유 폴더에 올려두는 도구. 볼트에서 실험을 추가·수정·삭제하면 **수 초 내 자동 갱신**된다.

> 🔴 **내용은 [`_Tools/html-templates/내용-규칙.md`](../html-templates/내용-규칙.md) 을 따른다.** 이 스크립트는 형식(디자인·레이아웃)만 만들고, 무엇을 어떻게 쓰느냐는 템플릿과 무관하게 그 파일이 정한다 — 특히 §14 정본 대조 · §16 절차 형식 · §17 정본 동기화 · §18 파일명.

## 무엇을 하나
- 각 실험(`## YYYY.MM.DD — 제목`)에서 **6개 필드만** 뽑아 카드로: 실험일자·이름·실험제목·실험목적·실험 내용·주의할 점 및 보완할 점
- 맨 위 **월별 캘린더**: 실험한 날 하이라이트(기간은 전 구간), 클릭 시 해당 실험으로 이동
- 내부 참조(`[[위키링크]]`)·개인 메모·출처 이모지는 타인이 볼 수 없으니 자동 제거
- 왼쪽 사이드바: 프로젝트 클릭 → 실험 목록 펼침 + 검색

## 파일 위치
| 구분 | 경로 |
|---|---|
| 빌드 스크립트 | `_Tools/notebook-html/build_notebook_html.py` |
| 출력 HTML(공유용) | `~/Dropbox/연구노트/연구노트.html` |
| 로그 | `~/Library/Logs/notebook-html/watch.log` |
| 자동 실행 설정 | `~/Library/LaunchAgents/com.<you>.notebook-html.plist` |

## 공유 방법
Dropbox `연구노트` 폴더를 **공유 폴더로 상대를 초대** → 상대 컴퓨터에 동기화된
`연구노트.html`을 더블클릭하면 열린다. (Dropbox 공유 링크는 HTML을 렌더 안 하니 공유 폴더 방식 사용)

## 자주 쓰는 명령 (터미널)
```bash
S=<볼트>/_Tools/notebook-html/build_notebook_html.py
python3 "$S"            # 지금 즉시 1회 빌드
P=~/Library/LaunchAgents/com.<you>.notebook-html.plist
launchctl unload "$P"; launchctl load "$P"   # 자동감시 재시작 (스크립트 수정 후 필요)
launchctl list | grep notebook-html          # 동작 확인 (가운데 열 0 = 정상)
```

> ⚠️ **스크립트를 수정하면** 위 `unload/load`로 자동감시를 재시작해야 새 코드가 반영된다.
> 표시할 필드·디자인·캘린더 규칙은 모두 스크립트 상단 설정과 `build()` 부분에서 조정.
