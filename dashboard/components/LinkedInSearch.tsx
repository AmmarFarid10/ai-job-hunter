"use client";
import SourceLinks from "@/components/SourceLinks";
import JobDescription from "@/components/JobDescription";
import { useEffect, useState } from "react";
type Row = Record<string, any>;
export default function LinkedInSearch({
  onUpdated,
}: {
  onUpdated: () => Promise<void>;
}) {
  const [providers, setProviders] = useState<Row[]>([]),
    [source, setSource] = useState(""),
    [terms, setTerms] = useState(
      "Senior Python Developer\nFastAPI Developer\nAI Engineer",
    ),
    [items, setItems] = useState<Row[]>([]),
    [offset, setOffset] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [run, setRun] = useState<Row | null>(null);
  async function load(name: string, position = 0) {
    if (!name) return;
    const response = await fetch(
      `/api/backend/discovery/items?${name === "all" ? "" : `provider=${encodeURIComponent(name)}&`}posted_within_days=7&limit=50&offset=${position}`,
      { cache: "no-store" },
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail);
    setItems(value);
    setOffset(position);
  }
  useEffect(() => {
    fetch("/api/backend/discovery/providers", { cache: "no-store" })
      .then((r) => r.json())
      .then((value) => {
        if (!Array.isArray(value))
          throw new Error(value.detail || "Could not load providers");
        const search = value.filter((p: Row) =>
          ["tavily", "brave", "greenhouse", "lever", "career_page"].includes(
            p.kind,
          ),
        );
        setProviders(search);
        setSource(search.length ? "all" : "");
      })
      .catch((e) => setError(e.message));
    fetch("/api/backend/discovery/runs?limit=20", { cache: "no-store" })
      .then((r) => r.json())
      .then((value) => {
        if (Array.isArray(value)) setRun(value[0] || null);
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    setItems([]);
    load(source).catch((e) => setError(e.message));
  }, [source]);
  async function search(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const search_terms = terms
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean);
      if (
        !search_terms.length ||
        search_terms.length > 3 ||
        search_terms.some((t) => t.length < 2 || t.length > 100)
      )
        throw new Error("Enter 1–3 search terms, each 2–100 characters.");
      const response = await fetch("/api/backend/discovery/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sources:
            source === "all"
              ? providers.filter((p) => p.configured).map((p) => p.name)
              : [source],
          posted_within_days: 7,
          search_terms,
          max_items: 20,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      const value = await response.json();
      if (!response.ok)
        throw new Error(
          typeof value.detail === "string"
            ? value.detail
            : JSON.stringify(value.detail),
        );
      setRun(value);
      await load(source);
      await onUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="panel">
        <h2>Job search</h2>
        <p className="muted">
          Search configured company career sources, LinkedIn job listings and
          hiring posts together. Only postings with date evidence from the last
          seven days are included. Undated or updated-only pages are excluded.
          Search snippets need review; no LinkedIn login is used.
        </p>
        <form onSubmit={search}>
          <label>
            Search provider
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="all">All configured sources</option>
              {providers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} ({p.kind}){p.configured ? "" : " — key missing"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Search terms (one per line, up to three)
            <textarea
              value={terms}
              onChange={(e) => setTerms(e.target.value)}
              maxLength={302}
            />
          </label>
          <button
            disabled={
              busy ||
              !(source === "all"
                ? providers.some((p) => p.configured)
                : providers.find((p) => p.name === source)?.configured)
            }
          >
            Search jobs
          </button>
          <small>
            Uses up to three basic API searches from your provider quota.
            Maximum 20 leads per run.
          </small>
        </form>
        {!providers.length && (
          <p className="warning">
            No job sources are enabled. Configure permitted company boards or a
            search provider.
          </p>
        )}
        {providers.length > 0 &&
          source !== "all" &&
          !providers.find((p) => p.name === source)?.configured && (
            <p className="warning">
              The selected search provider is missing its API key in the backend
              environment.
            </p>
          )}
        {busy && <p role="status">Searching job sources…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>
      {run && (
        <section className="panel">
          <h2>Last job search</h2>
          <p>
            <strong>{run.status}</strong> ·{" "}
            {new Date(run.completed_at || run.created_at).toLocaleString()}
          </p>
          <p>
            New review leads: {run.summary.counts.review_required} · Previously
            seen: {run.summary.counts.seen} · Filtered results (old, undated or
            invalid): {run.summary.rejected}
          </p>
          {run.summary.errors.map((e: Row, i: number) => (
            <p className="error" key={i}>
              {e.provider}: {e.code}
            </p>
          ))}
          {run.status === "FAILED" && (
            <p className="warning">
              This search failed. Results below are previously saved leads, not
              new results from this attempt.
            </p>
          )}
          {run.summary.warnings.map((w: Row, i: number) => (
            <small key={i}>{w.code.replaceAll("_", " ").toLowerCase()}</small>
          ))}
        </section>
      )}
      <section className="panel">
        <h2>Saved job leads · last 7 days</h2>
        <p className="muted">
          Showing {items.length} saved leads from{" "}
          {source === "all"
            ? "all configured sources"
            : source || "your provider"}
          . A search snippet is not a full or verified job description; review
          the source before importing a job for matching.
        </p>
        {items.map((item) => (
          <article className="linkedin-lead" key={item.id}>
            <span className="badge">
              {item.status.replaceAll("_", " ").toLowerCase()}
            </span>
            <h3>{item.payload.title}</h3>
            <SourceLinks urls={[item.payload.source_url]} />
            <p>
              {item.payload.company || "Company not confirmed"} ·{" "}
              {item.payload.location || "Location not confirmed"}
            </p>
            {item.payload.posted_at && (
              <p className="muted">
                Posted: {new Date(item.payload.posted_at).toLocaleString()} ·
                reported by source
              </p>
            )}
            <JobDescription
              text={
                item.payload.description || "No description in search result."
              }
            />
          </article>
        ))}
        {!items.length && (
          <p>
            No leads with posting-date evidence from the last seven days. Run a
            new search; older and undated saved leads are hidden.
          </p>
        )}
        <div className="downloads">
          <button
            className="secondary"
            disabled={busy || offset === 0}
            onClick={() =>
              load(source, Math.max(0, offset - 50)).catch((e) =>
                setError(e.message),
              )
            }
          >
            Previous leads
          </button>
          <button
            className="secondary"
            disabled={busy || items.length < 50}
            onClick={() =>
              load(source, offset + 50).catch((e) => setError(e.message))
            }
          >
            Next leads
          </button>
        </div>
      </section>
    </>
  );
}
