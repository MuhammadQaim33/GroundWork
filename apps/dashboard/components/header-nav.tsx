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
      <div className="flex items-center gap-6">
        <Link
          href="/login"
          className="text-xs font-bold uppercase tracking-widest text-black/70 transition-colors hover:text-black"
        >
          Sign in
        </Link>
        <Link
          href="/signup"
          className="rounded-lg bg-black px-5 py-2 text-xs font-bold uppercase tracking-widest text-white transition-all hover:bg-black/80 active:scale-[0.98]"
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
    <div className="flex items-center gap-6">
      <Link
        href="/generate"
        className="text-xs font-bold uppercase tracking-widest text-black/70 transition-colors hover:text-black"
      >
        Generate
      </Link>
      <Link
        href="/settings"
        className="text-xs font-bold uppercase tracking-widest text-black/70 transition-colors hover:text-black"
      >
        Settings
      </Link>
      <button
        type="button"
        onClick={onSignOut}
        className="text-xs font-bold uppercase tracking-widest text-black/50 transition-colors hover:text-black"
      >
        Sign out
      </button>
    </div>
  );
}
