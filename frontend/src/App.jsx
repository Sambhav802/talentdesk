import { useCallback, useEffect, useState } from 'react';
import { Menu } from 'lucide-react';
import Sidebar from './components/Sidebar.jsx';
import ChatView from './components/ChatView.jsx';
import Dashboard from './components/Dashboard.jsx';
import KnowledgeBase from './components/KnowledgeBase.jsx';
import AuthDialog from './components/AuthDialog.jsx';
import Notifications from './components/Notifications.jsx';
import { api, newSessionId } from './lib/api.js';
import { roleById } from './lib/roles.js';

const TITLES = { chat: 'Assistant', dashboard: 'Dashboard', kb: 'Knowledge base' };

function readTheme() {
  try { return localStorage.getItem('theme') === 'dark'; } catch { return false; }
}

export default function App() {
  const [role, setRole] = useState('Candidate');
  const [view, setView] = useState('chat');
  const [dark, setDark] = useState(readTheme);
  const [menuOpen, setMenuOpen] = useState(false);

  const [sessionId, setSessionId] = useState(newSessionId);
  const [messages, setMessages] = useState(() => [{ role: 'bot', text: roleById('Candidate').greeting }]);
  const [loading, setLoading] = useState(false);

  const [showAuth, setShowAuth] = useState(true);
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [previous, setPrevious] = useState(null);
  const [notifications, setNotifications] = useState([]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    try { localStorage.setItem('theme', dark ? 'dark' : 'light'); } catch { /* storage unavailable */ }
  }, [dark]);

  const switchRole = (id) => {
    const r = roleById(id);
    setRole(id);
    setView('chat');
    setSessionId(newSessionId());
    setMessages([{ role: 'bot', text: r.greeting }]);
    setEmail(r.demo.email);
    setPhone(r.demo.phone);
    setPrevious(null);
    setNotifications([]);
    setShowAuth(true);
  };

  const login = async () => {
    const res = await api.login(email.trim(), phone.trim(), role);
    if (res.history?.length) {
      setPrevious({ history: res.history, sessionId: res.session_id });
    } else {
      setShowAuth(false);
    }
  };

  const fetchNotifications = useCallback(async () => {
    if (showAuth || (role === 'Candidate' && !email)) return;
    try { setNotifications((await api.notifications(role, email)).notifications || []); } catch { /* offline: keep last */ }
  }, [role, email, showAuth]);

  useEffect(() => {
    fetchNotifications();
    const t = setInterval(fetchNotifications, 15000);
    return () => clearInterval(t);
  }, [fetchNotifications]);

  // Structured reply from /chat: markdown `response` (always complete) plus type, intro, cards, suggestions.
  const botMessage = (res) => ({
    role: 'bot', text: res.response, citations: res.citations || [], type: res.type || 'message',
    intro: res.intro || '', cards: res.cards || [], suggestions: res.suggestions || [],
  });

  const send = async (text) => {
    setMessages((m) => [...m, { role: 'user', text }]);
    setLoading(true);
    try {
      const res = await api.chat(sessionId, text, role);
      setMessages((m) => [...m, botMessage(res)]);
    } catch {
      setMessages((m) => [...m, { role: 'bot', type: 'error', text: 'Sorry, I could not reach the assistant. Please check your connection and try again.' }]);
    } finally {
      setLoading(false);
    }
  };

  const uploadResume = async (file) => {
    setMessages((m) => [...m, { role: 'user', text: `📎 ${file.name}` }]);
    setLoading(true);
    try {
      const { file_url } = await api.uploadResume(file);
      const res = await api.chat(sessionId, file_url, role);
      setMessages((m) => [...m, botMessage(res)]);
    } catch (e) {
      setMessages((m) => [...m, { role: 'bot', type: 'error', text: `Upload failed: ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full">
      <Sidebar role={role} onRole={switchRole} view={view} onView={setView} dark={dark} onTheme={() => setDark((d) => !d)}
               email={showAuth ? '' : email} open={menuOpen} onClose={() => setMenuOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 dark:border-slate-800 dark:bg-slate-900 sm:px-6">
          <div className="flex items-center gap-2">
            <button className="btn-ghost p-2 lg:hidden" onClick={() => setMenuOpen(true)} aria-label="Open menu"><Menu size={18} /></button>
            <h1 className="text-sm font-semibold">{TITLES[view]}</h1>
            <span className="chip bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{role}</span>
          </div>
          <Notifications items={notifications} onOpen={(n) => { setView('chat'); setMessages((m) => [...m, { role: 'bot', text: n.details }]); }} />
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          {view === 'chat' && (
            <ChatView messages={messages} loading={loading} role={role} quickReplies={roleById(role).quick}
                      onSend={send} onUpload={uploadResume} />
          )}
          {view === 'dashboard' && role === 'HR Admin' && <Dashboard />}
          {view === 'kb' && role === 'HR Admin' && <KnowledgeBase role={role} />}
        </main>
      </div>

      {showAuth && (
        <AuthDialog role={role} email={email} phone={phone} setEmail={setEmail} setPhone={setPhone}
                    onSubmit={login} previous={previous} onRole={switchRole}
                    onRestore={() => {
                      setMessages(previous.history);
                      if (previous.sessionId) setSessionId(previous.sessionId);
                      setShowAuth(false);
                    }}
                    onFresh={() => { setMessages([{ role: 'bot', text: 'Welcome back! Starting a fresh conversation.' }]); setShowAuth(false); }} />
      )}
    </div>
  );
}
