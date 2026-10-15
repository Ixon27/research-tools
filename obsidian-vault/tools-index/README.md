# tools-index — 도구 안내 자동 생성기

볼트의 모든 도구(커맨드 + 스크립트)를 한 노트로 목록화한다. 커맨드 frontmatter의 `description`이 원본이라, 도구를 고치고 이 스크립트를 다시 돌리면 안내가 갱신된다.

## 실행

```bash
python3 _Tools/tools-index/build_index.py
```

- 산출: `_Tools/도구-안내.md` — Obsidian에서 `[[도구-안내]]`로 열림.
- 스캔 대상: `.claude/commands/`(볼트) + `_Tools/*/`.

## 무엇을 뽑나

| 대상 | 뽑는 것 |
|------|---------|
| 커맨드(.md) | 이름 + frontmatter `description` 첫 문장 + 실행 위치 + 산출물 + **워크플로우 단계**(##/### 헤딩) |
| 스크립트(_Tools/*) | README H1 요약 + 실행법(py→python3, sh→bash) + 산출물 |

**워크플로우 섹션**: 커맨드 파일은 `.claude/`(Obsidian 숨김 폴더)라 볼트에서 안 열린다. 그래서 각 커맨드의 단계 뼈대를 뽑아 `도구-안내.md`에 넣는다 — "무엇을 어떤 순서로" 하는지 보고 뭘 고칠지 판단하는 용도.

산출물 위치는 `build_index.py`의 `OUTPUT_OF` 맵에서. 새 도구 추가 시 여기 한 줄 넣고 재생성.

## 규칙

`도구-안내.md`는 **직접 편집하지 않는다**(재생성 시 덮어써짐). 설명을 바꾸려면 원본 커맨드 파일의 `description`을 고치고 다시 돌린다. 볼트 AGENTS.md "도구 안내 자동 갱신 규칙" 참조.
