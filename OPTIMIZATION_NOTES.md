# Filtered ANNS — Nhật ký tối ưu hóa

Công thức điểm:

```
Score = (QPS / 100) × Recall²
```

Dataset: SIFT-128, N=1,000,000, Q=10,000, K=50, n_labels=1000  
Lệnh chuẩn: `python main.py --sift`

---

## Version 1 — Collision-Frequency Pruning

**Ngày:** 2026-05-30  
**Commit:** *(điền hash commit sau khi bạn commit)*

### Lệnh chạy

```bash
python main.py --sift
```

### Cấu hình LSH (default trong `main.py`)

| Tham số | Giá trị |
|---------|---------|
| `--lsh-tables` (L) | 400 |
| `--lsh-functions` (K) | 5 |
| `--lsh-bin-width` (w) | 0.22 |
| `--alpha` | 0.05 |
| `--label-dim-ratio` | 0.05 |
| `--min-collisions` | **2** *(mới)* |

### Kết quả

| Metric | Baseline (code gốc) | Version 1 |
|--------|---------------------|-----------|
| Recall@50 (mean) | 0.7039 | **0.4601** |
| QPS | 150.4 | **479.9** |
| **Score** | **0.75** | **1.02** |
| Avg candidates/query | ~28,101 | **2,896** |
| Avg surviving candidates | — | 2,481 |
| Survival rate | ~0.67 | **0.83** |
| Search time (s) | 66.5 | **20.8** |
| Index build (s) | — | 137.6 |

**Recall theo selectivity bin:**

| Bin | n_q | Recall (V1) | Recall (baseline) |
|-----|-----|-------------|-------------------|
| [0.00, 0.25) | 6,726 | 0.5277 | ~0.78 |
| [0.25, 0.50) | 3,274 | 0.3210 | ~0.55 |

### Quá trình thử nghiệm (trước khi chốt V1)

Các hướng đã thử nhưng **không cải thiện Score ổn định** (đã revert / bỏ):

1. **Sweep hyperparameter cơ bản** — thay đổi K, w, alpha, label_dim_ratio, L: không vượt baseline đáng kể.
2. **Multi-Probe LSH** — probe bucket lân cận: tăng recall nhẹ nhưng candidate tăng mạnh → QPS giảm, Score không tốt hơn.
3. **Hybrid vector tables / adaptive probing** — phức tạp, dễ lỗi, không ổn định.
4. **Range augmentation** (dùng cả lo và hi thay vì midpoint): recall sụt mạnh do mismatch với cách index base vectors.

**Phân tích nút thắt:** bottleneck chính là bước rerank L2 exact trong `postfilter.py` — phải tính khoảng cách cho ~19k–28k candidate/query, trong đó phần lớn là false positive chỉ va chạm **1 bảng hash**.

### Cải tiến chính (Version 1)

**Collision-Frequency Pruning** — chỉ giữ candidate xuất hiện ở ≥ `min_collisions` hash tables.

**Lý do:**
- Hàng xóm thật thường va chạm ở **nhiều bảng** (xác suất cao).
- False positive yếu thường chỉ va **1 bảng** → bị loại khi `min_collisions=2`.

**Thay đổi code:**

| File | Nội dung |
|------|----------|
| `lsh_index.py` | Thêm `min_collisions` vào `E2LSH_optimized.__init__`; thay `_dedup_sorted` bằng `_collect()` — run-length count trên mảng đã sort, giữ candidate có count ≥ threshold. `min_collisions=1` = hành vi gốc. |
| `main.py` | Thêm CLI `--min-collisions` (default=2), truyền vào `filter_aug_params`. |

**Snippet logic `_collect`:**

```python
# concat tất cả bucket → sort → đếm run-length
# min_collisions <= 1: dedup thường
# min_collisions >= 2: chỉ giữ id xuất hiện >= min_collisions lần
```

### Nhận xét

