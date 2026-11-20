import { BookOpen, LayoutDashboard, MessageSquareText, Moon, ShieldCheck, Sparkles, Sun, UserCog, UserRound, X } from 'lucide-react';
import { ROLES } from '../lib/roles.js';

const ROLE_ICON = { Candidate: UserRound, 'Hiring Manager': UserCog, 'HR Admin': ShieldCheck };

export default function Sidebar({ role, onRole, view, onView, dark, onTheme, email, open, onClose }) {
  const nav = [
    { id: 'chat', label: 'Assistant', icon: MessageSquareText, show: true },
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, show: role === 'HR Admin' },
    { id: 'kb', label: 'Knowledge base', icon: BookOpen, show: role === 'HR Admin' },
  ].filter((n) => n.show);

  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-slate-950/40 lg:hidden" onClick={onClose} aria-hidden="true" />}
      <aside className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200 bg-white transition-transform dark:border-slate-800 dark:bg-slate-900 lg:static lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}
             aria-label="Sidebar">
        <div className="flex items-center justify-between px-5 py-5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white"><Sparkles size={18} /></span>
            <div>
              <p className="text-sm font-semibold leading-tight">TalentDesk</p>
              <p className="text-xs text-slate-500">AI HR assistant</p>
            </div>
          </div>
          <button className="btn-ghost p-2 lg:hidden" onClick={onClose} aria-label="Close menu"><X size={18} /></button>
        </div>

        <nav className="space-y-1 px-3" aria-label="Main">
          {nav.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => { onView(id); onClose(); }} aria-current={view === id ? 'page' : undefined}
                    className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                      view === id ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-300' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
              <Icon size={18} /> {label}
            </button>
          ))}
        </nav>

        <div className="mt-6 px-5">
          <p className="label">Signed in as</p>
        </div>
        <div className="space-y-1.5 px-3" role="radiogroup" aria-label="Role">
          {ROLES.map((r) => {
            const Icon = ROLE_ICON[r.id];
            const active = role === r.id;
            return (
              <button key={r.id} role="radio" aria-checked={active} onClick={() => { onRole(r.id); onClose(); }}
                      className={`flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition ${
                        active ? 'border-brand-300 bg-brand-50/60 dark:border-brand-800 dark:bg-brand-950/40' : 'border-transparent hover:bg-slate-100 dark:hover:bg-slate-800'}`}>
                <Icon size={18} className={active ? 'mt-0.5 text-brand-600' : 'mt-0.5 text-slate-400'} />
                <span>
                  <span className="block text-sm font-medium">{r.label}</span>
                  <span className="block text-xs text-slate-500">{r.blurb}</span>
                </span>
              </button>
            );
          })}
        </div>

        <div className="mt-auto space-y-3 border-t border-slate-200 p-4 dark:border-slate-800">
          {email && <p className="truncate text-xs text-slate-500" title={email}>{email}</p>}
          <button className="btn-outline w-full" onClick={onTheme}>
            {dark ? <Sun size={16} /> : <Moon size={16} />} {dark ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      </aside>
    </>
  );
}
