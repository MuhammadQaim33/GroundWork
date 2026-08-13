"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { logout } from "@/lib/api";
import { useSession } from "@/lib/use-session";

export default function HeaderNav() {
  const router = useRouter();
  const session = useSession();

  if (!session) {
    return (
      <div className="flex items-center gap-4 text-sm font-medium">
        <Link href="/login" className="text-white/80 transition-colors hover:text-white">
          Sign in
        </Link>
        <Link
          href="/signup"
          className="rounded-md bg-uber-green px-3 py-1.5 font-semibold text-uber-black transition-colors hover:bg-uber-green-dark hover:text-white"
        >
          Sign up
        </Link>
      </div>
    );
  }

  async function onSignOut() {
    await logout();
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="flex items-center gap-6 text-sm font-medium">
      <Link href="/generate" className="text-white/80 transition-colors hover:text-white">
        Generate
      </Link>
      <Link href="/settings" className="text-white/80 transition-colors hover:text-white">
        Settings
      </Link>
      <button
        type="button"
        onClick={onSignOut}
        className="text-white/80 transition-colors hover:text-white"
      >
        Sign out
      </button>
    </div>
  );
}
