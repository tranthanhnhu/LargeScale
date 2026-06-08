# Filtered ANNS — Optimization Log

Score formula:

```
Score = (QPS / 100) × Recall²
```

Dataset: SIFT-128, N=1,000,000, Q=10,000, K=50, n_labels=1000  
Standard command: `python main.py --sift`

---

## Version 1 — Collision-Frequency Pruning

**Date:** 2026-05-30  
**Commit:** *(fill in commit hash after you commit)*

### Run command

```bash
python main.py --sift
```

### LSH configuration (default in `main.py` at the time)

| Parameter | Value |
|-----------|-------|
| `--lsh-tables` (L) | 400 |
| `--lsh-functions` (K) | 5 |
| `--lsh-bin-width` (w) | 0.22 |
| `--alpha` | 0.05 |
| `--label-dim-ratio` | 0.05 |
| `--min-collisions` | **2** *(new)* |

### Results

| Metric | Baseline (original code) | Version 1 |
|--------|--------------------------|-----------|
| Recall@50 (mean) | 0.7039 | **0.4601** |
| QPS | 150.4 | **479.9** |
| **Score** | **0.75** | **1.02** |
| Avg candidates/query | ~28,101 | **2,896** |
| Avg surviving candidates | — | 2,481 |
| Survival rate | ~0.67 | **0.83** |
| Search time (s) | 66.5 | **20.8** |
| Index build (s) | — | 137.6 |

**Recall by selectivity bin:**

| Bin | n_q | Recall (V1) | Recall (baseline) |
|-----|-----|-------------|-------------------|
| [0.00, 0.25) | 6,726 | 0.5277 | ~0.78 |
| [0.25, 0.50) | 3,274 | 0.3210 | ~0.55 |

### Experiments before finalizing V1

Approaches tried but **did not improve Score reliably** (reverted / dropped):

1. **Basic hyperparameter sweep** — varying K, w, alpha, label_dim_ratio, L: no significant gain over baseline.
2. **Multi-Probe LSH** — probing neighboring buckets: slight recall gain but candidate count exploded → QPS dropped, Score not better.
3. **Hybrid vector tables / adaptive probing** — complex, error-prone, unstable.
4. **Range augmentation** (using both lo and hi instead of midpoint): recall collapsed due to mismatch with how base vectors are indexed.

**Bottleneck analysis:** the main bottleneck is exact L2 reranking in `postfilter.py` — computing distances for ~19k–28k candidates/query, most of which are weak false positives colliding in only **one** hash table.

### Main improvement (Version 1)

**Collision-Frequency Pruning** — keep only candidates appearing in ≥ `min_collisions` hash tables.

**Rationale:**
- True neighbors usually collide in **many tables** (high probability).
- Weak false positives usually collide in only **one table** → removed when `min_collisions=2`.

**Code changes:**

| File | Change |
|------|--------|
| `lsh_index.py` | Add `min_collisions` to `E2LSH_optimized.__init__`; replace `_dedup_sorted` with `_collect()` — run-length count on sorted array, keep candidates with count ≥ threshold. `min_collisions=1` restores original behavior. |
| `main.py` | Add CLI `--min-collisions` (default=2), pass into `filter_aug_params`. |

**`_collect` logic snippet:**

```python
# concat all buckets → sort → run-length count
# min_collisions <= 1: standard dedup
# min_collisions >= 2: keep only ids appearing >= min_collisions times
```

### Notes

- ✅ Score **0.75 → 1.02** (+36%), clearly above baseline.
- ✅ QPS up **~3.2×** thanks to ~10× fewer candidates.
- ✅ Survival rate 0.83 — remaining candidates are higher quality.
- ⚠️ Recall dropped **0.70 → 0.46** — pruning too aggressive; R² only ~0.21, limiting Score upside.
- ⚠️ Weakest bin `[0.25, 0.50)` (Recall 0.32) — broad filters are harder.

### Next steps (planned V2)

- Increase `w` (wider bins) so neighbors collide in more tables → survive pruning → recall recovers.
- Keep `min_collisions=2` since it proved effective for QPS.

---

## Version 2 — Increase bin width (w=0.26)

**Date:** 2026-05-30  
**Commit:** *(fill in commit hash after you commit)*

### Run command

```bash
python main.py --sift --lsh-bin-width 0.26 --min-collisions 2
```

### Configuration changes vs V1

