import { describeSource } from "@/lib/job-sources.mjs";

export default function SourceLinks({
  urls,
}: {
  urls: (string | null | undefined)[];
}) {
  const sources = [...new Set(urls)]
    .map(describeSource)
    .filter((source) => source !== null);
  if (!sources.length)
    return <small className="muted">Source link not available</small>;
  return (
    <div className="source-links" aria-label="Original sources">
      {sources.map((source) => (
        <div key={source.url} className="source-link">
          <span className="badge">{source.label}</span>{" "}
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(event) => event.stopPropagation()}
          >
            {source.action} ↗
          </a>
        </div>
      ))}
    </div>
  );
}
