import { useMemo } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { sql, PostgreSQL } from "@codemirror/lang-sql";
import { githubDark } from "@uiw/codemirror-theme-github";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onRun: () => void;
  /** Column names offered as completions, keyed by table. */
  schema?: Record<string, string[]>;
}

export default function SqlEditor({ value, onChange, onRun, schema }: Props) {
  const extensions = useMemo(
    () => [sql({ dialect: PostgreSQL, schema, upperCaseKeywords: true })],
    [schema],
  );

  return (
    <div
      className="editor-shell h-full overflow-hidden rounded-lg border border-slate-800"
      onKeyDown={(e) => {
        // Ctrl/Cmd+Enter runs, the way every SQL console works.
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          onRun();
        }
      }}
    >
      <CodeMirror
        value={value}
        onChange={onChange}
        theme={githubDark}
        extensions={extensions}
        height="100%"
        basicSetup={{ foldGutter: false, highlightActiveLine: false }}
      />
    </div>
  );
}
