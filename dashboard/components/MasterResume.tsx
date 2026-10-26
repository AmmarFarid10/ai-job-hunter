"use client";
import { useEffect, useState } from "react";
type Row = Record<string, any>;
const base = (candidate: string) =>
  `/api/backend/candidates/${candidate}/resumes`;
function payload(profile: Row) {
  return {
    name: profile.name,
    email: profile.email,
    location: profile.location,
    summary: profile.summary,
    confirmed: true,
    skills: (profile.skills || [])
      .filter((s: Row) => s.verified)
      .map((s: Row) => s.name),
    experiences: (profile.experiences || [])
      .filter((s: Row) => s.verified)
      .map(({ verified, ...row }: Row) => row),
    education: (profile.education || [])
      .filter((s: Row) => s.verified)
      .map(({ verified, ...row }: Row) => row),
    preferences: profile.preferences || {},
  };
}
export default function MasterResume({
  candidate,
  profile,
  onSaved,
}: {
  candidate: string;
  profile: Row;
  onSaved: () => Promise<void>;
}) {
  const [drafts, setDrafts] = useState<Row[]>([]),
    [draft, setDraft] = useState<Row | null>(null),
    [file, setFile] = useState<File | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [editor, setEditor] = useState(""),
    [confirmed, setConfirmed] = useState(false);
  async function history() {
    const response = await fetch(base(candidate), { cache: "no-store" });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail);
    setDrafts(value);
  }
  useEffect(() => {
    setDraft(null);
    setConfirmed(false);
    history().catch((e) => setError(e.message));
  }, [candidate]);
  function select(row: Row) {
    setDraft(row);
    setEditor(
      JSON.stringify(row.confirmed_profile || payload(profile), null, 2),
    );
    setConfirmed(false);
    setNotice("");
  }
  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (file.size > 10 * 1024 * 1024)
        throw new Error("Choose a PDF up to 10 MB.");
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(base(candidate), {
        method: "POST",
        body: form,
      });
      const value = await response.json();
      if (!response.ok)
        throw new Error(
          typeof value.detail === "string" ? value.detail : "Upload failed",
        );
      select(value);
      await history();
      setNotice(
        "Master resume uploaded. Review the extracted text and each profile fact before confirming.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!draft || !confirmed) return;
    setBusy(true);
    setError("");
    try {
      const value = JSON.parse(editor);
      value.confirmed = true;
      const response = await fetch(base(candidate) + `/${draft.id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(value),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : JSON.stringify(result.detail),
        );
      await onSaved();
      await history();
      setDraft({
        ...draft,
        reviewed_at: new Date().toISOString(),
        confirmed_profile: value,
      });
      setConfirmed(false);
      setNotice(
        "Profile confirmed. Existing matches and tailored resumes may now be stale; refresh matching and generate new versions.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Confirmation failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="panel">
        <h2>Upload your master resume</h2>
        <p className="muted">
          PDF up to 10 MB. Uploads are private review drafts and never overwrite
          your confirmed profile automatically.
        </p>
        <form onSubmit={upload}>
          <label>
            Master resume PDF
            <input
              type="file"
              accept="application/pdf,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              required
            />
          </label>
          <button disabled={busy || !file}>Upload master resume</button>
        </form>
        {busy && <p role="status">Processing resume…</p>}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {notice && (
          <div className="notice" role="status">
            {notice}
          </div>
        )}
      </section>
      {draft && (
        <section className="panel">
          <div className="section-heading">
            <h2>Review uploaded resume</h2>
            <a
              className="button secondary"
              href={base(candidate) + `/${draft.id}/download`}
              target="_blank"
              rel="noopener"
            >
              Download original PDF
            </a>
          </div>
          {draft.warnings.map((warning: string) => (
            <p className="warning" key={warning}>
              {warning}
            </p>
          ))}
          <details open>
            <summary>Extracted source text</summary>
            <pre>
              {draft.extracted_text ||
                "No text extracted. Enter verified facts manually from the PDF."}
            </pre>
          </details>
          <p>
            <b>Suggested skills:</b>{" "}
            {draft.suggestions.skills.join(", ") || "None detected"}
          </p>
          <p>
            <b>Emails found in source:</b>{" "}
            {draft.suggestions.emails.join(", ") || "None detected"}
          </p>
          <p className="muted">
            The editor starts with your existing confirmed facts. Copy or
            correct facts from this PDF; employers, dates and education require
            manual review. Suggested skills and emails are not automatically
            verified.
          </p>
          <label>
            Profile facts to confirm (JSON)
            <textarea
              className="profile-editor"
              spellCheck={false}
              value={editor}
              onChange={(e) => {
                setEditor(e.target.value);
                setConfirmed(false);
              }}
              readOnly={!!draft.reviewed_at}
            />
          </label>
          {draft.reviewed_at ? (
            <p className="notice">
              This upload was already confirmed. Upload a new revision to review
              further changes.
            </p>
          ) : (
            <>
              <label className="check">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                I checked every fact against my resume, including skills,
                employment dates and education, and confirm this profile.
              </label>
              <button disabled={busy || !confirmed} onClick={save}>
                Confirm reviewed profile
              </button>
            </>
          )}
        </section>
      )}
      <section className="panel">
        <h2>Master resume history</h2>
        {drafts.map((row) => (
          <div className="approval-row" key={row.id}>
            <div>
              <strong>{new Date(row.created_at).toLocaleString()}</strong>
              <small>
                {row.reviewed_at
                  ? "Confirmed profile source"
                  : "Unverified review draft"}{" "}
                · SHA-256 {row.sha256.slice(0, 12)}…
              </small>
            </div>
            <button className="secondary" onClick={() => select(row)}>
              Review upload
            </button>
          </div>
        ))}
        {!drafts.length && (
          <p className="muted">No master resume uploaded for this candidate.</p>
        )}
      </section>
    </>
  );
}