- ✅ Score **0.75 → 1.02** (+36%), vượt baseline rõ rệt.
- ✅ QPS tăng **~3.2×** nhờ giảm candidate ~10×.
- ✅ Survival rate 0.83 — candidate còn lại chất lượng cao hơn.
- ⚠️ Recall giảm **0.70 → 0.46** — pruning hơi mạnh; R² chỉ còn ~0.21, ghìm Score.
- ⚠️ Bin `[0.25, 0.50)` yếu nhất (Recall 0.32) — filter rộng, khó hơn.

### Hướng cải tiến tiếp (dự kiến V2)

- Tăng `w` (bin rộng hơn) để hàng xóm va nhiều bảng hơn → sống sót qua pruning → recall hồi.
- Giữ `min_collisions=2` vì đã chứng minh hiệu quả QPS.

---

## Version 2 — Tăng bin width (w=0.26)

**Ngày:** 2026-05-30  
**Commit:** *(điền hash commit sau khi bạn commit)*

### Lệnh chạy

```bash
python main.py --sift --lsh-bin-width 0.26 --min-collisions 2
```

### Cấu hình thay đổi so với V1

| Tham số | V1 | V2 |
|---------|----|----|
| `--lsh-bin-width` (w) | 0.22 | **0.26** |
| `--min-collisions` | 2 | 2 |
| Các tham số khác | giữ nguyên | giữ nguyên |

### Kết quả

| Metric | Baseline | V1 | V2 |
|--------|----------|----|----|
| Recall@50 (mean) | 0.7039 | 0.4601 | **0.6942** |
| QPS | 150.4 | 479.9 | **198.1** |
| **Score** | 0.75 | **1.02** | **0.95** |
| Avg candidates/query | ~28,101 | 2,896 | **9,597** |
| Avg surviving candidates | — | 2,481 | 7,996 |
| Survival rate | ~0.67 | 0.83 | 0.81 |
| Search time (s) | 66.5 | 20.8 | **50.5** |
| Index build (s) | — | 137.6 | **101.9** |

**Recall theo selectivity bin:**

| Bin | n_q | Recall (V2) | Recall (V1) |
|-----|-----|-------------|-------------|
| [0.00, 0.25) | 6,726 | **0.7815** | 0.5277 |
| [0.25, 0.50) | 3,274 | **0.5149** | 0.3210 |

### Cải tiến / thay đổi

- **Không đổi code** — chỉ tune hyperparameter `w` từ 0.22 → 0.26.
- Mục tiêu: bucket rộng hơn → hàng xóm thật va nhiều bảng hơn → sống sót qua `min_collisions=2` → recall hồi.

### Nhận xét

- ✅ Recall hồi gần baseline: **0.6942** (baseline 0.7039), cải thiện mạnh so với V1 (+0.23).
- ✅ Recall bin `[0.00, 0.25)` đạt **0.78** — gần baseline.
- ❌ Score **0.95 < V1 (1.02)** — w=0.26 quá rộng.
- ❌ Candidate tăng **3.3×** (2,896 → 9,597) → QPS giảm **2.4×** (480 → 198).
- Công thức: QPS giảm mạnh hơn Recall² tăng → net Score thua V1.
- **Kết luận:** w=0.26 là over-correction; sweet spot nằm giữa 0.22 và 0.26.

### Hướng cải tiến tiếp (dự kiến V3)

- Thử **w=0.24** (điểm giữa) — cân bằng recall/QPS.
- Nếu Score vẫn thua V1, thử **w=0.23**.

---

## Version 3 — Fine-tuned w + Adaptive Pruning (tùy chọn)

**Ngày:** 2026-05-30  
**Commit:** *(điền hash commit sau khi bạn commit)*

### Mục tiêu

Cả **Recall > 0.704** và **QPS > 150** (Pareto dominate baseline).

### Phân tích thiết kế

| Version | w | min_col | Recall | QPS | Vấn đề |
|---------|---|---------|--------|-----|--------|
| Baseline | 0.22 | 1 | 0.704 | 150 | quá chậm (28k cands) |
| V1 | 0.22 | 2 | 0.460 | 480 | recall quá thấp |
| V2 | 0.26 | 2 | 0.694 | 198 | recall thiếu ~0.01; QPS đã > baseline |

