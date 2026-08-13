"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { signup } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await signup(email.trim(), password);
      router.replace("/generate");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign up failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-sm">
      <div className="rounded-lg border border-uber-line bg-background p-6">
        <h1 className="text-2xl font-semibold text-uber-black">Create account</h1>
        <p className="mt-1 text-sm text-uber-gray">Set up your Groundwork account.</p>

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
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-uber-line bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-uber-green"
            />
            <p className="mt-1 text-xs text-uber-gray">At least 8 characters.</p>
          </div>
          <div>
            <label htmlFor="confirm" className="block text-sm font-medium text-uber-black">
              Confirm password
            </label>
            <input
              id="confirm"
              type="password"
              required
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="mt-1 w-full rounded-md border border-uber-line bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-uber-green"
            />
          </div>

          {error && <p className="text-sm font-medium text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-uber-black px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-uber-green disabled:opacity-50"
          >
            {busy ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-uber-gray">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-uber-black hover:text-uber-green-dark">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
