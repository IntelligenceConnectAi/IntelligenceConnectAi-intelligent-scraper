// Shared ECharts theming — one place for colors/tooltip/grid per
// INTELLIGENT_SCRAPER_DASHBOARD_DESIGN_SYSTEM.md §10, reused by every chart
// component so no chart hand-rolls its own axis/tooltip styling.
//
// IMPORTANT: ECharts parses color/font strings itself (for legends, gradient
// math, tooltip swatches, etc.) rather than just writing them into an SVG
// attribute — it does NOT understand CSS `var(--x)` the way raw hand-rolled
// SVG DOM did. A `var()` string silently falls through to ECharts' own
// default palette instead of throwing, which is easy to miss visually.
// Every color below is a `var(--x)` string backed by index.css so it tracks
// the light/dark theme toggle automatically — chart components must resolve
// each one with `resolveColor()` before handing it to an ECharts `option`.

export const CHART_COLORS = [
  "var(--business-cyan)", "var(--people-pink)", "var(--brand-purple-bright)", "var(--success)",
  "var(--warning)", "var(--business-blue)", "var(--danger-2)", "var(--brand-indigo)",
];

export const CHART_AXIS_LABEL_COLOR = "var(--text-muted)";
export const CHART_AXIS_LINE_COLOR = "var(--chart-axis-line)";
export const CHART_GRID_LINE_COLOR = "var(--chart-grid-line)";
export const CHART_FONT = "Inter, system-ui, -apple-system, sans-serif";

// Design tokens reused directly by chart components — `var()` strings same
// as everything above, so they light/dark-adapt too. Callers must wrap each
// in `resolveColor()` before it reaches an ECharts `option`.
export const BUSINESS_SECONDARY = "var(--business-secondary)";
export const PEOPLE_SECONDARY = "var(--people-secondary)";
export const BRAND_PURPLE_BRIGHT = "var(--brand-purple-bright)";
export const BORDER_SOFT = "var(--border-soft)";
export const PANEL_BG_SOLID = "var(--panel-bg-solid)";

// Function, not a static object — its colors are `var()` strings that need
// re-resolving on every render (see resolveColor below), not just once at
// module load, otherwise a theme toggle would leave stale tooltip colors.
export function tooltipTheme() {
  return {
    backgroundColor: resolveColor("var(--chart-tooltip-bg)"),
    borderColor: resolveColor("var(--chart-tooltip-border)"),
    borderWidth: 1,
    textStyle: { color: resolveColor("var(--text-primary)"), fontSize: 12 },
    padding: [8, 12],
    extraCssText: "border-radius: 10px; box-shadow: 0 12px 28px rgba(0,0,0,0.35);",
  };
}

export const baseGridOption = {
  backgroundColor: "transparent",
  textStyle: { fontFamily: CHART_FONT },
  animationEasing: "cubicOut",
  animationDuration: 700,
};

export function axisLabelStyle() {
  return { color: resolveColor(CHART_AXIS_LABEL_COLOR), fontSize: 11 };
}

export function axisLineStyle() {
  return { lineStyle: { color: resolveColor(CHART_AXIS_LINE_COLOR) } };
}

export function splitLineStyle() {
  return { lineStyle: { color: resolveColor(CHART_GRID_LINE_COLOR) } };
}

// Resolves a `var(--token)` or `var(--token, fallback)` string to its
// current computed value; passes literal colors (hex/rgb/named) through
// unchanged. Falls back to the string itself (or its var() fallback) when
// `document` isn't available (SSR) or the property isn't found (e.g. jsdom
// test environments that don't load the real stylesheet).
export function resolveColor(value) {
  if (typeof value !== "string" || !value.startsWith("var(")) return value;
  if (typeof document === "undefined") return value;
  const match = value.match(/^var\((--[a-zA-Z0-9-]+)\s*(?:,\s*(.+))?\)$/);
  if (!match) return value;
  const [, name, fallback] = match;
  const resolved = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return resolved || fallback || value;
}
