import { useCallback, useEffect, useMemo, useState } from 'react';
import { BriefcaseBusiness, CircleCheck, CircleX, Clock, Download, Inbox, RefreshCw, Trash2, Users } from 'lucide-react';
import Modal from './Modal.jsx';
import { api, apiUrl, exportUrl } from '../lib/api.js';
import { PIPELINE, statusTone } from '../lib/roles.js';

const FILTERS = {
  all: () => true,
  hired: (s) => s.includes('hired'),
  pending: (s) => s.includes('pending') || s.includes('awaiting'),
  rejected: (s) => s.includes('reject') || s.includes('not suitable') || s.includes('missing'),
};

const EXPORTS = [
  ['pending', 'Pending review'], ['shortlisted', 'Shortlisted'], ['interview_done', 'Interview done'],
  ['hired', 'Hired'], ['rejected', 'Rejected'], ['all_candidates', 'All candidates'], ['hiring_requests', 'Hiring requests'],
];

function Stat({ icon: Icon, label, value, active, tone, onClick }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
            className={`card flex items-center gap-4 p-4 text-left transition hover:-translate-y-0.5 ${active ? 'ring-2 ring-brand-500' : ''}`}>
      <span className={`flex h-11 w-11 items-center justify-center rounded-xl ${tone}`}><Icon size={20} /></span>
      <span>
        <span className="block text-xs font-medium text-slate-500 dark:text-slate-400">{label}</span>
        <span className="text-2xl font-semibold tabular-nums">{value ?? '–'}</span>
      </span>
    </button>
  );
}

