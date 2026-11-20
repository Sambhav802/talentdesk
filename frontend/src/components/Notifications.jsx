import { useEffect, useRef, useState } from 'react';
import { Bell } from 'lucide-react';

export default function Notifications({ items, onOpen }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button className="btn-ghost relative p-2" onClick={() => setOpen((v) => !v)} aria-expanded={open}
              aria-label={`Notifications${items.length ? ` (${items.length})` : ''}`}>
        <Bell size={18} />
        {items.length > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
            {items.length}
          </span>
        )}
      </button>
      {open && (
        <div className="card absolute right-0 top-11 z-30 w-80 overflow-hidden">
          <p className="border-b border-slate-200 px-4 py-3 text-sm font-semibold dark:border-slate-800">Notifications</p>
          {items.length ? (
            <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800">
              {items.map((n, i) => (
                <li key={i}>
                  <button className="w-full px-4 py-3 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800/60"
                          onClick={() => { setOpen(false); onOpen(n); }}>
                    {n.text}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="px-4 py-8 text-center text-sm text-slate-500">You're all caught up.</p>}
        </div>
      )}
    </div>
  );
}
