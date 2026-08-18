"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      router.replace("/generate");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-[60vh] items-center justify-center overflow-hidden">
      <div className="orb absolute left-1/2 top-1/2 h-[600px] w-[900px] -translate-x-1/2 -translate-y-1/2" />
      <div className="bg-grid-hairline absolute inset-0" />
      <div className="relative z-10 mx-auto w-full max-w-sm rounded-2xl border border-black/10 bg-white p-8 shadow-xl shadow-black/[0.04]">
        <h1 className="font-jura text-2xl font-bold tracking-tighter">Sign in</h1>
        <p className="mt-1 text-sm text-black/60">Welcome back to Groundwork.</p>

        <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
          <div>
            <label htmlFor="email" className="block text-[11px] font-bold uppercase tracking-widest text-black/45">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-black/10 bg-white px-3 py-2.5 text-sm outline-none transition-colors focus:border-black/40"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-[11px] font-bold uppercase tracking-widest text-black/45">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-black/10 bg-white px-3 py-2.5 text-sm outline-none transition-colors focus:border-black/40"
            />
          </div>

          {error && <p className="text-sm font-medium text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-black px-4 py-3 text-sm font-bold uppercase tracking-widest text-white transition-all hover:bg-black/80 active:scale-[0.98] disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-black/60">
          No account?{" "}
          <Link href="/signup" className="font-bold text-black transition-colors hover:text-brand">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}