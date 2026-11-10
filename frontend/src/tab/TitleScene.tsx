import { useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { TitleWorld } from "./TitleWorld";

/**
 * The title screen's backdrop: a small 3D world with the town's name standing in it
 * (TitleWorld.ts). Decoration only; the page's heading and controls live in Gate.tsx. Where
 * 3D drawing is not available the name is shown as plain large type on the dusk colour.
 */
export function TitleBackdrop() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const reduce = useReducedMotion();
  const [flat, setFlat] = useState(false);
  useEffect(() => {
    if (!canvas.current) return;
    let world: TitleWorld | null = null;
    try {
      world = new TitleWorld(canvas.current, !!reduce);
    } catch {
      setFlat(true);
    }
    return () => world?.dispose();
  }, [reduce]);
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-[#f39a7c]">
      {flat ? (
        <p className="absolute inset-x-0 top-[22%] text-center font-display text-[clamp(3rem,13vw,9rem)] font-bold uppercase leading-none tracking-wide text-[#e9a8f5] [text-shadow:0_6px_0_#b56fd0]" translate="no">
          Hearthside
        </p>
      ) : (
        <>
          <canvas ref={canvas} className="block size-full" />
          {/* dusk settling in at the edges */}
          <div className="absolute inset-0 bg-[radial-gradient(120%_90%_at_50%_42%,transparent_52%,rgba(122,60,190,0.34)_100%)]" />
        </>
      )}
    </div>
  );
}
