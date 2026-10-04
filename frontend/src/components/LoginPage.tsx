import { useState } from "react";
import { authLogin } from "../api";

interface Props {
  defaultUsername: string;
  onSuccess: () => void;
}

export function LoginPage({ defaultUsername, onSuccess }: Props) {
  const [username, setUsername] = useState(defaultUsername);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authLogin(username.trim(), password);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
      <div className="w-full max-w-sm rounded-xl border border-slate-800 bg-slate-900/80 p-6 shadow-xl">
        <h1 className="text-lg font-semibold tracking-tight">
          TDX · Sign in
        </h1>
        <p className="mt-1 text-xs text-slate-500">
          This dashboard is protected. Enter the credentials configured on the
          server.
        </p>

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block text-xs">
            <span className="text-slate-400">Username</span>
            <input
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-slate-500 focus:outline-none"
              disabled={busy}
            />
          </label>
          <label className="block text-xs">
            <span className="text-slate-400">Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-slate-500 focus:outline-none"
              disabled={busy}
              required
            />
          </label>

          {error && (
            <div className="rounded-md border border-bear/40 bg-bear/10 px-3 py-2 text-xs text-bear">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy || !password}
            className="w-full rounded-md bg-slate-200 py-2 text-sm font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
