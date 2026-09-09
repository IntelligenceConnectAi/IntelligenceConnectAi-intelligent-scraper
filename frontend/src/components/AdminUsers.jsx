import { useEffect, useState } from "react";
import { api } from "../lib/api";

const ALL_PERMISSIONS = ["operations_admin", "people_leads_admin", "support_admin", "billing_admin"];

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function CreateAdminForm({ onCreated }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [platformRole, setPlatformRole] = useState("admin");
  const [permissions, setPermissions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const togglePerm = (key) => setPermissions(p => p.includes(key) ? p.filter(x => x !== key) : [...p, key]);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      await api.adminCreateUser({ email: email.trim(), password, full_name: fullName.trim(), platform_role: platformRole, permissions });
      setEmail(""); setPassword(""); setFullName(""); setPlatformRole("admin"); setPermissions([]);
      onCreated();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card p-5">
      <p className="label mb-4">Create Admin</p>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <input value={email} onChange={e => setEmail(e.target.value)} type="email" required placeholder="email@example.com" className="input" />
          <input value={password} onChange={e => setPassword(e.target.value)} type="password" required placeholder="Password (min 8 chars)" className="input" />
          <input value={fullName} onChange={e => setFullName(e.target.value)} required placeholder="Full name" className="input" />
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <select value={platformRole} onChange={e => setPlatformRole(e.target.value)} className="input" style={{ width: "auto" }}>
            <option value="admin">Admin</option>
            <option value="super_admin">Super Admin</option>
          </select>
          <div className="flex flex-wrap gap-2">
            {ALL_PERMISSIONS.map(p => (
              <label key={p} className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-2)" }}>
                <input type="checkbox" checked={permissions.includes(p)} onChange={() => togglePerm(p)} />
                {p.replace(/_/g, " ")}
              </label>
            ))}
          </div>
        </div>
        {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
        <button type="submit" disabled={loading} className="btn-primary">{loading ? "Creating…" : "Create Admin"}</button>
      </form>
    </div>
  );
}

function UserRow({ user, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const togglePermission = async (key) => {
    setBusy(true);
    try {
      const action = user.permissions.includes(key) ? "revoke" : "grant";
      await api.adminUpdatePermission(user.id, key, action);
      onChanged();
    } catch (e) {
      alert(`Failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async () => {
    setBusy(true);
    try {
      if (user.is_active) await api.adminDisableUser(user.id);
      else await api.adminEnableUser(user.id);
      onChanged();
    } catch (e) {
      alert(`Failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <tr style={{ borderTop: "1px solid var(--border)" }}>
        <td className="px-4 py-3 text-sm" style={{ color: "var(--text)" }}>{user.full_name || "—"}</td>
        <td className="px-4 py-3 text-xs" style={{ color: "var(--text-2)" }}>{user.email}</td>
        <td className="px-4 py-3"><span className={`badge ${user.platform_role === "super_admin" ? "badge-accent" : "badge-muted"}`}>{user.platform_role}</span></td>
        <td className="px-4 py-3"><span className={`badge ${user.is_active ? "badge-accent" : "badge-danger"}`}>{user.is_active ? "Active" : "Disabled"}</span></td>
        <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(user.created_at)}</td>
        <td className="px-4 py-3">
          <div className="flex gap-1.5">
            <button onClick={() => setExpanded(e => !e)} className="badge badge-muted cursor-pointer hover:opacity-80 transition">
              {expanded ? "Hide" : "Permissions"}
            </button>
            <button onClick={toggleActive} disabled={busy} className={`badge ${user.is_active ? "badge-danger" : "badge-accent"} cursor-pointer hover:opacity-80 transition disabled:opacity-40`}>
              {user.is_active ? "Disable" : "Enable"}
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr style={{ borderTop: "1px solid var(--border)" }}>
          <td colSpan={6} className="px-4 py-3" style={{ background: "var(--bg-secondary)" }}>
            <div className="flex flex-wrap gap-3">
              {ALL_PERMISSIONS.map(p => (
                <label key={p} className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-2)" }}>
                  <input type="checkbox" checked={user.permissions.includes(p)} disabled={busy || user.platform_role === "super_admin"}
                    onChange={() => togglePermission(p)} />
                  {p.replace(/_/g, " ")}
                </label>
              ))}
              {user.platform_role === "super_admin" && (
                <span className="text-xs" style={{ color: "var(--text-3)" }}>Super admins implicitly hold all permissions.</span>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function AdminUsers() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true); setError("");
    try { setUsers(await api.adminListUsers()); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-5 animate-fade-in">
      <CreateAdminForm onCreated={load} />

      {loading ? (
        <div className="card p-10 text-center animate-soft-pulse">
          <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading admins…</p>
        </div>
      ) : error ? (
        <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>
      ) : (
        <div className="card overflow-hidden">
          <div className="px-5 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Admin Roster</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Name", "Email", "Role", "Status", "Created", ""].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map(u => <UserRow key={u.id} user={u} onChanged={load} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
