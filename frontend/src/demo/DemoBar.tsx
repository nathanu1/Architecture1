import { FilmStrip } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { formatTime } from "../lib/time";
import { useTown } from "../store";
import { recordedWith } from "./about";
import { demoPlayer } from "./api";
import { type Moment, momentsOf } from "./moments";
import type { Player } from "./player";

/** Jumps land three game minutes early (three seconds at normal speed) so the moment plays out. */
const LEAD = 18;

/** The recording's timeline: drag to any time, or jump to a moment worth seeing. */
export function DemoBar() {
  const info = useTown((s) => s.info)!;
  const clock = useTown((s) => s.poll?.clock);
  const [player, setPlayer] = useState<Player | null>(null);
  useEffect(() => {
    let alive = true;
    void demoPlayer().then((p) => alive && setPlayer(p));
    return () => {
      alive = false;
    };
  }, []);

  const moments = useMemo<Moment[]>(() => {
    if (!player) return [];
    return momentsOf(player.events, (id) => info.residents.find((r) => r.id === id)?.first_name ?? "someone");
  }, [player, info]);

  if (!player || !clock) return null;
  const jump = (step: number) => player.seek(step);
  const how = recordedWith(info);
  return (
    <div className="pointer-events-auto panel flex w-[min(92vw,520px)] flex-col gap-1.5 px-3 py-2">
      <div className="flex items-center gap-2">
        <FilmStrip size={16} weight="fill" color="#e2629b" aria-hidden="true" />
        <span className="font-display text-sm font-bold">Recording</span>
        <span className="min-w-0 truncate text-xs text-[var(--muted)]">
          {how.mock ? (
            "mock model, so residents’ words are placeholders"
          ) : (
            <>
              words by{" "}
              <span translate="no" className="font-semibold">
                {how.model}
              </span>
              {how.via ? `, run locally through ${how.via}` : ""}
            </>
          )}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="tabular text-[11px] font-bold text-[var(--muted)]">{formatTime(player.timeAt(player.first))}</span>
        <label htmlFor="demo-time" className="sr-only">
          Time in the recording
        </label>
        <input
          id="demo-time"
          name="time"
          type="range"
          min={player.first}
          max={player.last}
          step={6}
          value={Math.max(player.first, clock.step)}
          aria-valuetext={formatTime(clock.time)}
          onChange={(e) => jump(Number(e.target.value))}
          className="h-2 min-w-0 flex-1 cursor-pointer accent-[var(--color-sun)]"
        />
        <span className="tabular text-[11px] font-bold text-[var(--muted)]">{formatTime(player.timeAt(player.last))}</span>
      </div>
      {moments.length ? (
        <div className="scroll-thin -mx-1 flex gap-1 overflow-x-auto px-1 py-0.5" role="group" aria-label="Moments in the recording">
          {moments.map((m) => (
            <button
              key={`${m.step}-${m.label}`}
              type="button"
              onClick={() => jump(Math.max(player.first, m.step - LEAD))}
              className={`shrink-0 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold transition-colors ${clock.step >= m.step ? "bg-sun/25" : "bg-[var(--panel-2)] hover:bg-[var(--panel-hover)]"}`}
              title={`Jump to just before ${formatTime(player.timeAt(m.step))}`}
            >
              <span className="tabular">{formatTime(player.timeAt(m.step))}</span> {m.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