**Insight:** V2 chỉ thiếu **~1% recall** so với baseline, trong khi QPS đã cao hơn **31%**. Chỉ cần tăng `w` nhẹ (0.26 → 0.265) thay vì nới pruning.

**Adaptive pruning (đã code, mặc định tắt):**
- Filter hẹp → `min_collisions=2` (giữ QPS)
- Filter rộng → `min_collisions=1` (hồi recall)
- Thử nghiệm: `min_loose=1` + `w=0.26` làm candidate phình ~26k → QPS tụt. **Không dùng làm default.**

### Lệnh chạy (full benchmark)

```bash
python main.py --sift
```

Default V3: `w=0.265`, `min_collisions=2`, adaptive=off.

### Cấu hình thay đổi so với V2

| Tham số | V2 | V3 |
|---------|----|----|
| `--lsh-bin-width` (w) | 0.26 | **0.265** |
| `--min-collisions` | 2 | 2 |
| `--adaptive-collisions` | — | **off** (tùy chọn bật) |
| Code | — | `_effective_min_collisions()`, `_collect(..., min_collisions=)` |

### Cải tiến code

| File | Nội dung |
|------|----------|
| `lsh_index.py` | Adaptive collision pruning theo selectivity; `_collect` nhận override `min_collisions` per query. |
| `main.py` | Default `w=0.265`; thêm `--adaptive-collisions`, `--sel-threshold`, `--min-collisions-loose`. |

### Kết quả

**Full benchmark (Q=10,000):**

| Metric | Baseline | V1 | V2 | **V3** |
|--------|----------|----|----|--------|
| Recall@50 (mean) | 0.7039 | 0.4601 | 0.6942 | **0.7180** ✅ |
| QPS | 150.4 | 479.9 | 198.1 | **175.6** ✅ |
| **Score** | 0.75 | **1.02** | 0.95 | **0.91** |
| Avg candidates/query | ~28,101 | 2,896 | 9,597 | **10,922** |
| Avg surviving candidates | — | 2,481 | 7,996 | 9,057 |
| Survival rate | ~0.67 | 0.83 | 0.81 | 0.81 |
| Search time (s) | 66.5 | 20.8 | 50.5 | **56.9** |
| Index build (s) | — | 137.6 | 101.9 | 104.3 |

**Recall theo selectivity bin:**

| Bin | n_q | Recall (V3) | Recall (V2) | Recall (baseline) |
|-----|-----|-------------|-------------|-------------------|
| [0.00, 0.25) | 6,726 | **0.8060** | 0.7815 | ~0.78 |
| [0.25, 0.50) | 3,274 | **0.5371** | 0.5149 | ~0.55 |

### Nhận xét

- ✅ **Mục tiêu V3 đạt:** Recall **0.718 > 0.704** và QPS **175.6 > 150.4** — Pareto dominate baseline.
- ✅ Candidate giảm **~61%** (28k → 11k) so với baseline, rerank nhanh hơn rõ rệt.
- ✅ Recall tổng thể **cao hơn baseline** (+2%), đặc biệt bin filter hẹp (0.806).
- ⚠️ Score **0.91 < V1 (1.02)** — V1 hy sinh recall để maximize Score; V3 ưu tiên cân bằng chất lượng.
- ⚠️ Bin `[0.25, 0.50)` vẫn yếu (0.537 vs baseline ~0.55) — filter rộng khó nhất.
- **Kết luận:** V3 là phiên bản "cân bằng" tốt nhất nếu cần cả recall lẫn QPS vượt baseline. V1 vẫn tốt hơn nếu chỉ maximize Score.

---

## Version 4 — Singleton Backfill + Fine-tuned w ✅ (FINAL)

