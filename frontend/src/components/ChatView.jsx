import { useEffect, useRef, useState } from 'react';
import { Bot, FileText, Paperclip, Quote, Send, User } from 'lucide-react';
import Markdown from './Markdown.jsx';
import { JobGrid, PolicyCard, StatsCard, Suggestions } from './Cards.jsx';

function stripSources(text, citations) {
  // The UI shows sources as chips, so drop the plain-text "Sources" block the API appends.
  return citations?.length ? text.replace(/\n\n\*\*Sources\*\*[\s\S]*$/, '') : text;
}

function Citations({ citations, openN, setOpenN }) {
  if (!citations?.length) return null;
  const open = citations.find((c) => c.n === openN);
  return (
    <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700">
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        <Quote size={12} /> Sources
      </p>
      <div className="flex flex-wrap gap-1.5">
        {citations.map((c) => (
          <button key={c.n} type="button" onClick={() => setOpenN(openN === c.n ? null : c.n)}
                  aria-expanded={openN === c.n}
                  className={`flex max-w-full items-center gap-1.5 rounded-lg border px-2 py-1 text-left text-xs transition ${
                    openN === c.n
                      ? 'border-brand-300 bg-brand-50 text-brand-800 dark:border-brand-700 dark:bg-brand-950 dark:text-brand-200'
                      : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300'}`}>
            <span className="flex h-4 min-w-4 items-center justify-center rounded bg-brand-600 px-1 text-[10px] font-bold text-white">{c.n}</span>
            <span className="truncate">{c.label || c.title}</span>
          </button>
        ))}
      </div>
      {open && (
        <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-700 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
          <p className="mb-1 font-semibold text-slate-900 dark:text-slate-100">
            [{open.n}] {open.label}
            {typeof open.score === 'number' && <span className="ml-2 font-normal text-slate-500">relevance {open.score.toFixed(2)}</span>}
          </p>
          <p className="whitespace-pre-line">{open.snippet}</p>
        </div>
      )}
    </div>
  );
}

function BotBody({ msg, onSend, openN, setOpenN }) {
  const cards = msg.cards || [];
  const onCite = msg.citations?.length ? (n) => setOpenN(n) : undefined;
  const jobs = cards.filter((c) => c.kind === 'job');
  const policy = cards.find((c) => c.kind === 'policy');
  const stats = cards.find((c) => c.kind === 'stats');
  const apply = onSend ? (job) => onSend(`I want to apply for the ${job.title} job`) : undefined;

  if (jobs.length && msg.intro) {
    // job results: the intro sentence, then cards built from the job records (the markdown list is the fallback)
    const table = msg.type === 'compare' ? msg.text.slice(msg.text.indexOf('|')) : '';
    return (
      <>
        <Markdown text={msg.intro} />
        {table && <Markdown text={table} />}
        <JobGrid jobs={jobs} onApply={apply} />
        {msg.text.includes('…and') && <p className="mt-2 text-xs text-slate-500">{msg.text.match(/…and[^\n]*/)?.[0]}</p>}
      </>
    );
  }
  if (policy) {
    const lead = msg.intro && msg.intro !== policy.key ? msg.intro : '';
    return (
      <>
        {lead && <div className="mb-2"><Markdown text={lead} /></div>}
        <PolicyCard card={policy} onCite={onCite} />
        <Citations citations={msg.citations} openN={openN} setOpenN={setOpenN} />
      </>
    );
  }
  if (stats) {
    return (<><Markdown text={msg.text.split('\n\n')[0]} /><div className="mt-2"><StatsCard card={stats} /></div></>);
  }
  return (
    <>
      <Markdown text={stripSources(msg.text || '', msg.citations)} onCite={onCite} />
      <Citations citations={msg.citations} openN={openN} setOpenN={setOpenN} />
    </>
  );
}

