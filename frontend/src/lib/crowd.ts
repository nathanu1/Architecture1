import type { Tile } from "../types";

/**
 * Where most residents are: the middle of the largest group within `radius` tiles (each way) of
 * one of them, or null when nobody is on the map. The camera opens here, so a town that starts
 * at home in the morning does not open on an empty square.
 */
export function busiestSpot(points: readonly Tile[], radius = 12): Tile | null {
  let best: readonly Tile[] = [];
  for (const p of points) {
    const near = points.filter((q) => Math.abs(q[0] - p[0]) <= radius && Math.abs(q[1] - p[1]) <= radius);
    if (near.length > best.length) best = near;
  }
  if (!best.length) return null;
  const mean = (k: 0 | 1) => Math.round(best.reduce((s, q) => s + q[k], 0) / best.length);
  return [mean(0), mean(1)];
}