function Details({ item, onClose }) {
  if (!item) return null;
  return (
    <Modal title={item.title} onClose={onClose}>
      <dl className="grid gap-3 text-sm">
        {Object.entries(item.data).filter(([k]) => k !== '_id').map(([k, v]) => {
          const value = Array.isArray(v) ? v.join(', ') : v == null || v === '' ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v);
          const isFile = typeof v === 'string' && v.startsWith('uploads/');
          return (
            <div key={k} className="grid grid-cols-3 gap-3 border-b border-slate-100 pb-2 last:border-0 dark:border-slate-800">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{k.replace(/_/g, ' ')}</dt>
              <dd className="col-span-2 break-words">
                {isFile ? <a className="text-brand-600 underline dark:text-brand-400" href={apiUrl(v)} target="_blank" rel="noreferrer">Open file</a> : value}
              </dd>
            </div>
          );
        })}
      </dl>
    </Modal>
  );
}

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('candidates');
  const [filter, setFilter] = useState('all');
  const [details, setDetails] = useState(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [busy, setBusy] = useState('');

  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(() => setReloadKey((k) => k + 1), []);
  useEffect(() => {
    let alive = true;
    api.dashboard()
      .then((d) => { if (alive) { setData(d); setError(''); } })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [reloadKey]);

  const candidates = useMemo(
    () => (data?.candidates || []).filter((c) => FILTERS[filter]((c.screening_status || '').toLowerCase())),
    [data, filter],
  );

  const act = async (key, fn) => {
    setBusy(key);
    try { await fn(); await load(); } catch (e) { setError(e.message); } finally { setBusy(''); }
  };

  const tabs = [
    ['candidates', `Candidates (${data?.candidates?.length ?? 0})`],
    ['requests', `Hiring requests (${data?.requests?.length ?? 0})`],
    ['jobs', `Job openings (${data?.jobs?.length ?? 0})`],
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Hiring dashboard</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Pipeline, requests and open roles at a glance.</p>
        </div>
        <div className="relative flex gap-2">
          <button className="btn-outline" onClick={load}><RefreshCw size={16} /> Refresh</button>
          <button className="btn-primary" onClick={() => setExportOpen((v) => !v)} aria-expanded={exportOpen}><Download size={16} /> Export CSV</button>
          {exportOpen && (
            <div className="card absolute right-0 top-12 z-20 w-56 p-1.5">
              {EXPORTS.map(([val, label]) => (
                <a key={val} href={exportUrl(val)} onClick={() => setExportOpen(false)}
                   className="block rounded-lg px-3 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-800">{label}</a>
              ))}
            </div>
          )}
        </div>
      </div>

      {error && <p className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{error}</p>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat icon={Users} label="Candidates" value={data?.stats?.total} active={filter === 'all' && tab === 'candidates'}
              tone="bg-brand-100 text-brand-700 dark:bg-brand-900/50 dark:text-brand-300" onClick={() => { setFilter('all'); setTab('candidates'); }} />
        <Stat icon={CircleCheck} label="Hired" value={data?.stats?.hired} active={filter === 'hired'}
              tone="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300" onClick={() => { setFilter('hired'); setTab('candidates'); }} />
        <Stat icon={Clock} label="Pending" value={data?.stats?.pending} active={filter === 'pending'}
              tone="bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300" onClick={() => { setFilter('pending'); setTab('candidates'); }} />
        <Stat icon={CircleX} label="Rejected" value={data?.stats?.rejected} active={filter === 'rejected'}
              tone="bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-300" onClick={() => { setFilter('rejected'); setTab('candidates'); }} />
      </div>

      <div className="card overflow-hidden">
        <div className="no-scrollbar flex gap-1 overflow-x-auto border-b border-slate-200 px-2 dark:border-slate-800" role="tablist">
          {tabs.map(([id, label]) => (
            <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
                    className={`whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium transition ${
                      tab === id ? 'border-brand-600 text-brand-700 dark:text-brand-300' : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'}`}>
              {label}
            </button>
          ))}
          {tab === 'candidates' && filter !== 'all' && (
            <button className="ml-auto self-center rounded-full bg-slate-100 px-3 py-1 text-xs dark:bg-slate-800" onClick={() => setFilter('all')}>
              Filter: {filter} ✕
            </button>
          )}
        </div>

        {!data && !error && <p className="p-8 text-center text-sm text-slate-500">Loading…</p>}

        {data && tab === 'candidates' && (
          candidates.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/60">
                  <tr><th className="px-4 py-3 font-semibold">Name</th><th className="px-4 py-3 font-semibold">Role</th>
                    <th className="px-4 py-3 font-semibold">Exp.</th><th className="px-4 py-3 font-semibold">Status</th>
                    <th className="px-4 py-3 font-semibold">Move to</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {candidates.map((c) => (
                    <tr key={c._id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                      <td className="px-4 py-3">
                        <button className="text-left font-medium hover:text-brand-600" onClick={() => setDetails({ title: c.full_name || 'Candidate', data: c })}>
                          {c.full_name || 'Unnamed'}
                          <span className="block text-xs font-normal text-slate-500">{c.email}</span>
                        </button>
                      </td>
                      <td className="px-4 py-3">{c.preferred_role}</td>
                      <td className="px-4 py-3 tabular-nums">{c.total_experience ? `${c.total_experience} yrs` : '—'}</td>
                      <td className="px-4 py-3"><span className={`chip ${statusTone(c.screening_status)}`}>{c.screening_status || 'Pending Review'}</span></td>
                      <td className="px-4 py-3">
                        <label className="sr-only" htmlFor={`st-${c._id}`}>Change status of {c.full_name}</label>
                        <select id={`st-${c._id}`} className="input w-44 py-1.5" disabled={busy === c._id}
                                value={PIPELINE.includes(c.screening_status) ? c.screening_status : ''}
                                onChange={(e) => act(c._id, () => api.setCandidateStatus(c._id, e.target.value))}>
                          <option value="" disabled>Select…</option>
                          {PIPELINE.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty icon={Users} text="No candidates in this view yet." />
        )}

        {data && tab === 'requests' && (
          data.requests.length ? (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.requests.map((r) => (
                <li key={r._id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-4">
                  <button className="text-left" onClick={() => setDetails({ title: r.role_required || 'Hiring request', data: r })}>
                    <span className="font-medium">{r.role_required}</span>
                    <span className="block text-xs text-slate-500">{r.department} · {r.positions} position(s) · {r.job_location} · {r.urgency} urgency · {r.budget}</span>
                  </button>
                  <button className="btn-primary" disabled={busy === r._id} onClick={() => act(r._id, () => api.approveRequest(r._id))}>
                    Approve &amp; post job
                  </button>
                </li>
              ))}
            </ul>
          ) : <Empty icon={Inbox} text="No pending hiring requests." />
        )}

        {data && tab === 'jobs' && (
          data.jobs.length ? (
            <ul className="grid gap-3 p-4 sm:grid-cols-2">
              {data.jobs.map((j) => (
                <li key={j._id} className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                  <div className="min-w-0">
                    <p className="font-medium">{j.title}</p>
                    <p className="text-xs text-slate-500">{j.department} · {j.location} · {j.experience_required} yrs</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {(Array.isArray(j.skills_required) ? j.skills_required : [j.skills_required]).filter(Boolean).slice(0, 5).map((s) => (
                        <span key={s} className="chip bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{s}</span>
                      ))}
                    </div>
                  </div>
                  <button className="btn-danger p-2" aria-label={`Delete ${j.title}`} disabled={busy === j._id}
                          onClick={() => window.confirm(`Delete the opening "${j.title}"?`) && act(j._id, () => api.deleteJob(j._id))}>
                    <Trash2 size={16} />
                  </button>
                </li>
              ))}
            </ul>
          ) : <Empty icon={BriefcaseBusiness} text="No open roles." />
        )}
      </div>
      <Details item={details} onClose={() => setDetails(null)} />
    </div>
  );
}

function Empty({ icon: Icon, text }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-16 text-sm text-slate-500">
      <Icon size={32} className="opacity-30" />{text}
    </div>
  );
}