function Message({ msg, onSend, isLast, loading, canApply }) {
  const [openN, setOpenN] = useState(null);
  const isUser = msg.role === 'user';
  const wide = !isUser && (msg.cards || []).some((c) => c.kind === 'job');
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
        isUser ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'bg-brand-600 text-white'}`}
           aria-hidden="true">
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>
      <div className={`min-w-0 rounded-2xl px-4 py-3 ${wide ? 'w-full sm:max-w-[92%]' : 'max-w-[85%] sm:max-w-[75%]'} ${
        isUser
          ? 'rounded-tr-sm bg-brand-600 text-white'
          : `rounded-tl-sm border bg-white text-slate-800 shadow-card dark:bg-slate-900 dark:text-slate-100 ${
            msg.type === 'error' ? 'border-rose-200 dark:border-rose-900' : 'border-slate-200 dark:border-slate-800'}`}`}>
        {isUser ? (
          <p className="whitespace-pre-wrap break-words text-sm">{msg.text}</p>
        ) : (
          <>
            <BotBody msg={msg} onSend={canApply ? onSend : undefined} openN={openN} setOpenN={setOpenN} />
            {isLast && <Suggestions items={msg.suggestions} onSend={onSend} disabled={loading} />}
          </>
        )}
      </div>
    </div>
  );
}

function Typing() {
  return (
    <div className="flex gap-3" role="status" aria-label="Assistant is typing">
      <div className="mt-1 flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-white"><Bot size={16} /></div>
      <div className="flex items-center gap-1 rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-3.5 dark:border-slate-800 dark:bg-slate-900">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-2 w-2 animate-blink rounded-full bg-slate-400" style={{ animationDelay: `${i * 0.15}s` }} />
        ))}
      </div>
    </div>
  );
}

export default function ChatView({ messages, loading, quickReplies, onSend, onUpload, role }) {
  const [input, setInput] = useState('');
  const endRef = useRef(null);
  const listRef = useRef(null);
  const fileRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [messages, loading]);

  const submit = (e) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    onSend(text);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-6 sm:px-6" aria-live="polite">
        <div className="mx-auto flex max-w-3xl flex-col gap-5">
          {messages.map((m, i) => (
            <Message key={i} msg={m} onSend={onSend} loading={loading} canApply={role === 'Candidate'}
                     isLast={i === messages.length - 1 && m.role === 'bot'} />
          ))}
          {loading && <Typing />}
          <div ref={endRef} />
        </div>
      </div>

      <div className="shrink-0 border-t border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
        <div className="mx-auto max-w-3xl px-4 pt-3 sm:px-6">
          <div className="no-scrollbar flex gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
            {quickReplies.map((q) => (
              <button key={q} type="button" disabled={loading} onClick={() => onSend(q)}
                      className="whitespace-nowrap rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:border-brand-300 hover:text-brand-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-700 dark:hover:text-brand-300">
                {q}
              </button>
            ))}
          </div>
        </div>
        <form onSubmit={submit} className="mx-auto flex max-w-3xl items-end gap-2 px-4 pb-4 pt-2 sm:px-6">
          <button type="button" className="btn-outline h-11 w-11 shrink-0 p-0" onClick={() => fileRef.current?.click()}
                  disabled={loading} aria-label="Attach resume (PDF)" title="Attach resume (PDF)">
            <Paperclip size={18} />
          </button>
          <label htmlFor="chat-input" className="sr-only">Message</label>
          <textarea id="chat-input" ref={inputRef} rows={1} value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) submit(e); }}
                    placeholder={`Message as ${role}…`}
                    className="input max-h-40 min-h-[44px] min-w-0 flex-1 resize-none py-3" />
          <button type="submit" className="btn-primary h-11 w-11 shrink-0 p-0" disabled={loading || !input.trim()} aria-label="Send">
            <Send size={18} />
          </button>
          <input ref={fileRef} type="file" accept=".pdf,.doc,.docx" className="hidden"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ''; }} />
        </form>
        <p className="mx-auto -mt-2 max-w-3xl px-4 pb-3 text-[11px] text-slate-400 sm:px-6">
          <FileText size={11} className="mr-1 inline" />Policy answers come only from the HR knowledge base and show their sources.
        </p>
      </div>
    </div>
  );
}
