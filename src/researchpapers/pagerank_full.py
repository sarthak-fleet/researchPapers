"""PageRank over the full 488k-paper citation graph via scipy.sparse.

The existing pagerank_score values in papers table were computed on a much
smaller subgraph (~8.5k papers). This recomputes on the current corpus and
writes back via ALTER UPDATE.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import scipy.sparse as sp

from researchpapers.ch_db import connect as ch_connect

log = logging.getLogger("researchpapers.pagerank_full")


def compute_and_write(damping: float = 0.85, max_iter: int = 50, tol: float = 1e-6) -> dict:
    t0 = time.monotonic()

    with ch_connect() as ch:
        log.info("loading papers (with openalex_id)...")
        papers = ch.query(
            "SELECT paper_id, openalex_id FROM papers FINAL WHERE length(openalex_id) > 0"
        ).result_rows
    n = len(papers)
    log.info("loaded %d papers", n)

    oa_to_idx = {p[1]: i for i, p in enumerate(papers)}
    paper_id_to_idx = {p[0]: i for i, p in enumerate(papers)}
    paper_id_by_idx = [p[0] for p in papers]

    with ch_connect() as ch:
        log.info("loading edges...")
        edges = ch.query(
            "SELECT citing_arxiv_id, cited_openalex_id FROM references_paper"
        ).result_rows
    log.info("loaded %d edges", len(edges))

    rows = []
    cols = []
    matched = 0
    for citing, cited_oa in edges:
        src = paper_id_to_idx.get(citing)
        dst = oa_to_idx.get(cited_oa)
        if src is not None and dst is not None and src != dst:
            rows.append(src)
            cols.append(dst)
            matched += 1
    log.info("matched %d in-corpus edges", matched)
    if matched == 0:
        return {"computed": 0, "error": "no edges matched"}

    # Build column-stochastic adjacency (transitions): M[j,i] = 1/out_deg(i) if i→j
    data = np.ones(matched, dtype=np.float32)
    A = sp.coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()
    # out-degrees
    out_deg = np.array(A.sum(axis=1)).ravel()
    # Avoid div-by-0 for dangling nodes (no out-links): redistribute uniformly
    dangling = (out_deg == 0)
    out_deg[dangling] = 1.0  # prevent div-by-0; will handle via teleport
    # Transition matrix (transposed for column-stochastic)
    D_inv = sp.diags(1.0 / out_deg)
    M = (A.T @ D_inv).astype(np.float32)

    log.info("running power iteration (max %d iters, tol %.0e)...", max_iter, tol)
    pr = np.ones(n, dtype=np.float32) / n
    teleport = np.ones(n, dtype=np.float32) / n
    for i in range(max_iter):
        # PR = d * (M @ PR + dangling_mass/n) + (1-d) * teleport
        dangling_mass = pr[dangling].sum()
        pr_new = damping * (M @ pr + dangling_mass / n) + (1 - damping) * teleport
        diff = np.abs(pr_new - pr).sum()
        pr = pr_new
        if i % 10 == 0:
            log.info("  iter %d, L1 diff = %.6f", i, float(diff))
        if diff < tol:
            log.info("converged at iter %d", i)
            break

    pr = pr / pr.sum()  # renormalize
    log.info("PR range: min=%.2e max=%.2e mean=%.2e", pr.min(), pr.max(), pr.mean())

    # Write to overlay table paper_scores_v2 — INSERT-only, no UPDATE on papers
    # (avoids partition-key constraints + query-size limits).
    log.info("writing %d pagerank scores to paper_scores_v2...", n)
    with ch_connect() as ch:
        ch.command("""
            CREATE TABLE IF NOT EXISTS paper_scores_v2 (
              paper_id String,
              pagerank Float64,
              computed_at DateTime DEFAULT now()
            )
            ENGINE = ReplacingMergeTree(computed_at)
            ORDER BY paper_id
        """)
    payload = [[paper_id_by_idx[i], float(pr[i])] for i in range(n)]
    BATCH = 10000
    with ch_connect() as ch:
        for start in range(0, n, BATCH):
            ch.insert(
                "paper_scores_v2",
                payload[start : start + BATCH],
                column_names=["paper_id", "pagerank"],
            )
            if start // BATCH % 5 == 0:
                log.info("  inserted %d/%d", min(start + BATCH, n), n)

    return {
        "computed": n,
        "edges": matched,
        "iters": i + 1,
        "elapsed_seconds": round(time.monotonic() - t0, 2),
    }
