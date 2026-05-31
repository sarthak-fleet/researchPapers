import * as React from "react";

import { Badge } from "@/components/ui/badge";

type Result = {
  paper_id: string;
  source: string;
  title: string;
  abstract_preview: string;
  submitted_date: string | null;
  citation_count: number;
  arxiv_id: string | null;
  similarity: number;
};

// Resolve API base in this priority:
//   1. PUBLIC_API_URL build-time env (Cloudflare Pages / Vercel)
//   2. window.__API_BASE__ runtime override (set via /api-config.js if present)
//   3. Default: localhost:8000 (local dev)
const API_BASE: string =
  (import.meta.env.PUBLIC_API_URL as string | undefined) ??
  (typeof window !== "undefined" && (window as any).__API_BASE__) ??
  "http://127.0.0.1:8000";

function paperUrl(paper_id: string, arxiv_id: string | null): string {
  if (arxiv_id) return `https://arxiv.org/abs/${arxiv_id}`;
  if (paper_id.startsWith("arxiv:")) return `https://arxiv.org/abs/${paper_id.replace("arxiv:", "")}`;
  if (paper_id.startsWith("openreview:")) return `https://openreview.net/forum?id=${paper_id.replace("openreview:", "")}`;
  return "#";
}

export function SemanticSearch() {
  const [q, setQ] = React.useState("");
  const [results, setResults] = React.useState<Result[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [didSearch, setDidSearch] = React.useState(false);

  const run = React.useCallback(async (query: string) => {
    if (query.length < 3) return;
    setLoading(true);
    setError(null);
    setDidSearch(true);
    try {
      const r = await fetch(`${API_BASE}/semantic-search?q=${encodeURIComponent(query)}&limit=15`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setResults(data.results || []);
    } catch (e: any) {
      setError(e?.message || "request failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div class="space-y-4">
      <form
        onSubmit={(e) => { e.preventDefault(); run(q); }}
        class="flex gap-2"
      >
        <input
          type="text"
          value={q}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)}
          placeholder="Search the corpus by meaning — e.g. 'emergent capabilities in language models'"
          class="flex-1 rounded-lg border bg-card px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 placeholder:text-muted-foreground/60"
        />
        <button
          type="submit"
          disabled={loading || q.length < 3}
          class="px-5 py-3 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
        >
          {loading ? "Searching..." : "Search"}
        </button>
      </form>

      {error && <div class="text-sm text-destructive">Error: {error}. Is the API running at {API_BASE}?</div>}

      {didSearch && !loading && results.length === 0 && !error && (
        <div class="text-sm text-muted-foreground">No matches. The embedding index may still be building — try again in a few minutes.</div>
      )}

      {results.length > 0 && (
        <div class="space-y-2">
          {results.map((r) => (
            <a
              key={r.paper_id}
              href={paperUrl(r.paper_id, r.arxiv_id)}
              target="_blank"
              rel="noopener"
              class="block rounded-lg border bg-card p-3 hover:bg-muted/40 transition-colors"
            >
              <div class="flex items-center gap-2 text-xs mb-1">
                <span class="tabular-nums text-primary font-semibold">{r.similarity.toFixed(3)}</span>
                <Badge variant="outline" class="font-mono text-[10px]">{r.source}</Badge>
                {r.citation_count > 0 && (
                  <span class="tabular-nums text-muted-foreground">{r.citation_count.toLocaleString()} cites</span>
                )}
                {r.submitted_date && (
                  <span class="text-muted-foreground tabular-nums">{r.submitted_date.slice(0, 4)}</span>
                )}
              </div>
              <div class="text-sm text-foreground/90 mb-1">{r.title}</div>
              <div class="text-xs text-muted-foreground line-clamp-2">{r.abstract_preview}</div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
