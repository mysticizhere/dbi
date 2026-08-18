import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { hierarchy, tree as d3tree, type HierarchyPointNode } from "d3-hierarchy";
import type { PlanNode } from "./types";
import { buildScale, heat, heatText, type ColorMode } from "./colors";

/**
 * SVG user units do not follow the root font size, so the tree has to be scaled
 * explicitly. Keep S in step with --ui-scale in index.css.
 */
const S = 1.5;

const NODE_W = 208 * S;
// Card height and vertical gap are trimmed rather than scaled straight: at 1.5x
// the original proportions left a lot of dead space inside each card and pushed
// a four-level plan off the bottom of the canvas. Text still clears the box.
const NODE_H = 62 * S;
const GAP_X = 26 * S;
const GAP_Y = 40 * S;
const PADDING = 40 * S;
// Screen pixels of pointer jitter, not content -- deliberately unscaled.
const DRAG_THRESHOLD = 4;
const MIN_FIT_ZOOM = 0.45;

interface Props {
  root: PlanNode;
  mode: ColorMode;
  analyzed: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
}

/** Root at the top, scans at the bottom -- data flows upward, as the plan reads. */
export default function PlanTree({ root, mode, analyzed, selectedId, onSelect }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  // Panning must not steal clicks from nodes. Capture is deferred until the
  // pointer actually moves: setPointerCapture on pointerdown would redirect the
  // following `click` to the <svg>, and node selection would silently never fire.
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; moved: boolean } | null>(
    null,
  );
  const suppressClick = useRef(false);

  const { nodes, links, width } = useMemo(() => {
    const h = hierarchy(root, (d) => d.children);
    const layout = d3tree<PlanNode>().nodeSize([NODE_W + GAP_X, NODE_H + GAP_Y]);
    const positioned = layout(h);
    const all = positioned.descendants();
    const xs = all.map((n) => n.x);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    // d3 centres the root at x=0, so shift everything positive before drawing.
    const shift = -minX + NODE_W / 2 + PADDING;
    all.forEach((n) => {
      n.x += shift;
      n.y += PADDING;
    });
    // Height is not needed: fit() only ever scales to width.
    return {
      nodes: all,
      links: positioned.links(),
      width: maxX - minX + NODE_W + PADDING * 2,
    };
  }, [root]);

  const flat = useMemo(() => nodes.map((n) => n.data), [nodes]);
  const scale = useMemo(() => buildScale(mode, flat, analyzed), [mode, flat, analyzed]);

  const fit = useCallback(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    // Fit the width only. Plans are deep, so fitting the height too would shrink
    // a tall tree until nothing on it could be read -- and depth is exactly what
    // panning is for. Floored so a very wide plan stays legible and overflows
    // instead of vanishing.
    const k = Math.min(1, Math.max(MIN_FIT_ZOOM, box.width / width));
    setTransform({ x: (box.width - width * k) / 2, y: 0, k });
  }, [width]);

  useEffect(fit, [fit]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const svg = svgRef.current;
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    const px = e.clientX - box.left;
    const py = e.clientY - box.top;
    setTransform((t) => {
      const k = Math.max(0.15, Math.min(2.5, t.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
      // Keep the point under the cursor fixed while zooming.
      return { k, x: px - ((px - t.x) / t.k) * k, y: py - ((py - t.y) / t.k) * k };
    });
  };

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-slate-950">
      <svg
        ref={svgRef}
        className="min-h-0 w-full flex-1 cursor-grab active:cursor-grabbing"
        onWheel={onWheel}
        onPointerDown={(e) => {
          drag.current = {
            x: e.clientX,
            y: e.clientY,
            ox: transform.x,
            oy: transform.y,
            moved: false,
          };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          const dx = e.clientX - d.x;
          const dy = e.clientY - d.y;
          if (!d.moved) {
            // A few pixels of jitter is a click, not a drag.
            if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
            d.moved = true;
            e.currentTarget.setPointerCapture(e.pointerId);
          }
          setTransform((t) => ({ ...t, x: d.ox + dx, y: d.oy + dy }));
        }}
        onPointerUp={(e) => {
          const d = drag.current;
          drag.current = null;
          if (d?.moved) {
            e.currentTarget.releasePointerCapture(e.pointerId);
            // The click that follows a drag is the end of the pan, not a pick.
            suppressClick.current = true;
          }
        }}
        onClickCapture={() => {
          if (suppressClick.current) suppressClick.current = false;
        }}
      >
        <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}>
          {links.map((l, i) => (
            <Edge key={i} link={l} />
          ))}
          {nodes.map((n) => (
            <NodeCard
              key={n.data.id}
              node={n}
              intensity={scale.intensity(n.data)}
              caption={scale.format(n.data)}
              selected={n.data.id === selectedId}
              onSelect={(id) => {
                if (suppressClick.current) return;
                onSelect(id);
              }}
            />
          ))}
        </g>
      </svg>

      <div className="flex shrink-0 items-center gap-2 border-t border-slate-800 px-3 py-1 text-[0.625rem] text-slate-600">
        <span>scroll to zoom, drag to pan</span>
        <button
          onClick={fit}
          className="rounded border border-slate-700 px-2 py-0.5 text-slate-400 hover:text-slate-200"
        >
          fit
        </button>
        <button
          onClick={() => setTransform((t) => ({ ...t, k: 1 }))}
          className="rounded border border-slate-700 px-2 py-0.5 text-slate-400 hover:text-slate-200"
        >
          100%
        </button>
        <span className="ml-auto font-mono">{Math.round(transform.k * 100)}%</span>
      </div>

      {scale.unavailable && (
        <div className="pointer-events-none absolute right-3 top-3 rounded border border-amber-800/60 bg-amber-950/70 px-3 py-1.5 text-xs text-amber-200">
          {scale.unavailable}
        </div>
      )}
    </div>
  );
}

