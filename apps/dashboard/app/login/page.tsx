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
    <div className="mx-auto w-full max-w-sm">
      <div className="rounded-lg border border-uber-line bg-background p-6">
        <h1 className="text-2xl font-semibold text-uber-black">Sign in</h1>
        <p className="mt-1 text-sm text-uber-gray">Welcome back to Groundwork.</p>

        <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-uber-black">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-uber-line bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-uber-green"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-uber-black">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-uber-line bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-uber-green"
            />
          </div>

          {error && <p className="text-sm font-medium text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-uber-black px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-uber-green disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-uber-gray">
          No account?{" "}
          <Link href="/signup" className="font-medium text-uber-black hover:text-uber-green-dark">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}
