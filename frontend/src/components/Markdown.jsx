import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Renders bot markdown safely (no raw HTML). `[n]` markers become clickable citation buttons when
// `onCite` is given.
export default function Markdown({ text, onCite }) {
  const source = onCite ? text.replace(/\[(\d{1,2})\](?!\()/g, '[[$1]](#cite-$1)') : text;
  return (
    <div className="prose-chat break-words text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href = '', children }) {
            if (onCite && href.startsWith('#cite-')) {
              const n = Number(href.slice(6));
              return (
                <button type="button" onClick={() => onCite(n)}
                        className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-brand-100 px-1 align-text-top text-[11px] font-semibold text-brand-700 no-underline hover:bg-brand-200 dark:bg-brand-900/60 dark:text-brand-200"
                        aria-label={`Show source ${n}`}>
                  {n}
                </button>
              );
            }
            return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
