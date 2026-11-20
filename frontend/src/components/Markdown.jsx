import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Renders bot markdown safely: react-markdown never renders raw HTML (no rehype-raw), links open in a new tab
// with rel="noreferrer", and only http(s)/mailto links are kept. `[n]` markers become clickable citation buttons
// when `onCite` is given. `inline` renders a single paragraph without block margins (for card bullet points).
const SAFE_URL = /^(https?:|mailto:|#cite-)/i;

export default function Markdown({ text, onCite, inline = false }) {
  const source = onCite ? text.replace(/\[(\d{1,2})\](?!\()/g, '[[$1]](#cite-$1)') : text;
  const Wrap = inline ? 'span' : 'div';
  return (
    <Wrap className={`prose-chat break-words leading-relaxed ${inline ? '' : 'text-sm'}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p({ children }) {
            return inline ? <>{children}</> : <p>{children}</p>;
          },
          table({ children }) {
            return <div className="my-2 overflow-x-auto"><table className="min-w-full text-xs">{children}</table></div>;
          },
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
            if (!SAFE_URL.test(href)) return <span>{children}</span>;
            return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </Wrap>
  );
}
