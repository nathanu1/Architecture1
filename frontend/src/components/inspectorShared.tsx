import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { replaceQuery } from "../lib/route";

export type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export const errorText = "text-[#b3261e] dark:text-[#ffb4ab]";
export const SERVER_HINT = "Check that “ga play” (or “ga serve”) is still running, then select Refresh.";
export const th = "px-2 py-1.5 text-left text-xs font-bold uppercase tracking-wide text-[var(--muted)]";
export const td = "px-2 py-1.5 align-top";

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/** One research API read. Data from a previous path is never shown under a new one. */
export function useResearch<T>(path: string | null, deps: unknown[] = []): Loaded<T> {
  const [state, setState] = useState<Loaded<T> & { path: string | null }>({ path, data: null, error: null, loading: !!path });
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setState((s) => (s.path === path ? { ...s, loading: true } : { path, data: null, error: null, loading: true }));
    api
      .research<T>(path)
      .then((data) => alive && setState({ path, data, error: null, loading: false }))
      .catch((e) => alive && setState({ path, data: null, error: (e as Error).message, loading: false }));
    return () => {
      alive = false;
    };
  }, [path, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
  if (state.path !== path) return { data: null, error: null, loading: !!path };
  return state;
}

/** Read and write one query parameter, so every view can be linked and reloaded. */
export function useQueryParam(key: string, fallback = ""): [string, (v: string) => void] {
  const [value, setValue] = useState(() => new URLSearchParams(window.location.search).get(key) ?? fallback);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (value && value !== fallback) q.set(key, value);
    else q.delete(key);
    replaceQuery(q);
  }, [key, value, fallback]);
  return [value, setValue];
}

export function Problem({ children }: { children: ReactNode }) {
  return <p className={`text-sm ${errorText}`}>{children}</p>;
}

export function Card({ title, children, aside, hint }: { title: string; children: ReactNode; aside?: ReactNode; hint?: ReactNode }) {
  return (
    <section className="mb-4 rounded-2xl bg-[var(--panel)] p-4 shadow-sm">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="font-display text-lg font-bold">{title}</h2>
        {hint ? <span className="text-xs text-[var(--muted)]">{hint}</span> : null}
        <div className="ml-auto">{aside}</div>
      </div>
      {children}
    </section>
  );
}

/** A number with a caption, in the town's rounded style. */
export function Stat({ value, label, color }: { value: ReactNode; label: string; color?: string }) {
  return (
    <div className="min-w-28 rounded-xl bg-[var(--panel-2)] px-3 py-2">
      <div className="font-display text-xl font-bold tabular" style={color ? { color } : undefined}>
        {value}
      </div>
      <div className="text-xs font-semibold text-[var(--muted)]">{label}</div>
    </div>
  );
}

/** A small pill, tinted with one of the theme colors. */
export function Pill({ color, children, title }: { color: string; children: ReactNode; title?: string }) {
  return (
    <span title={title} className="inline-flex items-center rounded-full px-2 py-0.5 font-display text-xs font-semibold text-[var(--text)]" style={{ background: `color-mix(in srgb, ${color} 22%, var(--panel))` }}>
      {children}
    </span>
  );
}
