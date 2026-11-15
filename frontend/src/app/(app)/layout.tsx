"use client";
import { AppShell } from "@/components/AppShell";
import { Spinner } from "@/components/ui";
import { useRequireAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { session, loading } = useRequireAuth();
  if (loading || !session) return <Spinner label="Checking your session" />;
  return <AppShell>{children}</AppShell>;
}
