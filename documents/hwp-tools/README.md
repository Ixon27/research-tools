# hwp-tools — 한글(HWP 5.x) 파일 읽기·채우기

한컴오피스 없이 Python으로 `.hwp` 파일의 **본문 텍스트를 읽고**, 기존 양식의 **문단 텍스트를 바꿔 넣는다.**
지원서·보고서처럼 서식이 정해진 HWP 양식에 내용을 채울 때 쓴다.

- 기존 문단의 텍스트만 바꾼다. 행·문단을 새로 추가하지는 않는다.
- 표·그림 같은 컨트롤이 들어 있는 문단은 깨지지 않도록 덮어쓰기를 거부한다.
- 줄 배치 정보(`PARA_LINE_SEG`)를 지워 두면 한글이 파일을 열 때 레이아웃을 다시 계산한다.

## 필요한 것

```bash
pip install olefile
```

## 파일

| 파일 | 하는 일 |
|---|---|
| `hwplib.py` | 읽기 도우미 — OLE 스트림 → `BodyText/SectionN` 압축 해제 → 레코드 파싱 → 텍스트 |
| `hwp_inspect.py` | 파일 구조 점검 (압축 여부·버전·섹션별 레코드 수) |
| `hwpedit.py` | 채우기 — `HwpDoc` 로 열고, 문단 텍스트를 바꾸고, 저장 |
| `cfb.py` | 저장용 최소 CFB(OLE2) 작성기 — HWP 컨테이너를 다시 만든다 |

## 사용법

```bash
python3 hwplib.py form.hwp          # 본문 텍스트 출력
python3 hwp_inspect.py form.hwp     # 구조 점검
```

```python
from hwpedit import HwpDoc

doc = HwpDoc("form.hwp")
sec = doc.sections["BodyText/Section0"]

for i, t in enumerate(sec.texts()):     # 문단 번호와 내용을 보고 채울 자리를 찾는다
    print(i, repr(t))

sec.set_text(12, "연구 목적: ...")       # 12번 문단 내용을 바꾼다
sec.drop_line_segs()                    # 한글이 열 때 줄 배치를 다시 계산하게
doc.save("form_filled.hwp")
```

저장한 파일은 **한글에서 한 번 열어 확인**한다.

## 제한

- HWP 5.x(바이너리) 전용. HWPX(`.hwpx`, XML)는 지원하지 않는다.
- 암호가 걸린 문서·배포용 문서는 처리하지 않는다(따로 검사하지 않으니 읽기·저장이 실패하거나 깨진다).
- 저장 파일의 FAT 섹터가 109개를 넘으면(대략 7 MB 이상) 지원하지 않는다.
