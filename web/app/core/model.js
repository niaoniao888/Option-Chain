/**
 * @typedef {object} SnapshotModel
 * @property {Readonly<object>} raw Exact server payload retained for audit and merging.
 * @property {Readonly<object>} projected Display-only local time projection.
 */

/** Preserve the raw server snapshot and attach only display projections. */
export function createModel(raw, projected) {
  return Object.freeze({ raw, projected });
}

export function mergeSnapshot(previous, incoming) {
  if (!incoming || typeof incoming !== "object") return null;
  if (incoming.unchanged === true) {
    if (!previous || !Array.isArray(previous.contracts)) return null;
    return { ...previous, ...incoming, contracts: previous.contracts };
  }
  return incoming;
}
