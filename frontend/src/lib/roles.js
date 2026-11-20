// Roles are selected in the UI (the app has no real authentication; see README).
export const ROLES = [
  {
    id: 'Candidate',
    label: 'Candidate',
    blurb: 'Browse roles, apply, track status',
    demo: { email: '', phone: '' },
    quick: ['View job openings', 'Apply for a job', 'Check application status', 'What is the interview process?'],
    greeting: 'Hi! I can show open roles, help you apply (your resume can autofill the form) and answer questions about our hiring process and policies.',
  },
  {
    id: 'Hiring Manager',
    label: 'Hiring Manager',
    blurb: 'Raise hiring requests',
    demo: { email: 'hrm@abc.com', phone: '1111111111' },
    quick: ['I want to raise a hiring request', 'What is the referral bonus?', 'How long is probation?'],
    greeting: 'Hello! I can raise a hiring request for your team or answer HR policy questions from the handbook.',
  },
  {
    id: 'HR Admin',
    label: 'HR Admin',
    blurb: 'Dashboard, pipeline, knowledge base',
    demo: { email: 'hradmin@abc.com', phone: '0000000000' },
    quick: ['Pending hiring requests', 'Shortlisted candidates', 'Show rejected candidates', 'Generate job description', 'What is the notice period policy?'],
    greeting: 'Welcome back. Ask about candidates and requests, generate a JD, or ask anything covered by the HR knowledge base.',
  },
];

export const roleById = (id) => ROLES.find((r) => r.id === id) || ROLES[0];

export const PIPELINE = ['Pending Review', 'Shortlisted for next step', 'Interview Done', 'Hired', 'Rejected'];

export function statusTone(status = '') {
  const s = status.toLowerCase();
  if (s.includes('hired')) return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
  if (s.includes('interview')) return 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300';
  if (s.includes('shortlist')) return 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300';
  if (s.includes('reject') || s.includes('not suitable') || s.includes('missing'))
    return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300';
  return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
}