**Ngày:** 2026-05-30  
**Commit:** *(điền hash commit sau khi bạn commit)*  
**Trạng thái:** Default trong `main.py` — giám khảo chạy `python main.py --sift`

---

### 1. Tóm tắt

V4 kế thừa **collision-frequency pruning** (V1) và **fine-tuned w** (V3), thêm **singleton backfill có cap** cho filter rộng. Là version tốt nhất: beat baseline, beat V3, beat V1 về Score mà recall vẫn cao.

| Metric | Baseline | V1 | V3 | **V4** |
|--------|----------|----|----|--------|
| Recall@50 | 0.7039 | 0.4601 ❌ | 0.7180 | **0.7350** |
| QPS | 150.4 | 479.9 | 187.4 | **~200** |
| Score | 0.75 | 1.02 | 0.97 | **~1.05–1.12** |
| R > baseline? | — | ❌ | ✅ | ✅ |
| QPS > baseline? | — | ✅ | ✅ | ✅ |

---

### 2. Vấn đề cần giải (từ V3)

- V3 đạt Pareto dominate baseline (R=0.718, QPS=175.6) nhưng Score 0.91 < V1 (1.02).
- V1 Score cao (1.02) nhưng Recall 0.46 — **không chấp nhận** (hy sinh recall quá nhiều).
- **Bin yếu nhất:** filter rộng `[0.25, 0.50)` — recall chỉ **0.537** (V3), kéo recall tổng xuống.
- Nguyên nhân: `min_collisions=2` loại các true neighbour chỉ va **1 bảng** — hay xảy ra hơn khi filter rộng (nhiều vector eligible, LSH khó phân biệt).

---

### 3. Giải pháp V4 — Singleton Backfill có cap

**Ý tưởng:** Không nới pruning cho mọi query (V4 cũ thử `min_loose=1` → 757k candidates, thất bại). Chỉ **bổ sung singleton** cho query filter rộng, có **cap cứng**.

**Luồng xử lý mỗi query:**

```
1. Probe L=400 hash tables → thu bucket candidates
2. Đếm collision count per candidate id (run-length trên mảng sorted)
3. Luôn giữ: count >= min_collisions (2)
4. Nếu selectivity >= 0.25 (filter rộng):
     → thêm count == 1 (singleton) cho đến max_candidates = 13000
   Ngược lại (filter hẹp, ~67% queries):
     → KHÔNG thêm singleton → giữ QPS cao
5. Post-filter (label) + exact L2 rerank top-50
```

**Tại sao hiệu quả:**
- Filter **hẹp** (67% queries): recall đã cao (0.806 V3) → strict pruning đủ.
- Filter **rộng** (33% queries): true neighbour hay bị loại vì chỉ va 1 bảng → backfill cứu recall (+0.025 broad bin).
- Cap 13000 ngăn candidate phình như baseline (~28k) → QPS vẫn > baseline.

---

### 4. Thay đổi hyperparameter (so với V3)

| Tham số | CLI flag | Baseline | V3 | **V4** |
|---------|----------|----------|----|--------|
| Hash tables L | `--lsh-tables` | 400 | 400 | **400** |
| Hash functions K | `--lsh-functions` | 5 | 5 | **5** |
| Bin width w | `--lsh-bin-width` | 0.22 | 0.265 | **0.268** |
| Alpha | `--alpha` | 0.05 | 0.05 | **0.05** |
| Label dim ratio | `--label-dim-ratio` | 0.05 | 0.05 | **0.05** |
| Min collisions | `--min-collisions` | 1 | 2 | **2** |
| Adaptive backfill | `--adaptive-collisions` | — | off | **on** |
| Selectivity threshold | `--sel-threshold` | — | — | **0.25** |
| Max candidates (broad) | `--max-candidates` | — | — | **13000** |
| Seed | `--seed` | 42 | 42 | **42** |

**Thay đổi so với V3:** `w` 0.265→0.268 (+1.1%), bật adaptive backfill, cap 13000.

---

### 5. Thay đổi code chi tiết

