import { BarChart3, Briefcase, CalendarClock, IndianRupee, MapPin, ShieldCheck, Users, Wifi } from 'lucide-react';
import Markdown from './Markdown.jsx';

// Structured replies from /chat render as cards. Every value shown here comes from the API's `cards` payload
// (database rows / cited handbook lines), never from free model text.

export function JobCard({ job, onApply, compact = false }) {
  return (
    <article className="flex h-full flex-col rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <header className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold leading-snug text-slate-900 dark:text-slate-50">{job.title}</h3>
        <span className="chip shrink-0 bg-slate-100 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">{job.department}</span>
      </header>
      <dl className="mt-2 grid grid-cols-1 gap-1 text-xs text-slate-600 dark:text-slate-300">
        <div className="flex items-center gap-1.5">
          {job.remote ? <Wifi size={13} aria-hidden="true" /> : <MapPin size={13} aria-hidden="true" />}
          <dt className="sr-only">Location</dt>
          <dd>{job.remote ? 'Remote' : job.location} · {job.employment_type}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <Briefcase size={13} aria-hidden="true" /><dt className="sr-only">Experience</dt><dd>{job.experience}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <IndianRupee size={13} aria-hidden="true" /><dt className="sr-only">Salary</dt>
          <dd className="font-medium text-slate-800 dark:text-slate-100">{job.salary}</dd>
        </div>
        {(job.openings || job.apply_by) && (
          <div className="flex items-center gap-1.5">
            <CalendarClock size={13} aria-hidden="true" /><dt className="sr-only">Openings and deadline</dt>
            <dd>{job.openings ? `${job.openings} opening${job.openings > 1 ? 's' : ''}` : ''}{job.openings && job.apply_by ? ' · ' : ''}{job.apply_by ? `apply by ${job.apply_by}` : ''}</dd>
          </div>
        )}
      </dl>
      {!compact && job.skills?.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1" aria-label="Skills">
          {job.skills.slice(0, 6).map((s) => (
            <li key={s} className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[11px] text-brand-700 dark:bg-brand-950 dark:text-brand-200">{s}</li>
          ))}
        </ul>
      )}
      {!compact && job.description && <p className="mt-2 line-clamp-3 text-xs text-slate-500 dark:text-slate-400">{job.description}</p>}
      {onApply && (
        <div className="mt-auto pt-3">
          <button type="button" onClick={() => onApply(job)}
                  className="btn-primary h-8 w-full px-3 text-xs">Apply</button>
        </div>
      )}
    </article>
  );
}

export function JobGrid({ jobs, onApply }) {
  return (
    <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
      {jobs.map((j) => <JobCard key={j.id || j.title + j.location} job={j} onApply={onApply} />)}
    </div>
  );
}

export function PolicyCard({ card, onCite }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5 dark:border-slate-700 dark:bg-slate-800/50"
             aria-label={card.title}>
      <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-brand-700 dark:text-brand-300">
        <ShieldCheck size={13} aria-hidden="true" /> {card.title}
      </p>
      <Markdown text={card.key} onCite={onCite} />
      {card.points?.length > 0 && (
        <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-300">
          {card.points.map((p, i) => <li key={i}><Markdown text={p} onCite={onCite} inline /></li>)}
        </ul>
      )}
    </section>
  );
}

export function StatsCard({ card }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-3.5 dark:border-slate-700 dark:bg-slate-900" aria-label={card.title}>
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-brand-700 dark:text-brand-300">
        <BarChart3 size={13} aria-hidden="true" /> {card.title}
      </p>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {card.rows.map((r) => (
          <div key={r.label} className="rounded-lg bg-slate-50 p-2 dark:bg-slate-800">
            <dt className="text-[11px] text-slate-500 dark:text-slate-400">{r.label}</dt>
            <dd className="text-lg font-semibold text-slate-900 dark:text-slate-50">{r.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
        <Users size={13} aria-hidden="true" /> {card.total} candidates · {card.open_roles} open roles · {card.pending_requests} pending requests
      </p>
    </section>
  );
}

export function Suggestions({ items, onSend, disabled }) {
  if (!items?.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Suggested follow-ups">
      {items.map((s) => (
        <button key={s} type="button" disabled={disabled} onClick={() => onSend(s)}
                className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 transition hover:bg-brand-100 disabled:opacity-50 dark:border-brand-800 dark:bg-brand-950 dark:text-brand-200">
          {s}
        </button>
      ))}
    </div>
  );
}
