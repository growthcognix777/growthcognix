"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Spinner } from "@/components/ui";

export default function Home() {
  const { session, loading } = useAuth(); const router = useRouter();
  useEffect(() => { if (!loading) router.replace(session ? "/dashboard/" : "/login/"); }, [loading, session, router]);
  return <Spinner />;
}