| Parameter | V1 | V2 |
|-----------|----|----|
| `--lsh-bin-width` (w) | 0.22 | **0.26** |
| `--min-collisions` | 2 | 2 |
| Other parameters | unchanged | unchanged |

### Results

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

**Recall by selectivity bin:**

| Bin | n_q | Recall (V2) | Recall (V1) |
|-----|-----|-------------|-------------|
| [0.00, 0.25) | 6,726 | **0.7815** | 0.5277 |
| [0.25, 0.50) | 3,274 | **0.5149** | 0.3210 |

### Changes

- **No code changes** — only tuned hyperparameter `w` from 0.22 → 0.26.
- Goal: wider buckets → true neighbors collide in more tables → survive `min_collisions=2` → recall recovers.

### Notes

- ✅ Recall recovered near baseline: **0.6942** (baseline 0.7039), strong improvement over V1 (+0.23).
- ✅ Recall bin `[0.00, 0.25)` reached **0.78** — close to baseline.
- ❌ Score **0.95 < V1 (1.02)** — w=0.26 too wide.
- ❌ Candidates up **3.3×** (2,896 → 9,597) → QPS down **2.4×** (480 → 198).
- Formula: QPS drop outweighed Recall² gain → net Score below V1.
- **Conclusion:** w=0.26 was over-correction; sweet spot lies between 0.22 and 0.26.

### Next steps (planned V3)

- Try **w=0.24** (midpoint) — balance recall/QPS.
- If Score still below V1, try **w=0.23**.

---

## Version 3 — Fine-tuned w + Adaptive Pruning (optional)

**Date:** 2026-05-30  
**Commit:** *(fill in commit hash after you commit)*

### Goal

Both **Recall > 0.704** and **QPS > 150** (Pareto dominate baseline).

### Design analysis

| Version | w | min_col | Recall | QPS | Issue |
|---------|---|---------|--------|-----|-------|
| Baseline | 0.22 | 1 | 0.704 | 150 | too slow (28k cands) |
| V1 | 0.22 | 2 | 0.460 | 480 | recall too low |
| V2 | 0.26 | 2 | 0.694 | 198 | recall ~0.01 short; QPS already > baseline |

**Insight:** V2 was only **~1% recall** below baseline while QPS was **31%** higher. A small `w` bump (0.26 → 0.265) was enough instead of loosening pruning.

**Adaptive pruning (coded, off by default):**
- Narrow filter → `min_collisions=2` (keep QPS)
- Broad filter → `min_collisions=1` (recover recall)
- Experiment: `min_loose=1` + `w=0.26` inflated candidates to ~26k → QPS collapsed. **Not used as default.**

### Run command (full benchmark)

```bash
python main.py --sift
```

V3 defaults: `w=0.265`, `min_collisions=2`, adaptive=off.

### Configuration changes vs V2

| Parameter | V2 | V3 |
|-----------|----|----|
| `--lsh-bin-width` (w) | 0.26 | **0.265** |
| `--min-collisions` | 2 | 2 |
| `--adaptive-collisions` | — | **off** (optional) |
| Code | — | `_effective_min_collisions()`, `_collect(..., min_collisions=)` |

### Code changes

| File | Change |
|------|--------|
| `lsh_index.py` | Selectivity-adaptive collision pruning; `_collect` accepts per-query `min_collisions` override. |
| `main.py` | Default `w=0.265`; add `--adaptive-collisions`, `--sel-threshold`, `--min-collisions-loose`. |

### Results

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

**Recall by selectivity bin:**

| Bin | n_q | Recall (V3) | Recall (V2) | Recall (baseline) |
|-----|-----|-------------|-------------|-------------------|
| [0.00, 0.25) | 6,726 | **0.8060** | 0.7815 | ~0.78 |
| [0.25, 0.50) | 3,274 | **0.5371** | 0.5149 | ~0.55 |

### Notes

- ✅ **V3 goal met:** Recall **0.718 > 0.704** and QPS **175.6 > 150.4** — Pareto dominate baseline.
- ✅ Candidates down **~61%** (28k → 11k) vs baseline, much faster rerank.
- ✅ Overall recall **above baseline** (+2%), especially narrow-filter bin (0.806).
- ⚠️ Score **0.91 < V1 (1.02)** — V1 sacrifices recall to maximize Score; V3 prioritizes quality balance.
- ⚠️ Bin `[0.25, 0.50)` still weak (0.537 vs baseline ~0.55) — broad filters are hardest.
- **Conclusion:** V3 was the best "balanced" version if both recall and QPS must beat baseline. V1 still wins if only maximizing Score.

