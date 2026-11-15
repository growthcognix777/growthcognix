"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthLayout } from "@/components/AuthLayout";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/types";
import { isEmail } from "@/lib/validate";

export default function LoginPage() {
  const { session, setSession } = useAuth(); const router = useRouter();
  const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false); const [touched, setTouched] = useState(false);
  useEffect(() => { if (session) router.replace("/dashboard/"); }, [session, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setTouched(true); setErr(null);
    if (!isEmail(email) || !password) return;
    setBusy(true);
    try { setSession(await api.login({ email, password })); router.replace("/dashboard/"); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Sign-in failed"); } finally { setBusy(false); }
  };

  return (
    <AuthLayout title="Sign in" subtitle="Welcome back. Sign in to your agency workspace.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {err && <div className="-m-5 mb-0"><ErrorBox message={err} /></div>}
        <Field label="Work email" error={touched && !isEmail(email) ? "Enter a valid email address" : undefined}>
          <Input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} invalid={touched && !isEmail(email)} />
        </Field>
        <Field label="Password" error={touched && !password ? "Enter your password" : undefined}>
          <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} invalid={touched && !password} />
        </Field>
        <Button type="submit" loading={busy} className="w-full">Sign in</Button>
      </form>
      <p className="mt-6 text-sm text-navy-500">New agency? <Link href="/register/" className="font-medium text-brand-600 hover:underline">Create an account</Link></p>
    </AuthLayout>
  );
}
