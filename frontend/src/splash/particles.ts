export interface Point {
  x: number;
  y: number;
}

export interface Edge {
  a: number;
  b: number;
}

/**
 * A field of points spread across the viewport, biased away from dead centre so
 * the collapse has somewhere to travel from.
 */
export function scatterPoints(
  count: number,
  width: number,
  height: number,
  random: () => number,
): Point[] {
  const points: Point[] = [];
  for (let i = 0; i < count; i += 1) {
    const angle = random() * Math.PI * 2;
    const spread = 0.18 + random() * 0.82;
    points.push({
      x: width / 2 + Math.cos(angle) * spread * width * 0.5,
      y: height / 2 + Math.sin(angle) * spread * height * 0.5,
    });
  }
  return points;
}

/**
 * Choose which points participate in the mesh.
 *
 * The remainder stay unconnected for the whole sequence, so the field reads as
 * real scattered data — some points correlate, some are just noise — rather
 * than one uniform web.
 */
export function selectConnected(count: number, fraction: number, random: () => number): number[] {
  const selected: number[] = [];
  for (let i = 0; i < count; i += 1) {
    if (random() < fraction) selected.push(i);
  }
  return selected;
}

/**
 * Connect each point to its nearest neighbours within `radius`.
 *
 * Computed once from the scattered layout, not per frame: an all-pairs distance
 * check every frame would not hold 60fps at this point count.
 */
export function buildEdges(points: Point[], radius: number, maxPerPoint = 2): Edge[] {
  const edges: Edge[] = [];
  const seen = new Set<string>();
  const radiusSquared = radius * radius;

  for (let i = 0; i < points.length; i += 1) {
    const candidates: { index: number; distance: number }[] = [];
    for (let j = 0; j < points.length; j += 1) {
      if (i === j) continue;
      const dx = points[i].x - points[j].x;
      const dy = points[i].y - points[j].y;
      const distance = dx * dx + dy * dy;
      if (distance <= radiusSquared) candidates.push({ index: j, distance });
    }
    candidates.sort((left, right) => left.distance - right.distance);
    for (const candidate of candidates.slice(0, maxPerPoint)) {
      const key = i < candidate.index ? `${i}-${candidate.index}` : `${candidate.index}-${i}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push({ a: i, b: candidate.index });
    }
  }
  return edges;
}

/** Deterministic PRNG so the boot sequence is identical run to run. */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0xffffffff;
  };
}
