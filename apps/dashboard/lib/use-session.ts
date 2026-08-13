"use client";

import { useSyncExternalStore } from "react";
import { getSession } from "@/lib/session";

const SESSION_EVENT = "groundwork:session-changed";

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(SESSION_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(SESSION_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function useSession() {
  return useSyncExternalStore(subscribe, getSession, () => null);
}
