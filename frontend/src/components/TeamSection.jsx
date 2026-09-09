import { useEffect, useState } from "react";
import { api } from "../lib/api";

const ROLE_LABELS = {
  account_owner: "Account Owner",
  client_admin: "Client Admin",
  client_member: "Client Member",
};

function RoleBadge({ role }) {
  const cls = role === "account_owner" ? "badge-accent" : role === "client_admin" ? "badge-warning" : "badge-muted";
  return <span className={`badge ${cls}`}>{ROLE_LABELS[role] || role}</span>;
}

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function TeamSection() {
  const [org, setOrg] = useState(null);
  const [members, setMembers] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("client_member");
  const [inviting, setInviting] = useState(false);
  const [inviteError, setInviteError] = useState("");
  const [newLink, setNewLink] = useState("");
  const [copied, setCopied] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const canManageTeam = org && (org.my_role === "account_owner" || org.my_role === "client_admin");
  const isOwner = org?.my_role === "account_owner";

  const loadAll = async () => {
    setLoading(true); setError("");
    try {
      const [o, m] = await Promise.all([api.getOrganization(), api.listMembers()]);
      setOrg(o); setMembers(m);
      if (o.my_role === "account_owner" || o.my_role === "client_admin") {
        setInvitations(await api.listInvitations());
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const handleInvite = async (e) => {
    e.preventDefault();
    setInviting(true); setInviteError(""); setNewLink("");
    try {
      const res = await api.createInvitation(inviteEmail.trim(), inviteRole);
      setNewLink(res.invite_link);
      setInviteEmail("");
      await loadAll();
    } catch (e2) {
      setInviteError(e2.message);
    } finally {
      setInviting(false);
    }
  };

  const handleResend = async (id) => {
    setBusyId(id);
    try {
      const res = await api.resendInvitation(id);
      setNewLink(res.invite_link);
      await loadAll();
    } catch (e) {
      alert(`Resend failed: ${e.message}`);
    } finally {
      setBusyId(null);
    }
  };

  const handleCancelInvite = async (id) => {
    if (!confirm("Cancel this invitation?")) return;
    setBusyId(id);
    try { await api.cancelInvitation(id); await loadAll(); }
    catch (e) { alert(`Cancel failed: ${e.message}`); }
    finally { setBusyId(null); }
  };

  const handleRoleChange = async (memberId, role) => {
    setBusyId(memberId);
    try { await api.updateMemberRole(memberId, role); await loadAll(); }
    catch (e) { alert(`Role change failed: ${e.message}`); }
    finally { setBusyId(null); }
  };

  const handleRemove = async (memberId) => {
    if (!confirm("Remove this team member? They will lose access immediately.")) return;
    setBusyId(memberId);
    try { await api.removeMember(memberId); await loadAll(); }
    catch (e) { alert(`Remove failed: ${e.message}`); }
    finally { setBusyId(null); }
  };

  const copyLink = () => {
    navigator.clipboard.writeText(newLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading team…</p>
    </div>
  );

  if (error) return (
    <div className="alert-danger">{error}</div>
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <p className="label" style={{ marginBottom: 0 }}>Team Seats</p>
          <span className="badge badge-accent mono">
            {org.seats_used} / {org.max_team_seats ?? "Unlimited"}
          </span>
        </div>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          {org.max_team_seats != null
            ? `${org.seats_remaining} seat${org.seats_remaining === 1 ? "" : "s"} remaining (active members + pending invitations).`
            : "Your plan includes unlimited team seats."}
        </p>
      </div>

      <div className="p-3 rounded-lg text-xs" style={{
        background: "rgba(96,165,250,0.08)", border: "1px solid rgba(96,165,250,0.2)", color: "var(--text-2)"
      }}>
        Team members can view all organization activity and submit People Leads requests.
        Business Leads submission currently requires the account owner's subscription —
        full team-wide submission is planned for a future update.
      </div>

      {canManageTeam && (
        <div className="card p-5">
          <p className="label mb-4">Invite a Team Member</p>
          <form onSubmit={handleInvite} className="flex flex-col sm:flex-row gap-2">
            <input type="email" required value={inviteEmail} onChange={e => setInviteEmail(e.target.value)}
              placeholder="teammate@example.com" className="input flex-1" />
            <select value={inviteRole} onChange={e => setInviteRole(e.target.value)}
              className="input sm:w-44" disabled={!isOwner}>
              <option value="client_member">Client Member</option>
              {isOwner && <option value="client_admin">Client Admin</option>}
            </select>
            <button type="submit" disabled={inviting || !inviteEmail.trim()} className="btn-primary shrink-0">
              {inviting ? "Inviting…" : "Send Invite"}
            </button>
          </form>
          {inviteError && <p className="text-xs mt-2" style={{ color: "var(--danger)" }}>{inviteError}</p>}
          {newLink && (
            <div className="mt-3 p-3 rounded-lg flex items-center gap-2" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
              <input readOnly value={newLink} className="input flex-1 text-xs mono" style={{ padding: "6px 8px" }} />
              <button type="button" onClick={copyLink} className="btn-ghost text-xs shrink-0">
                {copied ? "Copied ✓" : "Copy link"}
              </button>
            </div>
          )}
          {newLink && (
            <p className="text-xs mt-2" style={{ color: "var(--text-3)" }}>
              Share this link directly — invitations aren't emailed automatically.
            </p>
          )}
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-5 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
          <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Members</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Name", "Email", "Role", "Joined", ""].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {members.map((m, i) => {
                const canRemove = m.role !== "account_owner" && (isOwner || (org.my_role === "client_admin" && m.role === "client_member"));
                return (
                  <tr key={m.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                    <td className="px-4 py-3 text-sm font-medium" style={{ color: "var(--text)" }}>{m.full_name || "—"}</td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-2)" }}>{m.email}</td>
                    <td className="px-4 py-3">
                      {isOwner && m.role !== "account_owner" ? (
                        <select value={m.role} onChange={e => handleRoleChange(m.id, e.target.value)}
                          disabled={busyId === m.id} className="input text-xs" style={{ padding: "4px 8px" }}>
                          <option value="client_admin">Client Admin</option>
                          <option value="client_member">Client Member</option>
                        </select>
                      ) : (
                        <RoleBadge role={m.role} />
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(m.created_at)}</td>
                    <td className="px-4 py-3">
                      {canRemove && (
                        <button onClick={() => handleRemove(m.id)} disabled={busyId === m.id}
                          className="badge badge-danger cursor-pointer hover:opacity-80 transition disabled:opacity-40">
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {canManageTeam && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Pending Invitations</p>
          </div>
          {invitations.length === 0 ? (
            <p className="text-sm p-5" style={{ color: "var(--text-3)" }}>No pending invitations.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)" }}>
                    {["Email", "Role", "Expires", ""].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {invitations.map((inv, i) => (
                    <tr key={inv.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                      <td className="px-4 py-3 text-sm" style={{ color: "var(--text)" }}>{inv.email}</td>
                      <td className="px-4 py-3"><RoleBadge role={inv.role} /></td>
                      <td className="px-4 py-3 text-xs" style={{ color: inv.is_expired ? "var(--danger)" : "var(--text-3)" }}>
                        {inv.is_expired ? "Expired" : fmt(inv.expires_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1.5">
                          <button onClick={() => handleResend(inv.id)} disabled={busyId === inv.id}
                            className="badge badge-muted cursor-pointer hover:opacity-80 transition disabled:opacity-40">
                            Resend
                          </button>
                          <button onClick={() => handleCancelInvite(inv.id)} disabled={busyId === inv.id}
                            className="badge badge-danger cursor-pointer hover:opacity-80 transition disabled:opacity-40">
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
