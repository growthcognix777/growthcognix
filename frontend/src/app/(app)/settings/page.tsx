"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CardHeader, ErrorBox, Field, Input, Modal, PageHeader, Select, Skeleton, Table } from "@/components/ui";
import { api, DATA_MODE } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { ApiError, type FieldError, type Role } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";

export default function SettingsPage() {
  const { session, refresh } = useAuth();
  const isAdmin = session && ["owner", "admin"].includes(session.user.role);
  const agency = useAsync(() => api.getAgency()); const users = useAsync(() => api.listUsers());
  const [a, setA] = useState({ name: "", website: "", phone: "", address: "" }); const [saved, setSaved] = useState(false); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState(false); const [nu, setNu] = useState({ full_name: "", email: "", password: "", role: "staff" as Role }); const [ue, setUe] = useState<FieldError[]>([]); const [uerr, setUerr] = useState<string | null>(null);
  useEffect(() => { if (agency.data) setA({ name: agency.data.name, website: agency.data.website || "", phone: agency.data.phone || "", address: agency.data.address || "" }); }, [agency.data]);

  const saveAgency = async (e: React.FormEvent) => { e.preventDefault(); setBusy(true); setErr(null); setSaved(false);
    try { await api.updateAgency(a); setSaved(true); refresh(); } catch (e) { setErr(e instanceof Error ? e.message : "Save failed"); } finally { setBusy(false); } };
  const addUser = async (e: React.FormEvent) => { e.preventDefault(); setUerr(null);
    try { await api.createUser(nu); setInvite(false); setNu({ full_name: "", email: "", password: "", role: "staff" }); users.reload(); }
    catch (e) { if (e instanceof ApiError) { setUerr(e.message); setUe(e.errors); } } };
  const fe = (f: string) => ue.find((x) => x.field === f)?.message;

  return (
    <>
      <PageHeader title="Settings" subtitle="Agency profile, team and security." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader title="Agency profile" subtitle={isAdmin ? undefined : "Only owners and admins can edit this."} />
          {agency.loading ? <Skeleton rows={3} /> : (
            <form onSubmit={saveAgency} className="grid gap-4 p-5 md:grid-cols-2">
              {err && <div className="md:col-span-2 -m-5 mb-0"><ErrorBox message={err} /></div>}
              <Field label="Agency name"><Input disabled={!isAdmin} value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} /></Field>
              <Field label="Website"><Input disabled={!isAdmin} value={a.website} onChange={(e) => setA({ ...a, website: e.target.value })} /></Field>
              <Field label="Phone"><Input disabled={!isAdmin} value={a.phone} onChange={(e) => setA({ ...a, phone: e.target.value })} /></Field>
              <Field label="Address"><Input disabled={!isAdmin} value={a.address} onChange={(e) => setA({ ...a, address: e.target.value })} /></Field>
              {isAdmin && <div className="flex items-center justify-end gap-3 md:col-span-2">{saved && <span className="text-sm text-emerald-600">Saved</span>}<Button type="submit" loading={busy}>Save profile</Button></div>}
            </form>)}
        </Card>
        <Card><CardHeader title="Security" />
          <div className="space-y-3 p-5 text-sm text-navy-700">
            <div className="flex justify-between"><span>Data mode</span><Badge tone={DATA_MODE === "local" ? "amber" : "green"}>{DATA_MODE === "local" ? "Browser sandbox" : "API"}</Badge></div>
            <div className="flex justify-between"><span>Session storage</span><span className="text-navy-500">Tab session</span></div>
            <p className="text-xs text-navy-500">This is a local development foundation. Before public deployment: refresh tokens in httpOnly cookies, rate limiting, invite-only registration, file scanning, backups, HTTPS and secret management.</p>
          </div>
        </Card>
      </div>
      <Card className="mt-6"><CardHeader title="Team" subtitle="Roles: owner, admin, manager, staff." action={isAdmin && <Button size="sm" onClick={() => setInvite(true)}>Add member</Button>} />
        {users.loading ? <Skeleton rows={2} /> : users.error ? <ErrorBox message={users.error} /> : (
          <Table head={["Name", "Email", "Role", "Joined"]}>
            {users.data!.map((u) => (
              <tr key={u.id}><td className="px-5 py-3 font-medium text-navy-950">{u.full_name}{u.id === session?.user.id && <span className="ml-2 text-xs text-navy-400">(you)</span>}</td><td className="px-5 py-3 text-navy-700">{u.email}</td>
                <td className="px-5 py-3">{isAdmin && u.id !== session?.user.id && u.role !== "owner" ? (
                  <Select className="h-8 w-32" value={u.role} onChange={(e) => api.changeRole(u.id, e.target.value as Role).then(users.reload).catch((x) => alert(x.message))}>
                    {(["admin", "manager", "staff"] as Role[]).map((r) => <option key={r} value={r}>{r}</option>)}</Select>) : <Badge tone={u.role === "owner" ? "violet" : "slate"}>{u.role}</Badge>}</td>
                <td className="px-5 py-3 text-navy-500">{fmtDate(u.created_at)}</td></tr>))}
          </Table>)}
      </Card>
      <Modal open={invite} onClose={() => setInvite(false)} title="Add team member">
        <form onSubmit={addUser} className="space-y-4" noValidate>
          {uerr && <div className="-m-5 mb-0"><ErrorBox message={uerr} /></div>}
          <Field label="Full name" error={fe("full_name")}><Input value={nu.full_name} onChange={(e) => setNu({ ...nu, full_name: e.target.value })} /></Field>
          <Field label="Email" error={fe("email")}><Input type="email" value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} /></Field>
          <Field label="Temporary password" error={fe("password")} hint="Share it securely; invitations by email arrive with production hardening."><Input type="password" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} /></Field>
          <Field label="Role"><Select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value as Role })}>{(["admin", "manager", "staff"] as Role[]).map((r) => <option key={r} value={r}>{r}</option>)}</Select></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setInvite(false)}>Cancel</Button><Button type="submit">Add member</Button></div>
        </form>
      </Modal>
    </>
  );
}
