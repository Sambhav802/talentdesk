import { useCallback, useEffect, useRef, useState } from 'react';
import { Database, FileText, FileUp, LoaderCircle, RefreshCw, Search, Trash2 } from 'lucide-react';
import { api } from '../lib/api.js';

function ScoreBar({ value }) {
  const pct = Math.max(0, Math.min(1, value || 0)) * 100;
  return (
    <span className="flex items-center gap-2">
      <span className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <span className="block h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular-nums">{(value ?? 0).toFixed(3)}</span>
    </span>
  );
}

export default function KnowledgeBase({ role }) {
  const [docs, setDocs] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [uploading, setUploading] = useState(false);
  const [drag, setDrag] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const fileRef = useRef(null);

  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(() => setReloadKey((k) => k + 1), []);
  useEffect(() => {
    let alive = true;
    api.kbDocuments()
      .then((r) => alive && setDocs(r.documents))
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [reloadKey]);

  const upload = async (files) => {
    const list = Array.from(files || []);
    if (!list.length) return;
    setUploading(true); setError(''); setNotice('');
    try {
      for (const f of list) {
        const r = await api.kbUpload(f, role);
        setNotice(`Added "${r.document.title}" (${r.document.chunks} chunks${r.document.embed_model ? `, ${r.document.embed_model}` : ', lexical index'}).`);
      }
      await load();
    } catch (e) { setError(e.message); } finally { setUploading(false); }
  };

  const remove = async (d) => {
    if (!window.confirm(`Remove "${d.title}" from the knowledge base?`)) return;
    try { await api.kbDelete(d.id, role); await load(); } catch (e) { setError(e.message); }
  };

  const reindex = async () => {
    setError(''); setNotice('');
    try { const r = await api.kbReindexJobs(role); setNotice(`Re-indexed ${r.indexed} job openings.`); } catch (e) { setError(e.message); }
  };

  const search = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true); setError('');
    try { setResults(await api.kbSearch(query.trim())); } catch (err) { setError(err.message); } finally { setSearching(false); }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Knowledge base</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Documents the assistant answers from. Policy answers cite these passages; anything not covered is declined.
          </p>
        </div>
        <button className="btn-outline" onClick={reindex}><RefreshCw size={16} /> Re-index job openings</button>
      </div>

      {error && <p className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{error}</p>}
      {notice && <p className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">{notice}</p>}

      <div className="grid gap-6 lg:grid-cols-5">
        <section className="space-y-4 lg:col-span-2" aria-labelledby="kb-docs">
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}
            className={`card flex flex-col items-center gap-2 border-dashed p-6 text-center transition ${drag ? 'border-brand-500 bg-brand-50 dark:bg-brand-950/30' : ''}`}>
            {uploading ? <LoaderCircle className="animate-spin text-brand-600" /> : <FileUp className="text-brand-600" />}
            <p className="text-sm font-medium">Drop HR documents here</p>
            <p className="text-xs text-slate-500">PDF, TXT or Markdown: policies, handbook, FAQs</p>
            <button className="btn-primary mt-1" disabled={uploading} onClick={() => fileRef.current?.click()}>Choose files</button>
            <input ref={fileRef} type="file" multiple accept=".pdf,.txt,.md,.markdown" className="hidden"
                   onChange={(e) => { upload(e.target.files); e.target.value = ''; }} />
          </div>

          <div className="card">
            <h2 id="kb-docs" className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 text-sm font-semibold dark:border-slate-800">
              <Database size={16} /> Documents {docs && <span className="text-slate-400">({docs.length})</span>}
            </h2>
            {!docs ? <p className="p-4 text-sm text-slate-500">Loading…</p> : docs.length === 0 ? (
              <p className="p-4 text-sm text-slate-500">No documents yet. Upload one to get started.</p>
            ) : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {docs.map((d) => (
                  <li key={d.id} className="flex items-start gap-3 px-4 py-3">
                    <FileText size={18} className="mt-0.5 shrink-0 text-slate-400" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium" title={d.title}>{d.title}</p>
                      <p className="text-xs text-slate-500">
                        {d.chunks} chunks · {d.embed_model || 'BM25 only'} · {d.uploaded_at ? new Date(d.uploaded_at).toLocaleDateString() : ''}
                      </p>
                    </div>
                    <button className="btn-danger p-1.5" aria-label={`Delete ${d.title}`} onClick={() => remove(d)}><Trash2 size={16} /></button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="card lg:col-span-3" aria-labelledby="kb-search">
          <h2 id="kb-search" className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 text-sm font-semibold dark:border-slate-800">
            <Search size={16} /> Test retrieval
          </h2>
          <form onSubmit={search} className="flex gap-2 p-4">
            <label htmlFor="kb-q" className="sr-only">Search query</label>
            <input id="kb-q" className="input" placeholder="e.g. How many sick leave days do we get?" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button className="btn-primary" disabled={searching || !query.trim()}>
              {searching ? <LoaderCircle size={16} className="animate-spin" /> : <Search size={16} />} Search
            </button>
          </form>
          {results && (
            <div className="space-y-3 px-4 pb-4">
              <p className="text-xs text-slate-500">
                {results.results.length} passage(s) above the relevance threshold · embeddings: {results.embeddings}
              </p>
              {results.results.length === 0 && (
                <p className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                  Nothing relevant: the assistant would answer that this is not in the knowledge base.
                </p>
              )}
              {results.results.map((r, i) => (
                <article key={r.chunk_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <header className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="font-semibold">[{i + 1}] {r.title}{r.section ? ` · ${r.section}` : ''}</span>
                    <ScoreBar value={r.score} />
                  </header>
                  <p className="whitespace-pre-line text-sm text-slate-700 dark:text-slate-300">{r.text}</p>
                  <footer className="mt-2 text-[11px] text-slate-500">
                    BM25 {r.bm25} · vector {r.vector_score ?? 'n/a'} · chunk {r.chunk_index + 1} · {r.type}
                  </footer>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
