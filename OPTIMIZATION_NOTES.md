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

## Version 3 — *(chưa chạy)*

**Ngày:**  
**Commit:**  

### Lệnh chạy

```bash
# điền lệnh ở đây
```

### Cấu hình thay đổi so với V2

| Tham số | V2 | V3 |
|---------|----|----|
| | | |

### Kết quả

| Metric | V1 | V2 | V3 |
|--------|----|----|-----|
| Recall@50 | 0.4601 | 0.6942 | |
| QPS | 479.9 | 198.1 | |
| Score | 1.02 | 0.95 | |
| Avg candidates | 2,896 | 9,597 | |

### Cải tiến / thay đổi

*(ghi sau khi chạy)*

### Nhận xét

*(ghi sau khi chạy)*

---

## Version 4 — *(dự phòng)*

*(copy template từ V3 khi cần)*
