# plot-digitizer — 논문 그래프 이미지에서 수치 읽기

메타분석에서 논문이 수치를 표로 주지 않고 **막대그래프로만** 줄 때, 그림 픽셀을 재서 평균·오차막대 값을 뽑는다.
WebPlotDigitizer(WPD)로 손으로 찍던 작업을 스크립트로 바꾼 것이다.

방법: **PDF 고해상도 재렌더 → 축 눈금 선형 보정 → 막대·오차막대 픽셀 측정**.

> ⚠️ 이 도구의 출력은 **초안**이다. 결과 이미지(overlay)를 눈으로 확인하고, 최종값은 사람이 다시 확인한다.

## 필요한 것

```bash
pip install numpy pillow
brew install poppler      # pdftoppm (PDF → PNG)
```

## 사용 순서

```bash
pdftoppm -r 600 -f <쪽> -l <쪽> -png paper.pdf page   # 1. 그림이 있는 쪽을 600 dpi 로 렌더
python3 my_figure.py                                   # 2. 그림마다 짧은 스크립트를 쓴다 (아래 예시)
```

## 함수 (`dig.py`)

| 함수 | 하는 일 |
|---|---|
| `load(path)` | 이미지를 RGB 배열로 |
| `green_mask` · `color_mask(a, (r,g,b))` · `dark_mask` | 막대 색 / 검은 선(축·오차막대) 마스크 |
| `ticks_on_axis(dm, lo, hi)` | 축선 바깥 밴드에서 눈금 위치(행) 검출 |
| `calib(tick_rows, tick_vals)` | 눈금 위치 ↔ 값 선형 보정. `(변환함수, 기울기, 절편, 최대잔차)` 반환 — **잔차가 크면 눈금 배정이 틀린 것** |
| `clusters(idx, gap)` | 연속 픽셀 묶기 (막대 위치 찾기) |
| `bar_extent(gm, c0, c1)` | 막대가 칠해진 행 범위 |
| `caps(dm, cx, r_from, r_to)` | 오차막대 끝(cap) 행 검출 |
| `label_blobs(mask)` | 연결성분 라벨링 (점·기호 찾기) |

## 예시

```python
import numpy as np
from dig import *

a = load("page-5.png")[350:1900, 700:2600]          # 그림 영역만 자르기
gm, dm = color_mask(a, (60, 160, 80)), dark_mask(a)  # 막대 색, 검은 선

rows = ticks_on_axis(dm, 160, 186)                   # y축 눈금
V, slope, _, resid = calib(rows, [100, 80, 60, 40, 20, 0])
print(f"보정 잔차 {resid:.3f}")                        # 0 에 가까워야 한다

for c0, c1 in clusters(list(np.where(gm.any(axis=0))[0]), 30):   # 막대마다
    cx = (c0 + c1) // 2
    top = bar_extent(gm, c0, c1).min()               # 막대 꼭대기 = 평균
    cap = caps(dm, cx, top - 8, 60)                  # 위쪽 오차 cap
    sd = abs(top - sum(cap[-1]) / 2) * abs(slope) if cap else None
    print(f"mean {V(top):.2f}  SD {sd}")
```

결과 위치에 색선을 그린 overlay 이미지를 함께 저장해서 **반드시 눈으로 확인**한다. 판독 오류는 거의 전부 이 단계에서 잡혔다.

## 그림 유형별 주의점 (실제로 틀렸던 것들)

- **막대 테두리선 유무** — 테두리가 있으면 선 중심이 평균, 없으면 색이 끝나는 곳이 평균. 한 그림 안에 섞여 있기도 하다.
- **세로로 눕힌 유의성 문자** (`a`, `ab`) — 막대 폭을 채워서 막대 꼭대기로 잘못 읽힌다. 바닥에서 위로 연속 추적하면 해결된다.
- **막대 안쪽에 그려진 오차 cap** — 연속 추적이 거기서 끊긴다. 짧은 끊김(13행 이하)은 건너뛴다.
- **패널 전체를 가로지르는 `ns` 선** — 막대 폭만으로는 걸러지지 않는다. 막대 좌우 바깥이 배경색인지 함께 본다.
- **검출 범위 밖의 맨 위 눈금** — 눈금 값 배정이 한 칸 밀린다. 검출한 눈금 개수를 축 라벨 개수와 대조한다.
