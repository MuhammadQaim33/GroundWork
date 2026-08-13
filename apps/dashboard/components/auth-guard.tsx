"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useSession } from "@/lib/use-session";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const session = useSession();

  useEffect(() => {
    if (!session) router.replace("/login");
  }, [router, session]);

  if (!session) return null;
  return <>{children}</>;
}
