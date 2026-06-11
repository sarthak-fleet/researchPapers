"""Exports from ClickHouse → JSON for the Astro app.

Initial scope: OpenReview reviews aggregations. The Postgres-based exporter.py
keeps owning everything else for now; this is incremental.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from researchpapers.ch_db import connect as ch_connect

log = logging.getLogger("researchpapers.ch_exports")


def _row_to_dict(row, names: list[str]) -> dict:
    return dict(zip(names, row, strict=True))


def export_review_data(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with ch_connect() as c:
        # 1. Summary across venues
        result = c.query("""
            SELECT
                venue,
                count() AS n_reviews,
                countDistinct(paper_id) AS n_papers,
                avg(rating) AS avg_rating,
                avg(confidence) AS avg_confidence,
                countIf(decision = 'Accept (Oral)') AS oral_accepts,
                countIf(decision = 'Accept (Poster)') AS poster_accepts,
                countIf(decision = 'Reject') AS rejects
            FROM openreview_reviews
            GROUP BY venue
            ORDER BY n_reviews DESC
        """).result_rows
        cols = ["venue", "n_reviews", "n_papers", "avg_rating", "avg_confidence",
                "oral_accepts", "poster_accepts", "rejects"]
        venues = [
            {
                **_row_to_dict(r, cols),
                "avg_rating": round(float(r[3] or 0), 2),
                "avg_confidence": round(float(r[4] or 0), 2),
            }
            for r in result
        ]
        p = out_dir / "review_venues.json"
        p.write_text(json.dumps(venues, indent=2, default=str))
        written.append(p)

        # 2. Top-rated submissions: best reviewer-average per paper
        result = c.query("""
            SELECT
                r.paper_id,
                p.title,
                r.venue,
                avg(r.rating) AS avg_rating,
                avg(r.confidence) AS avg_confidence,
                count() AS n_reviews,
                any(r.decision) AS decision
            FROM openreview_reviews r
            LEFT JOIN papers p ON p.paper_id = r.paper_id
            WHERE r.rating IS NOT NULL
            GROUP BY r.paper_id, p.title, r.venue
            HAVING n_reviews >= 3
            ORDER BY avg_rating DESC, avg_confidence DESC
            LIMIT 200
        """).result_rows
        cols2 = ["paper_id", "title", "venue", "avg_rating", "avg_confidence",
                 "n_reviews", "decision"]
        top_papers = [
            {
                **_row_to_dict(r, cols2),
                "avg_rating": round(float(r[3] or 0), 2),
                "avg_confidence": round(float(r[4] or 0), 2),
            }
            for r in result
        ]
        p = out_dir / "review_top_papers.json"
        p.write_text(json.dumps(top_papers, indent=2, default=str))
        written.append(p)

        # 3. Rating distribution per venue
        result = c.query("""
            SELECT venue, rating, count() AS n
            FROM openreview_reviews
            WHERE rating IS NOT NULL
            GROUP BY venue, rating
            ORDER BY venue, rating
        """).result_rows
        distribution = [
            {"venue": r[0], "rating": int(r[1]), "n": int(r[2])} for r in result
        ]
        p = out_dir / "review_rating_distribution.json"
        p.write_text(json.dumps(distribution, indent=2))
        written.append(p)

        # 4. Source breakdown (papers across sources) — useful for the header card
        result = c.query("""
            SELECT source, count() AS n FROM papers GROUP BY source ORDER BY n DESC
        """).result_rows
        sources = [{"source": r[0], "n": int(r[1])} for r in result]
        p = out_dir / "ch_sources_summary.json"
        p.write_text(json.dumps(sources, indent=2))
        written.append(p)

        # 5a. Tag × reviewer rating cross-join — the HighSignal-shape insight.
        # Tags are normalized to lowercase (collapses "Deep Learning"/"deep learning"/"DEEP LEARNING")
        # and known plural pairs ("language models"/"language model") are merged via the CASE map.
        # For each spaCy-extracted tag, mean ICLR/NeurIPS reviewer rating across
        # papers tagged with it. Includes sample top-rated papers per tag for drilldown.
        result = c.query("""
            WITH paper_avg_rating AS (
                SELECT
                    r.paper_id,
                    avg(r.rating) AS avg_rating,
                    count() AS n_reviews,
                    any(r.venue) AS venue,
                    any(p.title) AS title
                FROM openreview_reviews r
                LEFT JOIN papers p ON p.paper_id = r.paper_id
                WHERE r.rating IS NOT NULL
                GROUP BY r.paper_id
                HAVING n_reviews >= 3
            )
            SELECT
                multiIf(
                  lower(tag) IN ('language model', 'large language model', 'large language models'), 'language models',
                  lower(tag) IN ('neural network'), 'neural networks',
                  lower(tag) IN ('diffusion model'), 'diffusion models',
                  lower(tag) IN ('transformer'), 'transformers',
                  lower(tag) IN ('vision transformer'), 'vision transformers',
                  lower(tag) IN ('graph neural network'), 'graph neural networks',
                  lower(tag) IN ('convolutional neural network'), 'convolutional neural networks',
                  lower(tag) IN ('llm', 'llms'), 'llms',
                  lower(tag)
                ) AS canonical_tag,
                round(avg(par.avg_rating), 2) AS mean_rating,
                count() AS n_papers,
                round(quantile(0.9)(par.avg_rating), 2) AS p90_rating,
                groupArray(50)((par.avg_rating, par.title, par.paper_id, par.venue)) AS samples
            FROM paper_tags t FINAL
            ARRAY JOIN tags AS tag
            JOIN paper_avg_rating par ON par.paper_id = t.paper_id
            WHERE t.tagger = 'spacy_v2'
            GROUP BY canonical_tag
            HAVING n_papers >= 10
            ORDER BY mean_rating DESC
            LIMIT 100
        """).result_rows
        tag_rating = []
        for r in result:
            samples = sorted(
                [{"avg_rating": float(s[0]), "title": s[1] or "", "paper_id": s[2], "venue": s[3]} for s in r[4]],
                key=lambda s: -s["avg_rating"],
            )[:5]
            tag_rating.append({
                "tag": r[0],
                "mean_rating": float(r[1] or 0),
                "n_papers": int(r[2]),
                "p90_rating": float(r[3] or 0),
                "samples": samples,
            })
        p = out_dir / "tag_rating.json"
        p.write_text(json.dumps(tag_rating, indent=2, default=str))
        written.append(p)

        # 6. Sleeper papers — reviewers loved them but they haven't accrued citations.
        result = c.query("""
            WITH par AS (
              SELECT paper_id, avg(rating) AS avg_rating, count() AS n_reviews,
                     any(decision) AS decision, any(venue) AS venue
              FROM openreview_reviews WHERE rating IS NOT NULL
              GROUP BY paper_id HAVING n_reviews >= 3
            )
            SELECT p.paper_id, coalesce(nullIf(m.title, ''), p.title) AS title, par.avg_rating, par.n_reviews,
                   coalesce(nullIf(m.citation_count, 0), p.citation_count) AS citation_count,
                   par.venue, par.decision, p.submitted_date
            FROM par
            JOIN papers p ON p.paper_id = par.paper_id
            LEFT JOIN paper_metadata_v2 AS m FINAL ON m.paper_id = p.paper_id
            WHERE par.avg_rating >= 7.0 AND coalesce(nullIf(m.citation_count, 0), p.citation_count) <= 20
              AND effective_year(p.source, p.arxiv_id, p.submitted_date) >= 2024
            ORDER BY par.avg_rating DESC, citation_count ASC
            LIMIT 100
        """).result_rows
        sleepers = [
            {"paper_id": r[0], "title": r[1], "avg_rating": round(float(r[2]), 2),
             "n_reviews": int(r[3]), "citation_count": int(r[4] or 0),
             "venue": r[5], "decision": r[6], "submitted_date": str(r[7]) if r[7] else None}
            for r in result
        ]
        p = out_dir / "sleepers.json"
        p.write_text(json.dumps(sleepers, indent=2, default=str))
        written.append(p)

        # 7. Hot right now — unified score across cites/year + rating + PageRank.
        result = c.query("""
            WITH par AS (
              SELECT paper_id, avg(rating) AS avg_rating
              FROM openreview_reviews WHERE rating IS NOT NULL
              GROUP BY paper_id HAVING count() >= 3
            )
            SELECT p.paper_id, p.source,
                   coalesce(nullIf(m.title, ''), p.title) AS title,
                   coalesce(nullIf(m.citation_count, 0), p.citation_count) AS citation_count,
                   p.submitted_date,
                   round(citation_count / greatest((today() - effective_date(p.source, p.arxiv_id, p.submitted_date)) / 365.25, 0.25), 1) AS cpy,
                   coalesce(par.avg_rating, 0) AS rating,
                   coalesce(s.pagerank, p.pagerank_score, 0) AS pr,
                   round(
                     0.5 * log(1 + citation_count / greatest((today() - effective_date(p.source, p.arxiv_id, p.submitted_date)) / 365.25, 0.25))
                     + 0.3 * coalesce(par.avg_rating, 5.0) / 10
                     + 0.2 * coalesce(s.pagerank, p.pagerank_score, 0) * 10000,
                   3) AS hotness
            FROM papers AS p FINAL
            LEFT JOIN par ON par.paper_id = p.paper_id
            LEFT JOIN paper_metadata_v2 AS m FINAL ON m.paper_id = p.paper_id
            LEFT JOIN paper_scores_v2 AS s FINAL ON s.paper_id = p.paper_id
            WHERE p.submitted_date IS NOT NULL
              AND effective_year(p.source, p.arxiv_id, p.submitted_date) >= 2023
              AND coalesce(nullIf(m.citation_count, 0), p.citation_count) >= 5
            ORDER BY hotness DESC
            LIMIT 100
        """).result_rows
        hot = [
            {"paper_id": r[0], "source": r[1], "title": r[2],
             "citation_count": int(r[3] or 0),
             "submitted_date": str(r[4]) if r[4] else None,
             "cites_per_year": float(r[5]),
             "avg_rating": round(float(r[6]), 2) if r[6] else None,
             "pagerank": float(r[7]),
             "hotness": float(r[8])}
            for r in result
        ]
        p = out_dir / "hot.json"
        p.write_text(json.dumps(hot, indent=2, default=str))
        written.append(p)

        # 8. Tag co-occurrence — which tags travel together in the same paper.
        # Top 30 tags as nodes; edges weighted by # papers tagged with both.
        top_tags_result = c.query("""
            SELECT
                multiIf(
                  lower(tag) IN ('language model', 'large language model', 'large language models'), 'language models',
                  lower(tag) IN ('neural network'), 'neural networks',
                  lower(tag) IN ('diffusion model'), 'diffusion models',
                  lower(tag) IN ('transformer'), 'transformers',
                  lower(tag) IN ('llm', 'llms'), 'llms',
                  lower(tag)
                ) AS t,
                count() AS n
            FROM paper_tags FINAL
            ARRAY JOIN tags AS tag
            WHERE tagger = 'spacy_v2'
            GROUP BY t ORDER BY n DESC LIMIT 30
        """).result_rows
        top_tag_set = {r[0] for r in top_tags_result}
        top_tag_counts = {r[0]: int(r[1]) for r in top_tags_result}

        # Compute co-occurrence by joining paper_tags to itself via ARRAY JOIN.
        # Filter to pairs where both sides are in top_tag_set.
        rows_co = c.query(
            """
            SELECT t1, t2, count() AS co
            FROM (
              SELECT t.paper_id,
                multiIf(
                  lower(tag) IN ('language model', 'large language model', 'large language models'), 'language models',
                  lower(tag) IN ('neural network'), 'neural networks',
                  lower(tag) IN ('diffusion model'), 'diffusion models',
                  lower(tag) IN ('transformer'), 'transformers',
                  lower(tag) IN ('llm', 'llms'), 'llms',
                  lower(tag)
                ) AS canonical
              FROM paper_tags AS t FINAL
              ARRAY JOIN tags AS tag
              WHERE t.tagger = 'spacy_v2'
            ) p1
            JOIN (
              SELECT t.paper_id,
                multiIf(
                  lower(tag) IN ('language model', 'large language model', 'large language models'), 'language models',
                  lower(tag) IN ('neural network'), 'neural networks',
                  lower(tag) IN ('diffusion model'), 'diffusion models',
                  lower(tag) IN ('transformer'), 'transformers',
                  lower(tag) IN ('llm', 'llms'), 'llms',
                  lower(tag)
                ) AS canonical
              FROM paper_tags AS t FINAL
              ARRAY JOIN tags AS tag
              WHERE t.tagger = 'spacy_v2'
            ) p2 USING (paper_id)
            ARRAY JOIN [p1.canonical] AS t1, [p2.canonical] AS t2
            WHERE t1 < t2 AND t1 IN %(top)s AND t2 IN %(top)s
            GROUP BY t1, t2
            HAVING co >= 50
            ORDER BY co DESC
            LIMIT 500
            """,
            parameters={"top": list(top_tag_set)},
        ).result_rows
        tag_cooccur = {
            "nodes": [
                {"id": t, "count": top_tag_counts[t]}
                for t in sorted(top_tag_set, key=lambda x: -top_tag_counts[x])
            ],
            "edges": [
                {"source": r[0], "target": r[1], "co_occurrence": int(r[2])}
                for r in rows_co
            ],
        }
        p = out_dir / "tag_cooccurrence.json"
        p.write_text(json.dumps(tag_cooccur, indent=2))
        written.append(p)

        # 9. Embedding-based semantic clusters (MiniBatchKMeans on 478k × 384).
        # For each cluster: size, top tags, top-cited sample papers.
        cluster_rows = c.query("""
            SELECT cluster_id, count() AS size
            FROM paper_clusters FINAL
            GROUP BY cluster_id
            ORDER BY size DESC
        """).result_rows

        clusters_out = []
        for cid, size in cluster_rows:
            top_tags = c.query(
                """
                SELECT tag, count() AS n
                FROM paper_tags t FINAL
                ARRAY JOIN tags AS tag
                JOIN paper_clusters pc FINAL ON pc.paper_id = t.paper_id
                WHERE t.tagger = 'spacy_v2' AND pc.cluster_id = %(cid)s
                GROUP BY tag
                HAVING n >= 5
                ORDER BY n DESC LIMIT 8
                """,
                parameters={"cid": int(cid)},
            ).result_rows
            samples = c.query(
                """
                SELECT p.paper_id, p.title, p.citation_count, p.source
                FROM paper_clusters pc FINAL
                JOIN papers AS p FINAL ON p.paper_id = pc.paper_id
                WHERE pc.cluster_id = %(cid)s
                ORDER BY p.citation_count DESC
                LIMIT 5
                """,
                parameters={"cid": int(cid)},
            ).result_rows
            clusters_out.append({
                "id": int(cid),
                "size": int(size),
                "top_tags": [{"tag": r[0], "n": int(r[1])} for r in top_tags],
                "top_papers": [
                    {"paper_id": r[0], "title": r[1], "citation_count": int(r[2] or 0), "source": r[3]}
                    for r in samples
                ],
            })
        p = out_dir / "embedding_clusters.json"
        p.write_text(json.dumps(clusters_out, indent=2))
        written.append(p)
    return written
