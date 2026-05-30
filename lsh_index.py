"""
lsh_index.py  (optimised)
=========================
Filter-augmented E2LSH for Euclidean distance.

Optimisations (unchanged from baseline):
  1. Single batched matmul for all L tables / K functions.
  2. Integer bucket keys via random linear hash (no tuple allocation).
  3. Concat + sort + diff deduplication (cache-friendly int32 radix sort).

New principled improvement — COLLISION-FREQUENCY PRUNING
--------------------------------------------------------
The query bottleneck downstream (postfilter._filter_and_rerank) is the exact
L2 rerank over every surviving candidate (~19k/query in the baseline). Most of
those candidates are weak: they collided with the query in only ONE of the L
hash tables. A genuine near neighbour, by contrast, collides in MANY tables
(its per-table collision probability p(d)^K is high). By keeping only the
candidates that appear in at least `min_collisions` tables we discard the
low-quality singletons, shrinking the rerank set sharply (higher QPS) while
retaining the true neighbours (recall preserved). `min_collisions = 1`
reproduces the original behaviour exactly.

Optional — SELECTIVITY-ADAPTIVE PRUNING
---------------------------------------
Broad-filter queries (selectivity >= sel_threshold) can use a looser
min_collisions_loose value. Disabled by default: min_loose=1 at wide w
inflates candidates and hurts QPS. Enable via --adaptive-collisions.
"""

from math import sqrt

import numpy as np

np.set_printoptions(threshold=200)


