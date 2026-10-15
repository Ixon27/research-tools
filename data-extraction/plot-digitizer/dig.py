"""공용 픽셀 판독 유틸 (WPD 대체) — 축 눈금 보정 + 막대/오차막대 픽셀 측정"""
import numpy as np
from PIL import Image

def load(path):
    return np.asarray(Image.open(path).convert('RGB')).astype(int)

def green_mask(a, gmin=90, d=50):
    r,g,b = a[...,0],a[...,1],a[...,2]
    return (g>gmin)&(g-r>d)&(g-b>d)

def color_mask(a, target, tol=60):
    return (np.abs(a - np.array(target)).sum(axis=2) < tol*3)

def dark_mask(a, thr=110):
    return a.max(axis=2) < thr

def clusters(idx, gap=4):
    out=[]
    for v in idx:
        if out and v-out[-1][-1] <= gap: out[-1].append(v)
        else: out.append([v])
    return [(c[0], c[-1]) for c in out]

def ticks_on_axis(dm, ax_lo, ax_hi, frac=0.6, gap=4):
    """축선 바깥 밴드[ax_lo:ax_hi]에서 눈금 행 검출"""
    band = dm[:, ax_lo:ax_hi]
    w = ax_hi-ax_lo
    rows = np.where(band.sum(axis=1) >= w*frac)[0]
    return [ (lo+hi)/2 for lo,hi in clusters(list(rows), gap) ]

def calib(tick_rows, tick_vals):
    tr = np.array(tick_rows, float); tv = np.array(tick_vals, float)
    slope, inter = np.polyfit(tr, tv, 1)
    resid = np.abs(slope*tr+inter - tv).max()
    return (lambda r: slope*r+inter), slope, inter, resid

def run_width(rowmask, cx):
    """rowmask(1D bool)에서 cx를 포함하는 연속 True 구간 길이"""
    if not rowmask[cx]: return 0
    l = cx
    while l>0 and rowmask[l-1]: l-=1
    r = cx
    while r<len(rowmask)-1 and rowmask[r+1]: r+=1
    return r-l+1

def caps(dm, cx, r_from, r_to, wmin=12, wmax=90, gap=4):
    """세로 오차선 위/아래 cap(가로 짧은 선) 행 검출"""
    step = 1 if r_to>r_from else -1
    hits=[]
    for r in range(r_from, r_to, step):
        w = run_width(dm[r], cx)
        if wmin <= w <= wmax: hits.append(r)
    hits.sort()
    return clusters(hits, gap)

def bar_extent(gm, c0, c1, inset=15, frac=0.6):
    core = gm[:, c0+inset:c1-inset]
    need = (c1-c0-2*inset)*frac
    rows = np.where(core.sum(axis=1) >= need)[0]
    return rows

def label_blobs(mask):
    """단순 BFS 연결성분 라벨링 → [(rows,cols)] 리스트"""
    from collections import deque
    m = mask.copy(); H,W = m.shape; out=[]
    for i in range(H):
        js = np.where(m[i])[0]
        for j in js:
            if not m[i,j]: continue
            q=deque([(i,j)]); m[i,j]=False; pix=[]
            while q:
                y,x=q.popleft(); pix.append((y,x))
                for dy,dx in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                    ny,nx=y+dy,x+dx
                    if 0<=ny<H and 0<=nx<W and m[ny,nx]:
                        m[ny,nx]=False; q.append((ny,nx))
            out.append(pix)
    return out
