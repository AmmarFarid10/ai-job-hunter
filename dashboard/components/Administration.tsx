"use client";
import { useEffect, useState } from "react";
type User = { id: string; name: string; email: string; role: string };
type Audit = {
  id: string;
  actor_account_id: string;
  target_account_id: string;
  method: string;
  resource: string;
  created_at: string;
};
export default function Administration({
  administrator,
  bootstrapAvailable,
}: {
  administrator: boolean;
  bootstrapAvailable: boolean;
}) {
  const [users, setUsers] = useState<User[]>([]),
    [audit, setAudit] = useState<Audit[]>([]),
    [key, setKey] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [offset, setOffset] = useState(0);
  async function request(path: string, method = "GET", data?: unknown) {
    const r = await fetch("/api/backend/admin/" + path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: data === undefined ? undefined : JSON.stringify(data),
      cache: "no-store",
    });
    const value = await r.json();
    if (!r.ok)
      throw new Error(
        typeof value.detail === "string" ? value.detail : "Request failed",
      );
    return value;
  }
  useEffect(() => {
    if (administrator)
      Promise.all([
        request(`users?limit=50&offset=${offset}`),
        request("audit"),
      ])
        .then(([u, a]) => {
          setUsers(u);
          setAudit(a);
        })
        .catch((e) => setError(e.message));
  }, [administrator, offset]);
  return (
    <section className="panel">
      <h2>Administration</h2>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!administrator && bootstrapAvailable && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await request("bootstrap", "POST", { setup_key: key });
              setKey("");
              location.assign("/");
            } catch (e) {
              setError(e instanceof Error ? e.message : "Setup failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          <p>
            Set up your master administrator account once. This grants access to
            all user workspaces, including the imported workspace.
          </p>
          <label>
            Administrator setup key
            <input
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              required
              maxLength={500}
            />
          </label>
          <button disabled={busy}>Make my account administrator</button>
        </form>
      )}
      {administrator && (
        <>
          <p>
            Select a user to view and manage their workspace. Access is recorded
            in the administrator audit history.
          </p>
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Email</th>
                <th>Role</th>
                <th>Workspace</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td>{u.email}</td>
                  <td>{u.role}</td>
                  <td>
                    <button
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true);
                        try {
                          const r = await fetch("/api/workspace", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ account_id: u.id }),
                          });
                          if (!r.ok)
                            throw new Error("Could not select workspace");
                          location.assign("/");
                        } catch (e) {
                          setError(
                            e instanceof Error ? e.message : "Request failed",
                          );
                          setBusy(false);
                        }
                      }}
                    >
                      View workspace
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="downloads">
            <button
              className="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Previous users
            </button>
            <button
              className="secondary"
              disabled={users.length < 50}
              onClick={() => setOffset(offset + 50)}
            >
              Next users
            </button>
          </div>
          <h3>Recent administrator access</h3>
          <p>
            Successful access to another user’s workspace is recorded. Profile
            contents, passwords and tokens are excluded.
          </p>
          {audit.map((a) => (
            <p key={a.id}>
              {new Date(a.created_at).toLocaleString()} · {a.method}{" "}
              {a.resource} · actor {a.actor_account_id} · workspace{" "}
              {a.target_account_id}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
