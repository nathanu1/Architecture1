import { ArrowRight } from "@phosphor-icons/react";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Button } from "../components/ui";
import { tabTown } from "./client";
import { loadMind, lookAtDevice, mindById, MINDS, modelFor, type Device, type Mind } from "./mind";
import { TitleBackdrop } from "./TitleScene";

const SAVED = "hearthside-tab-town";

const SIZES = [3, 10, 25];

function savedTown(): { mind: string; residents?: number } | null {
  try {
    return JSON.parse(window.localStorage.getItem(SAVED) ?? "null") as { mind: string; residents?: number } | null;
  } catch {
    return null;
  }
}

function remember(mind: string, residents: number): void {
  try {
    window.localStorage.setItem(SAVED, JSON.stringify({ mind, residents }));
  } catch {
    /* private window: the town still runs, it is just not remembered */
  }
}

/**
 * The town's title screen in the tab build: the name standing in a small 3D world at dusk with
 * the three neighbours beside it, and a small menu (how they think, Start). The engine begins loading the moment the page
 * opens, so the button rarely waits for it.
 */
export function Gate({ children }: { children: ReactNode }) {
  const query = new URLSearchParams(window.location.search);
  const forced = query.get("mind"); // ?mind=scripted|small|…|<model id> starts straight away (links, tests)
  const group = useId();
  const [savedAll] = useState(savedTown);
  const saved = savedAll?.mind ?? null;
  const [residents, setResidents] = useState(() => Number(query.get("residents")) || savedAll?.residents || 10);
  const [device, setDevice] = useState<Device | null>(null);
  const [choice, setChoice] = useState<string | null>(forced ?? saved);
  const [stage, setStage] = useState<"choose" | "starting" | "running">(forced ? "starting" : "choose");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmNew, setConfirmNew] = useState(false);

  useEffect(() => {
    tabTown.boot().catch(() => setError("This browser can’t run the town. Try Chrome or Edge."));
    void lookAtDevice().then((d) => {
      setDevice(d);
      setChoice((c) => c ?? saved ?? d.suggested);
    });
    const onHide = () => document.visibilityState === "hidden" && void tabTown.save();
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const begin = async (mind: Mind, fresh: boolean) => {
    setStage("starting");
    setError(null);
    try {
      void (navigator.storage?.persist?.() ?? Promise.resolve()).catch(() => undefined); // ask the browser to keep the town
      const model = modelFor(mind, device ?? (await lookAtDevice()));
      await loadMind(model, (fraction) => setProgress(fraction));
      setProgress(null);
      await tabTown.start(model ?? "scripted", { fresh, residents, depth: query.get("depth") ?? "words" });
      remember(mind.id, residents);
      setStage("running");
    } catch {
      setStage("choose");
      setProgress(null);
      setError(mind.model ? "That mind didn’t fit on this device. Pick a smaller one." : "The town couldn’t start. Reload the page to try again.");
    }
  };

  useEffect(() => {
    if (forced) void begin(forced === "test" ? { ...MINDS[1], id: "test", model: "test", modelF32: undefined } : mindById(forced), query.has("fresh"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (stage === "running") return <>{children}</>;

  const picked = mindById(choice);
  const noMinds = device !== null && !device.webgpu;
  const continuing = !!saved && !query.has("fresh");
  const percent = progress !== null ? Math.round(progress * 100) : null;
  return (
    <div className="relative flex h-full flex-col items-center overflow-hidden px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-[max(1rem,env(safe-area-inset-top))]">
      <TitleBackdrop />
      <h1 className="sr-only" translate="no">
        Hearthside
      </h1>

      <div className="relative mt-auto flex w-full max-w-[34rem] flex-col items-center">
        <main className="panel relative flex w-full flex-col items-center gap-3.5 px-5 pb-5 pt-5">
          {stage === "starting" ? (
            <div className="w-full py-3 text-center" aria-live="polite">
              <p className="font-display text-lg font-semibold tabular-nums">{percent !== null ? `Fetching Their Mind… ${percent}%` : "Waking the Town…"}</p>
              <div className="mt-3 h-4 overflow-hidden rounded-full bg-[var(--panel-2)]" role="progressbar" aria-label="Progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
                <div className={`h-full origin-left rounded-full bg-sun transition-transform duration-300 ${percent !== null ? "" : "w-1/3 animate-pulse motion-reduce:animate-none"}`} style={percent !== null ? { transform: `scaleX(${Math.max(0.04, progress!)})` } : undefined} />
              </div>
            </div>
          ) : (
            <>
              <fieldset className="w-full">
                <legend className="sr-only">How the residents think</legend>
                <div className="flex flex-wrap justify-center gap-1 rounded-[1.6rem] bg-[var(--panel-2)] p-1.5">
                  {MINDS.map((m) => {
                    const off = !!m.model && noMinds;
                    return (
                      <label
                        key={m.id}
                        className={`relative cursor-pointer select-none rounded-full px-3.5 py-2 font-display text-[15px] font-semibold transition-[background-color,transform] duration-150 active:scale-95 has-[:focus-visible]:outline has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--color-sun)] ${
                          choice === m.id ? "bg-sun text-[#2a2838] shadow-[0_3px_0_var(--color-sun-deep)]" : off ? "cursor-not-allowed opacity-35" : "hover:bg-[var(--panel-hover)]"
                        }`}
                      >
                        <input type="radio" name={group} value={m.id} checked={choice === m.id} disabled={off} onChange={() => setChoice(m.id)} className="sr-only" />
                        {m.name}
                      </label>
                    );
                  })}
                </div>
              </fieldset>
              {continuing ? null : (
                <fieldset>
                  <legend className="sr-only">How many neighbours</legend>
                  <div className="flex items-center gap-1 rounded-full bg-[var(--panel-2)] p-1">
                    {SIZES.map((n) => (
                      <label
                        key={n}
                        className={`cursor-pointer select-none rounded-full px-3 py-1 font-display text-sm font-semibold tabular-nums transition-[background-color,transform] duration-150 active:scale-95 has-[:focus-visible]:outline has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--color-sun)] ${residents === n ? "bg-sun text-[#2a2838]" : "hover:bg-[var(--panel-hover)]"}`}
                      >
                        <input type="radio" name={`${group}-size`} value={n} checked={residents === n} onChange={() => setResidents(n)} className="sr-only" />
                        {n} Neighbours
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}
              <p className="min-h-5 text-balance text-center text-sm font-bold text-[var(--muted)]" role={error ? "alert" : undefined}>
                {error ?? (noMinds ? device!.why : picked.blurb)}
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button tone="primary" icon={ArrowRight} className="min-h-14 px-10 text-xl" disabled={!choice || !!(picked.model && noMinds)} onClick={() => void begin(picked, !continuing)}>
                  {continuing ? "Continue" : "Start"}
                </Button>
                {continuing ? (
                  // starting over erases the saved town, so it asks once more
                  <Button tone={confirmNew ? "danger" : "ghost"} onBlur={() => setConfirmNew(false)} onClick={() => (confirmNew ? void begin(picked, true) : setConfirmNew(true))}>
                    {confirmNew ? "Erase & Start Over?" : "New Town"}
                  </Button>
                ) : null}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
