import { useEffect, useState } from "react";
import { DEMO } from "../demo/flag";
import { TAB } from "../tab/flag";

/** A page with no server behind its paths (the recorded demo, the town in a tab): views live in the hash. */
export const STATIC_PAGE = DEMO || TAB;

export type View = "town" | "inspector";

function current(): View {
  if (window.location.hash === "#inspector") return "inspector";
  if (window.location.hash === "#town") return "town";
  return window.location.pathname.startsWith("/inspector") ? "inspector" : "town";
}

/** The town or the research inspector, from the path (`ga play`) or a bare hash token (demo build). */
export function useView(): View {
  const [view, setView] = useState<View>(current);
  useEffect(() => {
    const on = () => setView(current());
    window.addEventListener("hashchange", on);
    window.addEventListener("popstate", on);
    return () => {
      window.removeEventListener("hashchange", on);
      window.removeEventListener("popstate", on);
    };
  }, []);
  return view;
}

/** Links between the two views. The demo page lives in a frame that cannot change its path. */
export const viewHref = (view: View) => (STATIC_PAGE ? `#${view}` : view === "inspector" ? "/inspector" : "/");

/** Keep view state in the query string, so it can be linked and reloaded (not in the demo build). */
export function replaceQuery(q: URLSearchParams): void {
  if (STATIC_PAGE) return;
  try {
    const search = q.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${search ? `?${search}` : ""}`);
  } catch {
    /* an embedding frame may refuse URL changes; the view still works */
  }
}
