"use client";
import { useState } from "react";
export default function AccountSecurity({
  mode,
  token = "",
  email = "",
  onBack,
}: {
  mode: "recover" | "resend" | "verify" | "reset";
  token?: string;
  email?: string;
  onBack: () => void;
}) {
  const [address, setAddress] = useState(email),
    [password, setPassword] = useState(""),
    [confirm, setConfirm] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  const title =
    mode === "recover"
      ? "Reset your password"
      : mode === "resend"
        ? "Verify your email"
        : mode === "verify"
          ? "Confirm email verification"
          : "Choose a new password";
  return (
    <main className="login">
      <section className="login-card">
        <h1>{title}</h1>
        {mode === "resend" && (
          <p>
            Check your inbox for a verification link. Verify your email before
            opening your workspace.
          </p>
        )}
        {mode === "verify" && (
          <p>
            Confirm that you requested verification of your Job Hunter account.
          </p>
        )}
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setError("");
            setMessage("");
            if (mode === "reset" && password !== confirm) {
              setError("Passwords do not match");
              return;
            }
            setBusy(true);
            try {
              const action = {
                recover: "request-password-reset",
                resend: "request-verification",
                verify: "verify-email",
                reset: "reset-password",
              }[mode];
              const response = await fetch("/api/account", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  action,
                  ...(["recover", "resend"].includes(mode)
                    ? { email: address }
                    : { token, ...(mode === "reset" ? { password } : {}) }),
                }),
              });
              const result = await response.json();
              if (!response.ok)
                throw new Error(
                  typeof result.detail === "string"
                    ? result.detail
                    : "Check your details and try again",
                );
              setMessage(result.detail);
              setPassword("");
              setConfirm("");
            } catch (e) {
              setError(e instanceof Error ? e.message : "Request failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          {["recover", "resend"].includes(mode) && (
            <label>
              Email
              <input
                type="email"
                required
                maxLength={320}
                autoComplete="email"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </label>
          )}
          {mode === "reset" && (
            <>
              <label>
                New password
                <input
                  type="password"
                  required
                  minLength={12}
                  maxLength={128}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <label>
                Confirm new password
                <input
                  type="password"
                  required
                  minLength={12}
                  maxLength={128}
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </label>
            </>
          )}
          <button
            disabled={busy || (!!message && ["verify", "reset"].includes(mode))}
          >
            {busy
              ? "Working…"
              : mode === "verify"
                ? "Verify email"
                : mode === "reset"
                  ? "Save new password"
                  : "Send email link"}
          </button>
        </form>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p className="notice" role="status">
            {message}
          </p>
        )}
        <button className="secondary" onClick={onBack}>
          Return to sign in
        </button>
      </section>
    </main>
  );
}
