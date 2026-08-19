import { useMemo } from "react";
import { marked } from "marked";

/**
 * Renders exercise prompts and notes.
 *
 * `dangerouslySetInnerHTML` is safe here in a way it usually is not: the source
 * is a markdown file on this machine, written by whoever owns the repo, in a
 * single-user app bound to 127.0.0.1. There is no untrusted input path into it.
 * If exercises ever become shareable, this needs sanitising first.
 */
export default function Markdown({ source }: { source: string }) {
  const html = useMemo(
    () => marked.parse(source, { async: false, gfm: true, breaks: false }) as string,
    [source],
  );
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