---

## Version 4 — Singleton Backfill + Fine-tuned w ✅ (FINAL)

**Date:** 2026-05-30  
**Commit:** *(fill in commit hash after you commit)*  
**Status:** Default in `main.py` — graders run `python main.py --sift`

---

### 1. Summary

V4 builds on **collision-frequency pruning** (V1) and **fine-tuned w** (V3), adding **capped singleton backfill** for broad filters. Best overall version: beats baseline, beats V3, beats V1 on Score while keeping recall high.

| Metric | Baseline | V1 | V3 | **V4** |
|--------|----------|----|----|--------|
| Recall@50 | 0.7039 | 0.4601 ❌ | 0.7180 | **0.7350** |
| QPS | 150.4 | 479.9 | 187.4 | **~200** |
| Score | 0.75 | 1.02 | 0.97 | **~1.05–1.12** |
| R > baseline? | — | ❌ | ✅ | ✅ |
| QPS > baseline? | — | ✅ | ✅ | ✅ |

---

### 2. Problem to solve (from V3)

- V3 Pareto-dominated baseline (R=0.718, QPS=175.6) but Score 0.91 < V1 (1.02).
- V1 Score high (1.02) but Recall 0.46 — **not acceptable** (too much recall sacrifice).
- **Weakest bin:** broad filter `[0.25, 0.50)` — recall only **0.537** (V3), pulling down overall recall.
- Cause: `min_collisions=2` drops true neighbors that collide in only **one table** — more common with broad filters (many eligible vectors, LSH harder to discriminate).

---

### 3. V4 solution — Capped singleton backfill

**Idea:** Do not loosen pruning for every query (earlier attempt with `min_loose=1` → 757k candidates, failed). Only **backfill singletons** for broad-filter queries, with a **hard cap**.

**Per-query pipeline:**

```
1. Probe L=400 hash tables → collect bucket candidates
2. Count collisions per candidate id (run-length on sorted array)
3. Always keep: count >= min_collisions (2)
4. If selectivity >= 0.25 (broad filter):
     → add count == 1 (singletons) up to max_candidates = 13000
   Else (narrow filter, ~67% of queries):
     → do NOT add singletons → keep QPS high
5. Post-filter (label) + exact L2 rerank top-50
```

**Why it works:**
- **Narrow** filters (67% of queries): recall already high (0.806 in V3) → strict pruning is enough.
- **Broad** filters (33% of queries): true neighbors often dropped (only 1-table collision) → backfill recovers recall (+0.025 broad bin).
- Cap 13000 prevents candidate explosion like baseline (~28k) → QPS stays above baseline.

---

### 4. Hyperparameter changes (vs V3)

| Parameter | CLI flag | Baseline | V3 | **V4** |
|-----------|----------|----------|----|--------|
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

**Changes vs V3:** `w` 0.265→0.268 (+1.1%), enable adaptive backfill, cap 13000.

---

### 5. Detailed code changes

#### 5.1. `lsh_index.py`

**a) New parameters in `E2LSH_optimized.__init__`:**

```python
self.min_collisions = int(filter_aug_params.get("min_collisions", 1))
self.adaptive_collisions = bool(filter_aug_params.get("adaptive_collisions", False))
self.sel_threshold = float(filter_aug_params.get("sel_threshold", 0.25))
self.max_candidates = int(filter_aug_params.get("max_candidates", 0))
self.n_labels = int(filter_aug_params.get("n_labels", 1))  # always set, used for selectivity
```

