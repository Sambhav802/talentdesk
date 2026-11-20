import { useState } from 'react';
import { History, LoaderCircle, Plus } from 'lucide-react';
import Modal from './Modal.jsx';
import { ROLES } from '../lib/roles.js';

export default function AuthDialog({ role, email, phone, setEmail, setPhone, onSubmit, previous, onRestore, onFresh, onRole }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try { await onSubmit(); } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <Modal title={`${role} sign in`} size="sm" dismissible={false}>
      {!previous ? (
        <form onSubmit={submit} className="space-y-4">
          <p className="text-sm text-slate-500 dark:text-slate-400">Enter your details to continue. We use them to find your earlier conversations.</p>
          <div>
            <label htmlFor="auth-email" className="label">Email</label>
            <input id="auth-email" type="email" required className="input" value={email} autoComplete="email"
                   onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </div>
          <div>
            <label htmlFor="auth-phone" className="label">Phone</label>
            <input id="auth-phone" type="tel" required className="input" value={phone} autoComplete="tel"
                   onChange={(e) => setPhone(e.target.value)} placeholder="9876543210" />
          </div>
          {error && <p className="text-sm text-rose-600">{error}</p>}
          <button type="submit" className="btn-primary w-full py-2.5" disabled={busy || !email || !phone}>
            {busy && <LoaderCircle size={16} className="animate-spin" />} Continue
          </button>
        </form>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600 dark:text-slate-300">Welcome back! Pick up your last conversation or start a new one.</p>
          <button className="btn-primary w-full py-2.5" onClick={onRestore}><History size={16} /> Continue previous chat</button>
          <button className="btn-outline w-full py-2.5" onClick={onFresh}><Plus size={16} /> Start a new chat</button>
        </div>
      )}
      <div className="mt-6 border-t border-slate-200 pt-4 dark:border-slate-800">
        <p className="label text-center">Switch role</p>
        <div className="flex flex-wrap justify-center gap-2">
          {ROLES.map((r) => (
            <button key={r.id} onClick={() => onRole(r.id)} aria-pressed={r.id === role}
                    className={`chip px-3 py-1 ${r.id === role ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'}`}>
              {r.label}
            </button>
          ))}
        </div>
        {role !== 'Candidate' && <p className="mt-3 text-center text-xs text-slate-500">Demo credentials are pre-filled for this role.</p>}
      </div>
    </Modal>
  );
}