function Edge({ link }: { link: { source: HierarchyPointNode<PlanNode>; target: HierarchyPointNode<PlanNode> } }) {
  const { source: s, target: t } = link;
  const y1 = s.y + NODE_H;
  const mid = y1 + (t.y - y1) / 2;
  const rel = t.data.parent_relationship;
  // InitPlan / SubPlan subtrees are not part of the main data flow, so they get
  // a dashed edge rather than being drawn as if rows stream through them.
  const aside = rel === "InitPlan" || rel === "SubPlan";
  return (
    <path
      d={`M${s.x},${y1} C${s.x},${mid} ${t.x},${mid} ${t.x},${t.y}`}
      fill="none"
      stroke={aside ? "rgb(100 116 139)" : "rgb(51 65 85)"}
      strokeWidth={1.5 * S}
      strokeDasharray={aside ? "4 3" : undefined}
    />
  );
}

function NodeCard({
  node,
  intensity,
  caption,
  selected,
  onSelect,
}: {
  node: HierarchyPointNode<PlanNode>;
  intensity: number;
  caption: string;
  selected: boolean;
  onSelect: (id: number) => void;
}) {
  const d = node.data;
  const x = node.x - NODE_W / 2;
  const fill = heat(intensity);
  const text = heatText(intensity);
  const worst = d.warnings[0];

  const subtitle =
    d.index_name ?? d.relation ?? d.subplan_name ?? d.cte_name ?? d.join_type ?? "";

  return (
    <g
      transform={`translate(${x} ${node.y})`}
      className="cursor-pointer"
      onClick={(e) => {
        e.stopPropagation();
        onSelect(d.id);
      }}
    >
      <rect
        width={NODE_W}
        height={NODE_H}
        rx={6 * S}
        fill={fill}
        stroke={selected ? "rgb(56 189 248)" : "rgb(51 65 85)"}
        strokeWidth={(selected ? 2.5 : 1) * S}
      />
      <text x={10 * S} y={19 * S} fontSize={12 * S} fontWeight={600} fill={text}>
        {truncate(d.node_type, 24)}
      </text>
      {subtitle && (
        <text x={10 * S} y={34 * S} fontSize={10 * S} fill={text} opacity={0.75} fontFamily="var(--font-mono)">
          {truncate(subtitle, 28)}
        </text>
      )}
      <text x={10 * S} y={50 * S} fontSize={10 * S} fill={text} opacity={0.9} fontFamily="var(--font-mono)">
        {truncate(caption, 26)}
      </text>
      {d.timing && d.timing.loops > 1 && (
        <text
          x={NODE_W - 10 * S}
          y={50 * S}
          fontSize={10 * S}
          textAnchor="end"
          fill={text}
          opacity={0.7}
          fontFamily="var(--font-mono)"
        >
          x{d.timing.loops.toLocaleString()}
        </text>
      )}
      {worst && (
        <g transform={`translate(${NODE_W - 10 * S} ${16 * S})`}>
          <circle
            r={5 * S}
            fill={
              worst.severity === "critical"
                ? "rgb(239 68 68)"
                : worst.severity === "warn"
                  ? "rgb(245 158 11)"
                  : "rgb(56 189 248)"
            }
          />
          {d.warnings.length > 1 && (
            <text x={0} y={3 * S} fontSize={8 * S} textAnchor="middle" fill="rgb(15 23 42)" fontWeight={700}>
              {d.warnings.length}
            </text>
          )}
        </g>
      )}
    </g>
  );
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : `${s.slice(0, n - 1)}…`;
}