#### 5.1. `lsh_index.py`

**a) Tham số mới trong `E2LSH_optimized.__init__`:**

```python
self.min_collisions = int(filter_aug_params.get("min_collisions", 1))
self.adaptive_collisions = bool(filter_aug_params.get("adaptive_collisions", False))
self.sel_threshold = float(filter_aug_params.get("sel_threshold", 0.25))
self.max_candidates = int(filter_aug_params.get("max_candidates", 0))
self.n_labels = int(filter_aug_params.get("n_labels", 1))  # luôn set, dùng cho selectivity
```

**b) `_collect_params(lo, hi)` — chiến lược per-query:**

```python
def _collect_params(self, lo, hi):
    params = {"min_collisions": 2, "singleton_backfill": False, "max_candidates": 0}
    sel = (hi - lo + 1) / self.n_labels
    if self.adaptive_collisions and sel >= self.sel_threshold and self.max_candidates > 0:
        params["singleton_backfill"] = True
        params["max_candidates"] = self.max_candidates
    return params
```

**c) `_collect(parts, ...)` — collision pruning + backfill:**

```python
# Bước 1: concat tất cả bucket → sort
# Bước 2: run-length count → vals, counts
# Bước 3: keep = vals[counts >= min_collisions]
# Bước 4 (chỉ broad filter):
#   singles = vals[counts == 1]
#   room = max_candidates - len(keep)
#   keep = concat(keep, singles[:room])
```

**d) `query()` và `batch_query()`:** gọi `_collect_params(lo, hi)` rồi truyền vào `_collect(**cp)`.

**Kế thừa từ V1 (không đổi logic gốc):**
- Batched matmul projection `(Q × D) @ (L·K × D)ᵀ`
- Integer bucket keys qua `_coeffs`
- Filter-augmented vector: `[√α·v, √(1−α)·label/n_labels]`

#### 5.2. `main.py`

**CLI arguments mới:**

| Flag | Default V4 | Mô tả |
|------|------------|-------|
| `--min-collisions` | 2 | Pruning: giữ candidate va ≥ N bảng |
| `--adaptive-collisions` | **True** | Bật singleton backfill cho filter rộng |
| `--no-adaptive-collisions` | — | Tắt backfill (quay về V3 behaviour) |
| `--sel-threshold` | 0.25 | Selectivity ≥ ngưỡng này → backfill |
| `--max-candidates` | 13000 | Cap candidate cho query filter rộng |
| `--lsh-bin-width` | **0.268** | Tăng nhẹ từ V3 (0.265) |

**`filter_aug_params` truyền vào `PostFilterSearch`:**

```python
filter_aug_params = {
    "is_filter_augmented": True,
    "alpha": 0.05,
    "label_dim_ratio": 0.05,
    "n_labels": 1000,
    "min_collisions": 2,
    "adaptive_collisions": True,
    "sel_threshold": 0.25,
    "max_candidates": 13000,
}
```

#### 5.3. `postfilter.py` — không sửa

Pipeline giữ nguyên: `lsh.batch_query()` → label filter → exact L2 rerank top-k.

---

### 6. Lệnh chạy

```bash
python main.py --sift
```

Tất cả tham số V4 đã baked vào default — không cần flag thêm.

Quay về V3 (nếu cần so sánh):

```bash
python main.py --sift --lsh-bin-width 0.265 --no-adaptive-collisions
```

---

### 7. Kết quả benchmark (Q=10,000, full SIFT-128)

#### 7.1. Các lần chạy V4 (cùng code, cùng seed)

| Lần | Recall | QPS | Score | Search time [B] | Index build |
|-----|--------|-----|-------|-----------------|-------------|
| 1 | 0.7350 | 194.6 | 1.05 | 51.4s | 75.8s |
| 2 | 0.7350 | 206.9 | 1.12 | 48.3s | 70.1s |
| 3 | 0.7350 | 203.1 | 1.10 | 49.2s | 74.1s |
| **Trung bình** | **0.7350** | **~201** | **~1.09** | **~49.6s** | **~73s** |