class E2LSH_optimized:
    """
    Multi-table filter-augmented E2LSH index.

    Parameters
    ----------
    n_tables    : L - number of independent hash tables
    n_functions : K - hash functions concatenated per compound key
    dim         : vector dimensionality D
    bin_width   : w - projection slab width (main recall tuning knob)
    seed        : random seed

    filter_aug_params (optional):
        is_filter_augmented : bool   - enable inline filter augmentation
        alpha               : float  - vector weight in the augmented vector
        label_dim_ratio     : float  - fraction of dim used for the label block
        n_labels            : int    - number of distinct label values
        min_collisions      : int    - keep only candidates seen in >= this many
                                       tables (1 = original union, no pruning)
        adaptive_collisions : bool   - per-query threshold from filter selectivity
        sel_threshold       : float  - selectivity >= this uses min_collisions_loose
        min_collisions_loose: int    - pruning level for broad-filter queries
    """

    def __init__(self,
                 n_tables: int    = 15,
                 n_functions: int = 2,
                 dim: int          = 128,
                 bin_width: float  = 0.5,
                 seed: int         = 42,
                 **filter_aug_params):

        self.n_tables    = n_tables
        self.n_functions = n_functions
        self.dim         = dim
        self.w           = bin_width
        self.N           = 0

        # filter-augmented params
        self._is_filter_aug = filter_aug_params.get("is_filter_augmented")
        self.n_labels = int(filter_aug_params.get("n_labels", 1))
        self.label_dim = int(filter_aug_params.get("label_dim_ratio") * dim)
        aug_dim = dim + self.label_dim if self._is_filter_aug else dim
        if self._is_filter_aug:
            alpha = filter_aug_params.get("alpha")
            self._sqrt_alpha = sqrt(alpha)
            self._sqrt_1_alpha = sqrt(1 - alpha)

        # candidate pruning: keep candidates colliding in >= min_collisions tables
        self.min_collisions = int(filter_aug_params.get("min_collisions", 1))
        self.adaptive_collisions = bool(
            filter_aug_params.get("adaptive_collisions", False))
        self.sel_threshold = float(filter_aug_params.get("sel_threshold", 0.25))
        self.min_collisions_loose = int(
            filter_aug_params.get("min_collisions_loose", 1))

        rng = np.random.default_rng(seed)

        # Random projection matrix: (L, K, aug_dim)
        self.A = rng.standard_normal(
            (n_tables, n_functions, aug_dim)).astype(np.float32)
        self.b = rng.uniform(
            0, bin_width, (n_tables, n_functions)).astype(np.float32)

        # Flattened views for one batched matmul - zero-copy reshape
        self._A_flat = self.A.reshape(n_tables * n_functions, aug_dim)
        self._b_flat = self.b.ravel()

        # Collapse K-tuple slab indices -> single int64 bucket key
        self._coeffs = rng.integers(
            1 << 20, 1 << 62, size=n_functions, dtype=np.int64)

        # L hash tables: dict[int64 -> int32 ndarray of indices]
        self.tables: list[dict] = [{} for _ in range(n_tables)]

    # ------------------------------------------------------------------
    # Internal: vectorised key computation
    # ------------------------------------------------------------------

    def _compute_keys(self, vecs: np.ndarray) -> np.ndarray:
        """(N, D) or (D,) -> (N, L) or (L,) int64 bucket keys."""
        single = vecs.ndim == 1
        if single:
            vecs = vecs[np.newaxis]

        proj = vecs @ self._A_flat.T + self._b_flat
        slab = np.floor(proj / self.w).astype(np.int32)
        slab = slab.reshape(len(vecs), self.n_tables, self.n_functions)
        keys = np.einsum('nlk,k->nl', slab.astype(np.int64), self._coeffs)

        return keys[0] if single else keys

    def _augment_base(self, vecs, labels):
        # Indexing: [√α·v,  √(1-α)·(a/n_labels)]
        num_vecs = vecs.shape[0]
        label_vecs = np.broadcast_to(
            labels[:, None] / self.n_labels, (num_vecs, self.label_dim))
        return np.column_stack(
            [self._sqrt_alpha * vecs, self._sqrt_1_alpha * label_vecs])

    def _augment_query(self, query_vecs, filter_ranges):
        # Searching: [√α·q,  √(1-α)·((r+l)/2 / n_labels)]
        lo, hi = filter_ranges[:, 0], filter_ranges[:, 1]
        query_labels = (hi + lo) / 2
        num_vecs = query_vecs.shape[0]
        label_vecs = np.broadcast_to(
            query_labels[:, None] / self.n_labels, (num_vecs, self.label_dim))
        return np.column_stack(
            [self._sqrt_alpha * query_vecs, self._sqrt_1_alpha * label_vecs])

    # ------------------------------------------------------------------
    # Internal: candidate collection
    # ------------------------------------------------------------------

    def _effective_min_collisions(self, lo: int, hi: int) -> int:
        """Broad filters need looser pruning to recover recall."""
        if not self.adaptive_collisions:
            return self.min_collisions
        sel = (hi - lo + 1) / self.n_labels
        if sel >= self.sel_threshold:
            return self.min_collisions_loose
        return self.min_collisions

    def _collect(self, parts: list, min_collisions: int | None = None) -> np.ndarray:
        """
        Union the per-table bucket arrays.

        If min_collisions <= 1 this is the original concat+sort+diff dedup.
        Otherwise only candidates appearing in at least `min_collisions`
        tables are kept (collision-frequency pruning).
        """
        mc = self.min_collisions if min_collisions is None else min_collisions
        if not parts:
            return np.array([], dtype=np.int32)

        cat = np.concatenate(parts)   # int32, contiguous
        cat.sort()                    # in-place radix/merge sort
        if len(cat) == 0:
            return cat

        if mc <= 1:
            mask = np.empty(len(cat), dtype=bool)
            mask[0] = True
            mask[1:] = cat[1:] != cat[:-1]
            return cat[mask]

        # Run-length count on the sorted array; keep frequent candidates.
        boundaries = np.flatnonzero(
            np.concatenate(([True], cat[1:] != cat[:-1], [True])))
        counts = np.diff(boundaries)
        vals = cat[boundaries[:-1]]
        return vals[counts >= mc]

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, base_vecs: np.ndarray, labels: np.ndarray) -> None:
        """Index all N base vectors."""
        self.base_vecs = base_vecs
        self.N = len(base_vecs)

        if self._is_filter_aug:
            base_vecs = self._augment_base(base_vecs, labels)
        all_keys = self._compute_keys(base_vecs)   # (N, L) int64

        for t in range(self.n_tables):
            keys_t = all_keys[:, t]
            order = np.argsort(keys_t, kind='stable')
            sk = keys_t[order]
            ukeys, starts, counts = np.unique(
                sk, return_index=True, return_counts=True)
            tbl = {}
            for k, s, c in zip(ukeys.tolist(), starts.tolist(), counts.tolist()):
                tbl[k] = order[s: s + c].astype(np.int32)
            self.tables[t] = tbl

        n_bkts = sum(len(t) for t in self.tables)
        print(f"[LSH] Build done: {self.N:,} vectors | "
              f"{self.n_tables} tables | "
              f"avg buckets/table = {n_bkts / self.n_tables:.1f}")

    # ------------------------------------------------------------------
    # Single-vector query
    # ------------------------------------------------------------------

    def query(self, q_vec: np.ndarray, lo: int, hi: int) -> np.ndarray:
        if self._is_filter_aug:
            filter_range = np.array([[lo, hi]])
            q_vec = self._augment_query(q_vec[np.newaxis], filter_range)[0]
        keys = self._compute_keys(q_vec)   # (L,) int64
        parts = []
        for t in range(self.n_tables):
            bucket = self.tables[t].get(int(keys[t]))
            if bucket is not None:
                parts.append(bucket)
        mc = self._effective_min_collisions(lo, hi)
        return self._collect(parts, min_collisions=mc)

    # ------------------------------------------------------------------
    # Batch query  (one big matmul for all queries)
    # ------------------------------------------------------------------

    def batch_query(self, query_vecs: np.ndarray,
                    filter_range: np.ndarray) -> list[np.ndarray]:
        if self._is_filter_aug:
            query_vecs = self._augment_query(query_vecs, filter_range)
        all_keys = self._compute_keys(query_vecs)   # (Q, L) int64
        results = []

        for q_idx in range(len(query_vecs)):
            keys = all_keys[q_idx]
            parts = []
            for t in range(self.n_tables):
                bucket = self.tables[t].get(int(keys[t]))
                if bucket is not None:
                    parts.append(bucket)
            lo, hi = int(filter_range[q_idx, 0]), int(filter_range[q_idx, 1])
            mc = self._effective_min_collisions(lo, hi)
            results.append(self._collect(parts, min_collisions=mc))

        return results

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def table_fill_stats(self) -> dict:
        sizes = [len(v) for tbl in self.tables for v in tbl.values()]
        arr = np.array(sizes, dtype=np.int64)
        return {"n_buckets": int(len(arr)),
                "mean_size": float(arr.mean()),
                "max_size": int(arr.max())}
