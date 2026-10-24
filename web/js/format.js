/** Format nullable API numbers without allowing NaN or missing values into the UI. */
export function fmtNum(value, digits = 1, fallback = "—") {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return digits === null ? String(value) : value.toFixed(digits);
}

export function numOr(value, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}
