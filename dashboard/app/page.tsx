"use client";
import { useCallback, useEffect, useState } from "react";
import { describeSource } from "@/lib/job-sources.mjs";
import AccountSecurity from "@/components/AccountSecurity";
import SourceLinks from "@/components/SourceLinks";
import JobDescription from "@/components/JobDescription";
import MasterResume from "@/components/MasterResume";
import Administration from "@/components/Administration";
import LinkedInSearch from "@/components/LinkedInSearch";

type Row = Record<string, any>; // Backend snapshots contain versioned, extensible explanation fields.
const tabs = [
  "Overview",
  "Opportunities",
  "Approvals",
  "Applications",
  "Activity",
  "Settings",
  "Master resume",
  "Job search",
];
const proxy = (path: string) =>
  "/api/backend/" + path.replace(/^\/api\/v1\//, "");
async function api(path: string, method = "GET", data?: unknown) {
  const response = await fetch(proxy(path), {
    method,
    headers: { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
    cache: "no-store",
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : JSON.stringify(value.detail),
    );
  return value;
}
function Badge({ value }: { value: string }) {
  return (
    <span
      className={
        "badge " +
        (value === "QUALIFIED" || value === "APPROVED" || value === "COMPLETE"
          ? "green"
          : value === "REJECTED" || value === "FAILED"
            ? "red"
            : "")
      }
    >
      {value.replaceAll("_", " ").toLowerCase()}
    </span>
  );
}
function date(value: string) {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
export default function Home() {
  const [signed, setSigned] = useState<boolean | null>(null);
  const [account, setAccount] = useState<Row>({});
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [recoveryAvailable, setRecoveryAvailable] = useState(false);
  const [accountAction, setAccountAction] = useState<{
    mode: "recover" | "verify" | "reset";
    token?: string;
  } | null>(null);
  const [bootstrapAvailable, setBootstrapAvailable] = useState(false);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState("login"),
    [signupAvailable, setSignupAvailable] = useState(false);
  const [authEmail, setAuthEmail] = useState(""),
    [password, setPassword] = useState(""),
    [accountName, setAccountName] = useState("");
  const [googleAvailable, setGoogleAvailable] = useState(false),
    [googleConnected, setGoogleConnected] = useState(false);
  const [newCandidateName, setNewCandidateName] = useState("");
  const [candidates, setCandidates] = useState<Row[]>([]),
    [candidate, setCandidate] = useState("");
  const [data, setData] = useState<Row | null>(null),
    [tab, setTab] = useState("Overview"),
    [selected, setSelected] = useState("");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState("");
  const [details, setDetails] = useState({
    method: "manual_handoff",
    destination: "",
    cover_letter: "",
    screening_answers: {},
  });
  const [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [linkToken, setLinkToken] = useState<{ id: string; token: string } | null>(
      null,
    );
  const [settings, setSettings] = useState<Row>({}),
    [preferences, setPreferences] = useState<Row>({}),
    [contact, setContact] = useState("");
  const [preview, setPreview] = useState<string | null>(null),
    [reviewLink, setReviewLink] = useState("");
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };
  const load = useCallback(async () => {
    if (candidate) {
      const value = await api("dashboard/" + candidate);
      setData(value);
      setSettings({ ...value.notification_settings, consent: false });
      setPreferences(value.candidate.preferences);
      setContact(value.candidate.email || "");
    }
  }, [candidate]);
  useEffect(() => {
    fetch("/api/session")
      .then((r) => r.json())
      .then((v) => {
        setSigned(!!v.authenticated);
        setAccount(v.user || {});
        setVerificationRequired(!!v.email_verification_required);
        setRecoveryAvailable(!!v.password_recovery_available);
        setBootstrapAvailable(!!v.admin_bootstrap_available);
        setWorkspaceId(v.workspace_id || null);
        setSignupAvailable(!!v.signup_available);
        setGoogleAvailable(!!v.google_available);
        setGoogleConnected(!!v.user?.google_connected);
        if (v.signup_available && !v.authenticated) setAuthMode("signup");
        if (v.detail) setError(v.detail);
      })
      .catch(() => setSigned(false));
    const query = new URLSearchParams(location.search);
    if (query.get("auth_error"))
      setError(
        "Google sign-in was not completed. Try again or use password login. Existing password accounts must connect Google in Settings first.",
      );
    if (query.get("candidate")) setCandidate(query.get("candidate")!);
    if (query.get("job")) setSelected(query.get("job")!);
    const consumeFragment = () => {
      const hash = new URLSearchParams(location.hash.slice(1));
      for (const mode of ["verify", "reset"] as const) {
        const token = hash.get(mode);
        if (token) {
          setAccountAction({ mode, token });
          history.replaceState(null, "", location.pathname);
        }
      }
      if (hash.get("approval") && hash.get("token")) {
        setLinkToken({ id: hash.get("approval")!, token: hash.get("token")! });
        setTab("Approvals");
        history.replaceState(null, "", location.pathname + location.search);
      }
    };
    consumeFragment();
    window.addEventListener("hashchange", consumeFragment);
    return () => window.removeEventListener("hashchange", consumeFragment);
  }, []);
  useEffect(() => {
    if (signed && (!verificationRequired || account.email_verified))
      api("candidates")
        .then((v) => {
          setCandidates(v);
          setCandidate(
            (current) =>
              current || v.find((c: Row) => c.verified)?.id || v[0]?.id || "",
          );
        })
        .catch((e) => setError(e.message));
  }, [signed, verificationRequired, account.email_verified]);
  useEffect(() => {
    if (signed && (!verificationRequired || account.email_verified))
      load().catch((e) => setError(e.message));
  }, [load, signed, verificationRequired, account.email_verified]);
  useEffect(() => {
    setConfirmed(false);
    setReason("");
    setPreview(null);
    setReviewLink("");
  }, [selected]);
  const jobs: Row[] = data?.jobs || [],
    resumes: Row[] = data?.resumes || [],
    approvals: Row[] = data?.approvals || [];
  const job = jobs.find((j) => j.id === selected),
    versions = resumes
      .filter((r) => r.job_id === selected)
      .sort((a, b) => b.version - a.version),
    current = versions[0];
  const approval =
    approvals.find((a) => a.job_id === selected && a.status === "PENDING") ||
    approvals.find((a) => a.job_id === selected);
  useEffect(() => {
    if (job)
      setDetails({
        method: "manual_handoff",
        destination: job.application_url || "",
        cover_letter: "",
        screening_answers: {},
      });
  }, [job?.id]);
  useEffect(() => {
    if (linkToken && data) {
      const row = approvals.find((a) => a.id === linkToken.id);
      if (row) setSelected(row.job_id);
      else
        api("approvals/" + linkToken.id)
          .then((row) => {
            setCandidate(row.candidate_id);
            setSelected(row.job_id);
          })
          .catch((e) => setError(e.message));
    }
  }, [linkToken, data?.candidate.id]);
  async function login(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: authMode,
          email: authEmail,
          password,
          ...(authMode === "signup" ? { name: accountName } : {}),
        }),
      });
      const value = await response.json();
      setPassword("");
      if (!response.ok) throw new Error(value.detail);
      window.location.assign("/");
      setSigned(true);
      setGoogleConnected(!!value.user?.google_connected);
      setSignupAvailable(true);
      setAuthMode("login");
    });
  }
  async function googleSignIn(mode: string) {
    await run(async () => {
      const response = await fetch("/api/oauth/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
        }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail);
      window.location.assign(value.url);
    });
  }
  async function decision(action: string) {
    if (!approval) return;
    await run(async () => {
      await api("approvals/" + approval.id + "/decision", "POST", {
        action,
        confirmed: true,
        reason,
        ...(linkToken && linkToken.id === approval.id
          ? { token: linkToken.token }
          : {}),
      });
      setConfirmed(false);
      await load();
      setNotice(
        action === "approve"
          ? "Approved for this exact resume and application details. No application was sent."
          : "Your decision has been recorded.",
      );
    });
  }
  async function updatePreferences() {
    await run(async () => {
      await api("candidates/" + candidate + "/preferences", "PUT", preferences);
      await load();
      setNotice("Search preferences saved. Rerun matching to refresh results.");
    });
  }
  if (accountAction)
    return (
      <AccountSecurity
        key={accountAction.mode + ":" + (accountAction.token || "")}
        mode={accountAction.mode}
        token={accountAction.token}
        onBack={() => location.assign("/")}
      />
    );
  if (signed && verificationRequired && !account.email_verified)
    return (
      <AccountSecurity
        mode="resend"
        email={account.email}
        onBack={async () => {
          await fetch("/api/session", { method: "DELETE" });
          location.assign("/");
        }}
      />
    );
  if (signed === null)
    return (
      <main className="login">
        <p>Opening your workspace…</p>
      </main>
    );
  if (!signed)
    return (
      <main className="login">
        <div className="login-card">
          <div className="mark">
            J<span>H</span>
          </div>
          <p className="eyebrow">YOUR NEXT CHAPTER</p>
          <h1>
            Good work starts
            <br />
            with a good fit.
          </h1>
          <p className="muted">
            Sign in to your private job hunting workspace.
          </p>
          <div className="downloads">
            <button
              className={authMode === "login" ? "" : "secondary"}
              onClick={() => setAuthMode("login")}
            >
              Log in
            </button>
            <button
              className={authMode === "signup" ? "" : "secondary"}
              disabled={!signupAvailable}
              onClick={() => setAuthMode("signup")}
            >
              Sign up
            </button>
          </div>
          <form onSubmit={login}>
            {authMode === "signup" && (
              <label>
                Your name
                <input
                  value={accountName}
                  onChange={(e) => setAccountName(e.target.value)}
                  maxLength={200}
                  autoComplete="name"
                  required
                />
              </label>
            )}
            <label>
              Email
              <input
                type="email"
                value={authEmail}
                onChange={(e) => setAuthEmail(e.target.value)}
                autoComplete="username"
                maxLength={320}
                required
              />
            </label>
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={
                  authMode === "signup" ? "new-password" : "current-password"
                }
                minLength={12}
                maxLength={128}
                required
              />
            </label>
            <button disabled={busy}>
              {authMode === "signup"
                ? "Create workspace account"
                : "Log in to workspace"}{" "}
              →
            </button>
          </form>
          {recoveryAvailable && (
            <button
              className="subtle"
              onClick={() => setAccountAction({ mode: "recover" })}
            >
              Forgot password?
            </button>
          )}
          <button
            className="secondary google-button"
            disabled={busy || !googleAvailable}
            onClick={() => googleSignIn(authMode)}
          >
            Continue with Google
          </button>
          {!googleAvailable && (
            <small>
              Google sign-in needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
              configured on the backend.
            </small>
          )}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <small>
            Each account has a private workspace. Administrators can access user
            workspaces for support.
          </small>
        </div>
      </main>
    );
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="/">
          J<span>H</span>
          <strong>
            Job Hunter<small>YOUR CAREER WORKSPACE</small>
          </strong>
        </a>
        <nav aria-label="Main navigation">
          {[
            ...tabs,
            ...(account.role === "ADMIN" || bootstrapAvailable
              ? ["Administration"]
              : []),
          ].map((t, i) => (
            <button
              key={t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              <span>{["◫", "↗", "✓", "▤", "◷", "⚙", "↑", "in"][i]}</span>
              {t}
              {t === "Approvals" && (
                <b>{approvals.filter((a) => a.status === "PENDING").length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="mode-dot" />
          Human approval is on
          <p>Every application starts with your decision.</p>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <span className="breadcrumb">
            Workspace <span>/</span> {tab}
          </span>
          <div className="account">
            <span className="avatar">
              {data?.candidate.name
                ?.split(" ")
                .map((s: string) => s[0])
                .slice(0, 2)
                .join("") || "JH"}
            </span>
            <select
              aria-label="Candidate"
              value={candidate}
              onChange={(e) => {
                setCandidate(e.target.value);
                setSelected("");
                setData(null);
              }}
            >
              {candidates.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                  {c.verified ? "" : " (unverified)"}
                </option>
              ))}
            </select>
            <button
              className="subtle"
              onClick={() =>
                run(async () => {
                  const response = await fetch("/api/session", {
                    method: "DELETE",
                  });
                  if (!response.ok)
                    throw new Error("Could not sign out. Try again.");
                  setData(null);
                  setAuthMode("login");
                  setAccount({});
                  setCandidates([]);
                  setCandidate("");
                  setSigned(false);
                })
              }
            >
              Sign out
            </button>
          </div>
        </header>
        <main>
          {workspaceId && (
            <div className="notice" role="status">
              Administrator view: {workspaceId}. Actions affect this workspace.{" "}
              <button
                onClick={async () => {
                  const r = await fetch("/api/workspace", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ account_id: null }),
                  });
                  if (r.ok) location.assign("/");
                  else setError("Could not switch workspace");
                }}
              >
                Return to my workspace
              </button>
            </div>
          )}
          {tab === "Administration" && (
            <Administration
              administrator={account.role === "ADMIN"}
              bootstrapAvailable={bootstrapAvailable}
            />
          )}

          <div className="page-heading">
            <div>
              <p className="eyebrow">MAKE YOUR NEXT MOVE</p>
              <h1>{tab === "Overview" ? "Your search, in focus." : tab}</h1>
              <p className="muted">
                {tab === "Overview"
                  ? "A clear view of your opportunities and what needs your attention."
                  : "Review the facts. You decide what happens next."}
              </p>
            </div>
            <div className="downloads">
              <button
                className="secondary"
                disabled={busy || !data?.candidate.verified}
                onClick={() =>
                  run(async () => {
                    await api("matching/runs", "POST", {
                      candidate_id: candidate,
                      job_ids: jobs.map((j) => j.id),
                      idempotency_key: crypto.randomUUID(),
                    });
                    await load();
                    setNotice("Matches refreshed from stored jobs.");
                  })
                }
              >
                Refresh matches
              </button>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => run(load)}
              >
                ↻ Refresh
              </button>
            </div>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
              <button className="subtle" onClick={() => setError("")}>
                Dismiss
              </button>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
          {busy && (
            <div className="working" role="status">
              Working…
            </div>
          )}
          {tab === "Administration" ? null : !data ? (
            <section className="panel">
              <p>
                {candidates.length
                  ? "Loading your workspace…"
                  : "Create a candidate profile to upload your master resume."}
              </p>
              {!candidates.length && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const row = await api("candidates", "POST", {
                        name: newCandidateName,
                      });
                      setCandidates([row]);
                      setCandidate(row.id);
                      setTab("Master resume");
                    });
                  }}
                >
                  <label>
                    Candidate name
                    <input
                      value={newCandidateName}
                      onChange={(e) => setNewCandidateName(e.target.value)}
                      required
                      maxLength={200}
                    />
                  </label>
                  <button disabled={busy}>Create candidate profile</button>
                </form>
              )}
            </section>
          ) : (
            <>
              {tab === "Overview" && (
                <>
                  <div className="metrics">
                    {[
                      [
                        "Discovered jobs",
                        data.counts.discovered_jobs,
                        "Across your configured sources",
                      ],
                      [
                        "Qualified matches",
                        data.counts.qualified,
                        "Fresh results that pass every check",
                      ],
                      [
                        "Needs review",
                        data.counts.review_required,
                        "Eligibility or requirements unresolved",
                      ],
                      [
                        "Pending decisions",
                        approvals.filter((a) => a.status === "PENDING").length,
                        "Your review queue",
                      ],
                    ].map(([label, value, caption]) => (
                      <section className="metric" key={String(label)}>
                        <p>{label}</p>
                        <strong>{value}</strong>
                        <small>{caption}</small>
                      </section>
                    ))}
                  </div>
                  <div className="overview-grid">
                    <section className="panel">
                      <div className="section-heading">
                        <div>
                          <p className="eyebrow">ON YOUR RADAR</p>
                          <h2>Top opportunities</h2>
                        </div>
                        <button
                          className="subtle"
                          onClick={() => setTab("Opportunities")}
                        >
                          View all →
                        </button>
                      </div>
                      {jobs.slice(0, 6).map((j) => (
                        <button
                          className="opportunity-row"
                          key={j.id}
                          onClick={() => {
                            setSelected(j.id);
                            setTab("Opportunities");
                          }}
                        >
                          <span className="company-icon">
                            {j.company.slice(0, 1)}
                          </span>
                          <span>
                            <strong>{j.title}</strong>
                            <small>
                              {j.company} ·{" "}
                              {j.location || "Location not confirmed"}
                            </small>
                            <small className="muted">
                              {[
                                ...new Set(
                                  (j.source_links?.length
                                    ? j.source_links
                                    : [j.application_url]
                                  )
                                    .map(
                                      (url: string) =>
                                        describeSource(url)?.label,
                                    )
                                    .filter(Boolean),
                                ),
                              ].join(" · ") || "Source unknown"}
                            </small>
                          </span>
                          <span className="score">
                            {j.match.score}
                            <small>match score</small>
                          </span>
                        </button>
                      ))}
                      {!jobs.length && (
                        <p className="muted">
                          Run matching to see opportunities here.
                        </p>
                      )}
                    </section>
                    <section className="panel next-step">
                      <p className="eyebrow">YOUR NEXT STEP</p>
                      <h2>Keep the final say.</h2>
                      <p>
                        Check the job requirements and review the exact resume
                        before making a decision.
                      </p>
                      <div className="flow">
                        <span>
                          01 <strong>Review the match</strong>
                        </span>
                        <span>
                          02 <strong>Read your tailored resume</strong>
                        </span>
                        <span>
                          03 <strong>Approve, reject, or request edits</strong>
                        </span>
                      </div>
                      <button onClick={() => setTab("Approvals")}>
                        Open review queue →
                      </button>
                      <small>
                        Approvals never submit an application in Phase 5.
                      </small>
                    </section>
                  </div>
                  <section className="banner">
                    <span className="mode-dot" />
                    <div>
                      <strong>
                        {data.notification_settings.mode === "mock"
                          ? "Notifications are in development mode"
                          : "Live notification providers configured"}
                      </strong>
                      <p>
                        Reports at 10:00 AM and 8:00 PM · Asia/Karachi ·{" "}
                        {data.notification_settings.enabled
                          ? "Schedule enabled for this candidate"
                          : "Schedule disabled for this candidate"}
                      </p>
                    </div>
                    <button
                      className="subtle"
                      onClick={() => setTab("Settings")}
                    >
                      Manage settings →
                    </button>
                  </section>
                </>
              )}
              {tab === "Opportunities" && (
                <>
                  <div className="toolbar">
                    <input
                      type="search"
                      placeholder="Search title, company, or location…"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      aria-label="Search opportunities"
                    />
                    <span>{jobs.length} canonical jobs</span>
                  </div>
                  <section className="panel table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Opportunity</th>
                          <th>Location</th>
                          <th>Score</th>
                          <th>Status</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {jobs
                          .filter((j) =>
                            (j.title + " " + j.company + " " + j.location)
                              .toLowerCase()
                              .includes(search.toLowerCase()),
                          )
                          .map((j) => (
                            <tr key={j.id}>
                              <td>
                                <strong>{j.title}</strong>
                                <small>{j.company}</small>
                                <SourceLinks
                                  urls={
                                    j.source_links?.length
                                      ? j.source_links
                                      : [j.application_url]
                                  }
                                />
                              </td>
                              <td>{j.location || "Not confirmed"}</td>
                              <td>
                                <b>{j.match.score}</b> / 100
                              </td>
                              <td>
                                <Badge
                                  value={
                                    j.match.stale ? "STALE" : j.match.decision
                                  }
                                />
                              </td>
                              <td>
                                <button
                                  className="subtle"
                                  onClick={() => setSelected(j.id)}
                                >
                                  Review →
                                </button>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </section>
                  <p className="muted footnote">
                    Showing up to 100 canonical jobs. Unmatched jobs need
                    evaluation before resume generation.
                  </p>
                  <section className="panel">
                    <h2>
                      Discovery leads requiring source review (
                      {data.counts.discovery_review})
                    </h2>
                    <p className="muted">
                      Search snippets are leads, not verified job descriptions.
                    </p>
                    {data.discovery_leads.map((lead: Row) => (
                      <details key={lead.id}>
                        <summary>
                          {lead.payload.title ||
                            lead.payload.job_title ||
                            lead.provider}{" "}
                          <Badge value={lead.status} />{" "}
                          <span className="badge">
                            {describeSource(lead.payload.source_url)?.label ||
                              "Source unknown"}
                          </span>
                        </summary>
                        <SourceLinks urls={[lead.payload.source_url]} />
                        <JobDescription
                          text={
                            lead.payload.description ||
                            "No description in this source observation."
                          }
                        />
                        <details>
                          <summary>Source details</summary>
                          <pre>{JSON.stringify(lead.payload, null, 2)}</pre>
                        </details>
                      </details>
                    ))}
                  </section>
                </>
              )}
              {tab === "Approvals" && (
                <section className="panel">
                  <div className="section-heading">
                    <h2>Your decision queue</h2>
                    <span>{approvals.length} review requests</span>
                  </div>
                  {approvals.map((a) => (
                    <div className="approval-row" key={a.id}>
                      <div>
                        <strong>
                          {jobs.find((j) => j.id === a.job_id)?.title ||
                            a.job_id}
                        </strong>
                        <small>
                          {jobs.find((j) => j.id === a.job_id)?.company} ·
                          Expires {date(a.expires_at)}
                        </small>
                        <Badge
                          value={
                            a.status === "APPROVED" && !a.effective_approved
                              ? "APPROVAL_STALE"
                              : a.status
                          }
                        />
                      </div>
                      <button
                        className="secondary"
                        onClick={() => setSelected(a.job_id)}
                      >
                        Review details →
                      </button>
                    </div>
                  ))}
                  {!approvals.length && (
                    <div className="empty">
                      <h3>Your queue is clear.</h3>
                      <p>
                        Open an opportunity, generate a resume, and create a
                        review request to see it here.
                      </p>
                      <button onClick={() => setTab("Opportunities")}>
                        Browse opportunities
                      </button>
                    </div>
                  )}
                </section>
              )}
              {tab === "Applications" && (
                <section className="panel table-wrap">
                  <h2>Application history</h2>
                  <p className="muted">
                    Records track review progress. Submission starts in Phase 6.
                  </p>
                  <table>
                    <thead>
                      <tr>
                        <th>Opportunity</th>
                        <th>Current state</th>
                        <th>Audit history</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.applications.map((a: Row) => (
                        <tr key={a.id}>
                          <td>
                            {jobs.find((j) => j.id === a.job_id)?.title ||
                              a.job_id}
                          </td>
                          <td>
                            <Badge value={a.state} />
                          </td>
                          <td>
                            <details>
                              <summary>{a.events.length} events</summary>
                              {a.events.map((e: Row, i: number) => (
                                <p key={i}>
                                  <b>{e.to_state}</b>
                                  <br />
                                  {e.reason}
                                  <small>{date(e.created_at)}</small>
                                </p>
                              ))}
                            </details>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!data.applications.length && (
                    <p className="empty">No application review records yet.</p>
                  )}
                </section>
              )}
              {tab === "Activity" && (
                <>
                  <section className="panel">
                    <h2>Notification reports</h2>
                    <p className="muted">
                      Mocked means no message left this app. Sent means accepted
                      by the provider.
                    </p>
                    <button
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          const r = await api("notifications/reports", "POST", {
                            candidate_id: candidate,
                            deliver: data.notification_settings.mode === "mock",
                            idempotency_key: crypto.randomUUID(),
                          });
                          await load();
                          setNotice(
                            `Report ${r.status.toLowerCase()}: ${r.content.items.length} opportunities.`,
                          );
                        })
                      }
                    >
                      {data.notification_settings.mode === "mock"
                        ? "Generate mock report"
                        : "Generate report preview"}
                    </button>
                    {data.reports.map((r: Row) => (
                      <details className="report" key={r.id}>
                        <summary>
                          {date(r.created_at)} · {r.content.items.length}{" "}
                          opportunities <Badge value={r.status} />
                        </summary>
                        {r.content.items.map((item: Row) => (
                          <p key={item.job_id}>
                            <strong>
                              {item.title} · {item.company}
                            </strong>
                            <br />
                            Score {item.score} · {item.decision}
                            <br />
                            <button
                              className="subtle"
                              onClick={() => {
                                setSelected(item.job_id);
                                setTab("Opportunities");
                              }}
                            >
                              Open review →
                            </button>
                          </p>
                        ))}
                        {r.deliveries.map((d: Row) => (
                          <small key={d.id}>
                            {d.channel}: {d.status}
                            {d.error_code ? " · " + d.error_code : ""}
                          </small>
                        ))}
                      </details>
                    ))}
                  </section>
                  <section className="panel">
                    <h2>Agent execution history</h2>
                    {data.executions.map((e: Row) => (
                      <details className="report" key={e.id}>
                        <summary>
                          {e.agent_name.replaceAll("_", " ")} ·{" "}
                          {date(e.created_at)} <Badge value={e.status} />
                        </summary>
                        <pre>{JSON.stringify(e.summary, null, 2)}</pre>
                      </details>
                    ))}
                  </section>
                </>
              )}
              {tab === "Master resume" && (
                <MasterResume
                  candidate={candidate}
                  profile={data.candidate}
                  onSaved={load}
                />
              )}
              {tab === "Job search" && <LinkedInSearch onUpdated={load} />}
              {tab === "Settings" && (
                <div className="settings-grid">
                  <section className="panel">
                    <h2>Google account</h2>
                    <p className="muted">
                      {googleConnected
                        ? "Google is connected. You can use it to sign in."
                        : "Connect Google while signed in to keep access to this existing workspace."}
                    </p>
                    <button
                      className="secondary"
                      disabled={busy || !googleAvailable || googleConnected}
                      onClick={() => googleSignIn("link")}
                    >
                      {googleConnected ? "Google connected" : "Connect Google"}
                    </button>
                    {!googleAvailable && (
                      <p className="muted">
                        Configure Google OAuth credentials on the backend to
                        enable this option.
                      </p>
                    )}
                    <hr />
                    <h2>Notification settings</h2>
                    <p className="muted">
                      10:00 AM and 8:00 PM, Asia/Karachi. Current mode:{" "}
                      <b>{settings.mode}</b>.
                    </p>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        run(async () => {
                          await api(
                            "notifications/settings/" + candidate,
                            "PUT",
                            {
                              enabled: settings.enabled,
                              email_enabled: settings.email_enabled,
                              whatsapp_enabled: settings.whatsapp_enabled,
                              email: settings.email || null,
                              whatsapp_number: settings.whatsapp_number || null,
                              consent: settings.consent,
                            },
                          );
                          await load();
                          setNotice("Notification settings saved.");
                        });
                      }}
                    >
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={!!settings.enabled}
                          onChange={(e) =>
                            setSettings({
                              ...settings,
                              enabled: e.target.checked,
                            })
                          }
                        />
                        Enable twice-daily reports
                      </label>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={!!settings.email_enabled}
                          onChange={(e) =>
                            setSettings({
                              ...settings,
                              email_enabled: e.target.checked,
                            })
                          }
                        />
                        Email
                      </label>
                      <label>
                        Report email
                        <input
                          type="email"
                          value={settings.email || ""}
                          onChange={(e) =>
                            setSettings({ ...settings, email: e.target.value })
                          }
                        />
                      </label>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={!!settings.whatsapp_enabled}
                          onChange={(e) =>
                            setSettings({
                              ...settings,
                              whatsapp_enabled: e.target.checked,
                            })
                          }
                        />
                        WhatsApp
                      </label>
                      <label>
                        WhatsApp number (international format)
                        <input
                          placeholder="+923001234567"
                          value={settings.whatsapp_number || ""}
                          onChange={(e) =>
                            setSettings({
                              ...settings,
                              whatsapp_number: e.target.value,
                            })
                          }
                        />
                      </label>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={!!settings.consent}
                          onChange={(e) =>
                            setSettings({
                              ...settings,
                              consent: e.target.checked,
                            })
                          }
                        />
                        I consent to reports at these destinations.
                      </label>
                      <button disabled={busy}>
                        Save notification settings
                      </button>
                    </form>
                  </section>
                  <div>
                    <section className="panel">
                      <h2>Search preferences</h2>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          updatePreferences();
                        }}
                      >
                        <label>
                          Minimum match score
                          <input
                            type="number"
                            min="0"
                            max="100"
                            value={preferences.match_threshold ?? 80}
                            onChange={(e) =>
                              setPreferences({
                                ...preferences,
                                match_threshold: Number(e.target.value),
                              })
                            }
                          />
                        </label>
                        <label>
                          Target roles (one per line)
                          <textarea
                            value={(preferences.roles || []).join("\n")}
                            onChange={(e) =>
                              setPreferences({
                                ...preferences,
                                roles: e.target.value
                                  .split("\n")
                                  .filter(Boolean),
                              })
                            }
                          />
                        </label>
                        <label>
                          Locations (one per line)
                          <textarea
                            value={(preferences.locations || []).join("\n")}
                            onChange={(e) =>
                              setPreferences({
                                ...preferences,
                                locations: e.target.value
                                  .split("\n")
                                  .filter(Boolean),
                              })
                            }
                          />
                        </label>
                        <button disabled={busy}>Save preferences</button>
                      </form>
                    </section>
                    <section className="panel">
                      <h2>Confirmed resume contact</h2>
                      <p className="muted">
                        Adding or changing an email makes existing resumes
                        stale. Generate a fresh version afterward.
                      </p>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          run(async () => {
                            await api(
                              "candidates/" + candidate + "/contact",
                              "PUT",
                              { email: contact, confirmed: true },
                            );
                            await load();
                            setNotice(
                              "Contact confirmed. Generate a fresh resume to include it.",
                            );
                          });
                        }}
                      >
                        <label>
                          Email for resume
                          <input
                            type="email"
                            value={contact}
                            onChange={(e) => setContact(e.target.value)}
                            required
                          />
                        </label>
                        <button disabled={busy}>Confirm contact email</button>
                      </form>
                    </section>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
        <footer>
          AI Job Hunter{" "}
          <span>Private workspace · Phase 5 · You stay in control</span>
        </footer>
      </div>
      {selected && job && (
        <div className="drawer-backdrop" onClick={() => setSelected("")}>
          <section
            className="drawer"
            onKeyDown={(e) => {
              if (e.key === "Escape") setSelected("");
              if (e.key === "Tab") {
                const elements = Array.from(
                  e.currentTarget.querySelectorAll<HTMLElement>(
                    "button:not(:disabled), a[href], input:not(:disabled), textarea, select, summary, iframe",
                  ),
                ).filter((el) => el.getClientRects().length);
                const first = elements[0],
                  last = elements[elements.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last?.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first?.focus();
                }
              }
            }}
            role="dialog"
            aria-modal="true"
            aria-label="Opportunity review"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              autoFocus
              className="close"
              aria-label="Close review"
              onClick={() => setSelected("")}
            >
              ×
            </button>
            <p className="eyebrow">OPPORTUNITY REVIEW</p>
            <h2>{job.title}</h2>
            <p className="muted">
              {job.company} · {job.location}
            </p>
            <SourceLinks
              urls={[...(job.source_links || []), job.application_url]}
            />
            <Badge value={job.match.stale ? "STALE" : job.match.decision} />
            <span className="detail-score">{job.match.score}/100</span>
            <details>
              <summary>Match explanation and unresolved checks</summary>
              <pre>{JSON.stringify(job.match.explanation, null, 2)}</pre>
            </details>
            <details>
              <summary>Original job description</summary>
              <JobDescription text={job.description} />
            </details>
            <div className="section-heading">
              <h3>Tailored resume</h3>
              <button
                className="secondary"
                disabled={busy || job.match.stale}
                onClick={() =>
                  run(async () => {
                    await api("resumes/generations", "POST", {
                      candidate_id: candidate,
                      job_id: job.id,
                      mode: job.match.qualified ? "qualified" : "review",
                      idempotency_key: crypto.randomUUID(),
                    });
                    await load();
                    setNotice("New resume version generated.");
                  })
                }
              >
                {current ? "Generate new version" : "Generate resume"}
              </button>
            </div>
            {current ? (
              <>
                <p>
                  Version {current.version}{" "}
                  <Badge
                    value={current.inputs_current ? current.status : "STALE"}
                  />
                </p>
                {current.document_data.warnings.map((w: string) => (
                  <p className="warning" key={w}>
                    {w.replaceAll("_", " ").toLowerCase()}
                  </p>
                ))}
                <div className="downloads">
                  <button
                    className="secondary"
                    onClick={() => setPreview(current.downloads.pdf)}
                  >
                    Preview PDF
                  </button>
                  {Object.entries(current.downloads).map(([fmt, url]) => (
                    <a
                      className="button secondary"
                      key={fmt}
                      href={proxy(url as string)}
                      target="_blank"
                      rel="noopener"
                    >
                      Download {fmt.toUpperCase()}
                    </a>
                  ))}
                </div>
                {preview && (
                  <div className="resume-pages" aria-label="Resume PDF preview">
                    {Array.from(
                      {
                        length: Math.min(
                          current.document_data.pdf_pages || 1,
                          30,
                        ),
                      },
                      (_, i) => (
                        <img
                          key={i}
                          loading="lazy"
                          src={proxy(
                            `/api/v1/resumes/versions/${current.id}/preview/${i + 1}`,
                          )}
                          alt={`Resume PDF page ${i + 1}`}
                        />
                      ),
                    )}
                  </div>
                )}
                <details>
                  <summary>Version history ({versions.length})</summary>
                  {versions.map((v) => (
                    <p key={v.id}>
                      Version {v.version} · {date(v.created_at)} · {v.status}{" "}
                      <a
                        href={proxy(v.downloads.pdf)}
                        target="_blank"
                        rel="noopener"
                      >
                        PDF
                      </a>
                    </p>
                  ))}
                </details>
              </>
            ) : (
              <p className="muted">No resume generated for this job yet.</p>
            )}
            {current && (
              <section className="review-actions">
                {reviewLink && (
                  <p>
                    <a href={reviewLink}>Open expiring review link</a> · Login
                    required
                  </p>
                )}
                <h3>
                  {approval?.status === "PENDING" &&
                  !approval.blockers.includes("EXPIRED")
                    ? "Your review request"
                    : "Prepare a review request"}
                </h3>
                {approval?.status === "PENDING" &&
                !approval.blockers.includes("EXPIRED") ? (
                  <>
                    <p>
                      Expires {date(approval.expires_at)}. Approval applies only
                      to these exact details.
                    </p>
                    <dl>
                      <dt>Method</dt>
                      <dd>{approval.details.method}</dd>
                      <dt>Destination</dt>
                      <dd>{approval.details.destination}</dd>
                      <dt>Cover letter</dt>
                      <dd>{approval.details.cover_letter || "None"}</dd>
                      <dt>Screening answers</dt>
                      <dd>
                        <pre>
                          {JSON.stringify(
                            approval.details.screening_answers,
                            null,
                            2,
                          )}
                        </pre>
                      </dd>
                      <dt>Resume SHA-256 manifest</dt>
                      <dd className="hash">{approval.resume_hash}</dd>
                    </dl>
                    {approval.blockers.length > 0 && (
                      <div className="warning">
                        <strong>Approval needs attention</strong>
                        {approval.blockers.map((b: string) => (
                          <p key={b}>{b.replaceAll("_", " ").toLowerCase()}</p>
                        ))}
                      </div>
                    )}
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={confirmed}
                        onChange={(e) => setConfirmed(e.target.checked)}
                      />
                      I reviewed this resume version and the exact application
                      details above.
                    </label>
                    <label>
                      Reason or requested changes
                      <textarea
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                      />
                    </label>
                    <div className="decision-buttons">
                      <button
                        disabled={busy || !confirmed || !approval.can_approve}
                        onClick={() => decision("approve")}
                      >
                        Approve exact version
                      </button>
                      <button
                        className="secondary"
                        disabled={busy || !reason.trim()}
                        onClick={() => decision("request_changes")}
                      >
                        Request changes
                      </button>
                      <button
                        className="danger"
                        disabled={busy}
                        onClick={() => decision("reject")}
                      >
                        Reject
                      </button>
                    </div>
                    <p className="muted footnote">
                      Requesting changes records instructions for your next
                      revision. No facts or resume files change automatically.
                    </p>
                  </>
                ) : (
                  <>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        run(async () => {
                          const request = await api("approvals", "POST", {
                            resume_version_id: current.id,
                            details,
                          });
                          setReviewLink(request.review_link);
                          await load();
                          setNotice(
                            "Review request created. No decision has been made.",
                          );
                        });
                      }}
                    >
                      <label>
                        Application method
                        <select
                          value={details.method}
                          onChange={(e) =>
                            setDetails({ ...details, method: e.target.value })
                          }
                        >
                          <option value="manual_handoff">Manual handoff</option>
                          <option value="career_portal">
                            Company career portal
                          </option>
                          <option value="email">Email</option>
                        </select>
                      </label>
                      <label>
                        Exact destination
                        <input
                          value={details.destination}
                          onChange={(e) =>
                            setDetails({
                              ...details,
                              destination: e.target.value,
                            })
                          }
                          required
                        />
                      </label>
                      <label>
                        Cover letter (optional)
                        <textarea
                          value={details.cover_letter}
                          onChange={(e) =>
                            setDetails({
                              ...details,
                              cover_letter: e.target.value,
                            })
                          }
                        />
                      </label>
                      <button
                        disabled={
                          busy ||
                          !current.inputs_current ||
                          approval?.status === "REJECTED"
                        }
                      >
                        Create review request
                      </button>
                    </form>
                    {approval && (
                      <>
                        <p>
                          Last decision: <Badge value={approval.status} />
                        </p>
                        {approval.reason && <p>{approval.reason}</p>}
                        {approval.status === "APPROVED" && (
                          <button
                            className="danger"
                            disabled={busy}
                            onClick={() => decision("revoke")}
                          >
                            Revoke approval
                          </button>
                        )}
                      </>
                    )}
                  </>
                )}
                {approval && (
                  <details>
                    <summary>Decision audit history</summary>
                    {approval.events.map((e: Row, i: number) => (
                      <p key={i}>
                        <b>{e.action}</b> · {date(e.created_at)}
                        <br />
                        {e.reason}
                      </p>
                    ))}
                  </details>
                )}
              </section>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
