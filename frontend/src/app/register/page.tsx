"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthLayout } from "@/components/AuthLayout";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ApiError, type FieldError } from "@/lib/types";
import { validateRegister } from "@/lib/validate";

export default function RegisterPage() {
  const { setSession } = useAuth(); const router = useRouter();
  const [v, setV] = useState({ agency_name: "", full_name: "", email: "", password: "" });
  const [errs, setErrs] = useState<FieldError[]>([]); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const fe = (f: string) => errs.find((e) => e.field === f)?.message;
  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null);
    const ve = validateRegister(v); setErrs(ve); if (ve.length) return;
    setBusy(true);
    try { setSession(await api.register(v)); router.replace("/dashboard/"); }
    catch (e) { if (e instanceof ApiError) { setErr(e.message); setErrs(e.errors); } else setErr("Registration failed"); } finally { setBusy(false); }
  };

  return (
    <AuthLayout title="Create your agency" subtitle="You'll be the owner. Invite your team from Settings.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {err && <div className="-m-5 mb-0"><ErrorBox message={err} /></div>}
        <Field label="Agency name" required error={fe("agency_name")}><Input value={v.agency_name} onChange={set("agency_name")} invalid={!!fe("agency_name")} /></Field>
        <Field label="Your full name" required error={fe("full_name")}><Input autoComplete="name" value={v.full_name} onChange={set("full_name")} invalid={!!fe("full_name")} /></Field>
        <Field label="Work email" required error={fe("email")}><Input type="email" autoComplete="email" value={v.email} onChange={set("email")} invalid={!!fe("email")} /></Field>
        <Field label="Password" required error={fe("password")} hint="At least 8 characters, with letters and numbers">
          <Input type="password" autoComplete="new-password" value={v.password} onChange={set("password")} invalid={!!fe("password")} /></Field>
        <Button type="submit" loading={busy} className="w-full">Create agency</Button>
      </form>
      <p className="mt-6 text-sm text-navy-500">Already registered? <Link href="/login/" className="font-medium text-brand-600 hover:underline">Sign in</Link></p>
    </AuthLayout>
  );
}