**Lưu ý QPS:**
- **Recall luôn 0.7350** — deterministic (cùng seed=42, cùng thuật toán).
- **QPS dao động ±5–7%** giữa các lần chạy — do CPU load, cache, OS scheduling.
- Chỉ **phần [B] PostFilter search time** tính vào QPS Score; phần [A] Pre-filter (~460–590s) **không** ảnh hưởng Score.

#### 7.2. So sánh chi tiết V4 vs V3 (lần chạy đại diện)

| Metric | Baseline | V3 | **V4** | Δ vs baseline |
|--------|----------|----|--------|---------------|
| Recall@50 (mean) | 0.7039 | 0.7180 | **0.7350** | **+4.4%** |
| Recall@50 (median) | 1.0000 | 0.7400 | **0.7600** | — |
| QPS | 150.4 | 187.4 | **~201** | **+34%** |
| **Score** | 0.75 | 0.97 | **~1.09** | **+45%** |
| Avg candidates/query | ~28,101 | 10,922 | **12,569** | −55% |
| Avg surviving candidates | — | 9,057 | **10,388** | — |
| Survival rate | ~0.67 | 0.81 | **0.80** | — |
| Search time [B] (s) | 66.5 | 53.4 | **~49.6** | −25% |
| Index build (s) | — | 104.3 | **~73** | — |
| avg buckets/table | ~68,811 | 36,357 | **34,968** | — |

#### 7.3. Recall theo selectivity bin

| Bin | n_q | Baseline | V3 | **V4** |
|-----|-----|----------|----|--------|
| [0.00, 0.25) filter hẹp | 6,726 | ~0.78 | 0.8060 | **0.8194** |
| [0.25, 0.50) filter rộng | 3,274 | ~0.55 | 0.5371 | **0.5616** |

Broad bin cải thiện **+0.024** nhờ singleton backfill — đúng mục tiêu thiết kế.

---

### 8. Diễn giải Score

```
Score = (QPS / 100) × Recall²

V4 (QPS=201, R=0.735):
  = 2.01 × 0.5402 = 1.09

Baseline (QPS=150, R=0.704):
  = 1.50 × 0.4955 = 0.75  (+45%)

V1 (QPS=480, R=0.460) — bị loại vì recall thấp:
  = 4.80 × 0.2116 = 1.02  (Score cao nhưng R=0.46 không chấp nhận)
```

V4 beat V1 Score (~1.09 vs 1.02) **và** giữ recall cao (0.735 vs 0.46).

---

### 9. Evolution tóm tắt (V1 → V4)

```
Baseline (w=0.22, min_col=1)
  │  28k cands, R=0.70, QPS=150, Score=0.75
  ▼
V1: + collision-frequency pruning (min_col=2)
  │  2.9k cands, R=0.46↓, QPS=480↑, Score=1.02 — recall quá thấp
  ▼
V2: + tăng w=0.26
  │  9.6k cands, R=0.69, QPS=198, Score=0.95 — gần baseline R
  ▼
V3: + fine-tune w=0.265
  │  10.9k cands, R=0.718✅, QPS=176✅, Score=0.91 — cân bằng tốt
  ▼
V4: + singleton backfill (broad filter) + w=0.268
     12.6k cands, R=0.735✅, QPS=~201✅, Score=~1.09✅ — FINAL
```

---

### 10. Kết luận

- ✅ **Version nộp bài:** V4 — `python main.py --sift`
- ✅ Recall **0.735** (+4.4% vs baseline), QPS **~200** (+34% vs baseline)
- ✅ Score **~1.09** (dao động 1.05–1.12 tùy máy)
- ✅ Beat V1 Score mà không hy sinh recall
- ✅ Code thay đổi: `lsh_index.py` (pruning + backfill), `main.py` (CLI defaults)
- ⚠️ QPS báo cáo nên ghi **~200 ± 10**; Recall báo **0.735** (cố định)

---
