import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function JobDescription({ text }: { text: string }) {
  return (
    <div className="description markdown-description">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(url) => {
          try {
            const parsed = new URL(url);
            return ["https:", "http:"].includes(parsed.protocol)
              ? parsed.href
              : "";
          } catch {
            return "";
          }
        }}
        components={{
          a: ({ href, children }) =>
            href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          img: ({ alt }) => <span>{alt || ""}</span>,
          h1: ({ children }) => <h3>{children}</h3>,
          h2: ({ children }) => <h3>{children}</h3>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