**b) `_collect_params(lo, hi)` — per-query strategy:**

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
# Step 1: concat all buckets → sort
# Step 2: run-length count → vals, counts
# Step 3: keep = vals[counts >= min_collisions]
# Step 4 (broad filter only):
#   singles = vals[counts == 1]
#   room = max_candidates - len(keep)
#   keep = concat(keep, singles[:room])
```

**d) `query()` and `batch_query()`:** call `_collect_params(lo, hi)` then pass into `_collect(**cp)`.

**Inherited from V1 (core logic unchanged):**
- Batched matmul projection `(Q × D) @ (L·K × D)ᵀ`
- Integer bucket keys via `_coeffs`
- Filter-augmented vector: `[√α·v, √(1−α)·label/n_labels]`

#### 5.2. `main.py`

**New CLI arguments:**

| Flag | V4 default | Description |
|------|------------|-------------|
| `--min-collisions` | 2 | Pruning: keep candidates colliding in ≥ N tables |
| `--adaptive-collisions` | **True** | Enable singleton backfill for broad filters |
| `--no-adaptive-collisions` | — | Disable backfill (revert to V3 behavior) |
| `--sel-threshold` | 0.25 | Selectivity ≥ this triggers backfill |
| `--max-candidates` | 13000 | Candidate cap for broad-filter queries |
| `--lsh-bin-width` | **0.268** | Slight increase from V3 (0.265) |

**`filter_aug_params` passed to `PostFilterSearch`:**

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

#### 5.3. `postfilter.py` — unchanged

Pipeline unchanged: `lsh.batch_query()` → label filter → exact L2 rerank top-k.

---

### 6. Run commands

```bash
python main.py --sift
```

All V4 parameters are baked into defaults — no extra flags needed.

Revert to V3 (for comparison):

```bash
python main.py --sift --lsh-bin-width 0.265 --no-adaptive-collisions
```

---

### 7. Benchmark results (Q=10,000, full SIFT-128)

#### 7.1. Multiple V4 runs (same code, same seed)

| Run | Recall | QPS | Score | Search time [B] | Index build |
|-----|--------|-----|-------|-------------------|-------------|
| 1 | 0.7350 | 194.6 | 1.05 | 51.4s | 75.8s |
| 2 | 0.7350 | 206.9 | 1.12 | 48.3s | 70.1s |
| 3 | 0.7350 | 203.1 | 1.10 | 49.2s | 74.1s |
| **Average** | **0.7350** | **~201** | **~1.09** | **~49.6s** | **~73s** |

**QPS notes:**
- **Recall is always 0.7350** — deterministic (same seed=42, same algorithm).
- **QPS varies ±5–7%** between runs — due to CPU load, cache, OS scheduling.
- Only **[B] PostFilter search time** counts toward reported QPS/Score; [A] Pre-filter (~460–590s) does **not** affect Score.

#### 7.2. Detailed comparison V4 vs V3 (representative run)

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

#### 7.3. Recall by selectivity bin

| Bin | n_q | Baseline | V3 | **V4** |
|-----|-----|----------|----|--------|
| [0.00, 0.25) narrow filter | 6,726 | ~0.78 | 0.8060 | **0.8194** |
| [0.25, 0.50) broad filter | 3,274 | ~0.55 | 0.5371 | **0.5616** |

Broad bin improved **+0.024** via singleton backfill — matches design goal.

---

### 8. Score breakdown

```
Score = (QPS / 100) × Recall²

V4 (QPS=201, R=0.735):
  = 2.01 × 0.5402 = 1.09

Baseline (QPS=150, R=0.704):
  = 1.50 × 0.4955 = 0.75  (+45%)

V1 (QPS=480, R=0.460) — rejected due to low recall:
  = 4.80 × 0.2116 = 1.02  (high Score but R=0.46 not acceptable)
```

V4 beats V1 Score (~1.09 vs 1.02) **and** keeps recall high (0.735 vs 0.46).

---

### 9. Evolution summary (V1 → V4)

```
Baseline (w=0.22, min_col=1)
  │  28k cands, R=0.70, QPS=150, Score=0.75
  ▼
V1: + collision-frequency pruning (min_col=2)
  │  2.9k cands, R=0.46↓, QPS=480↑, Score=1.02 — recall too low
  ▼
V2: + increase w=0.26
  │  9.6k cands, R=0.69, QPS=198, Score=0.95 — near baseline R
  ▼
V3: + fine-tune w=0.265
  │  10.9k cands, R=0.718✅, QPS=176✅, Score=0.91 — good balance
  ▼
V4: + singleton backfill (broad filter) + w=0.268
     12.6k cands, R=0.735✅, QPS=~201✅, Score=~1.09✅ — FINAL
```

---

### 10. Conclusion

- ✅ **Submission version:** V4 — `python main.py --sift`
- ✅ Recall **0.735** (+4.4% vs baseline), QPS **~200** (+34% vs baseline)
- ✅ Score **~1.09** (varies 1.05–1.12 depending on machine)
- ✅ Beats V1 Score without sacrificing recall
- ✅ Code changes: `lsh_index.py` (pruning + backfill), `main.py` (CLI defaults)
- ⚠️ Report QPS as **~200 ± 10**; report Recall as **0.735** (fixed)

---
