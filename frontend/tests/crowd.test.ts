import { describe, expect, it } from "vitest";
import { busiestSpot } from "../src/lib/crowd";
import type { Tile } from "../src/types";

describe("where the camera opens", () => {
  it("opens on the largest group of residents, not on a lone one", () => {
    const home: Tile[] = [
      [110, 75],
      [112, 75],
      [114, 74],
      [128, 75],
    ];
    const cafe: Tile[] = [[75, 20]];
    expect(busiestSpot([...cafe, ...home])).toEqual([112, 75]);
  });

  it("has nowhere to open when nobody is on the map", () => {
    expect(busiestSpot([])).toBeNull();
  });
});
