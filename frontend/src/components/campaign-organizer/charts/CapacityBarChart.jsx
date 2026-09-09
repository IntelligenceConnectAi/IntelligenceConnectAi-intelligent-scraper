// Multi-colored horizontal bar comparison (e.g. Dials/Day vs Team Capacity/Day
// vs Per-Caller) — same structure as BarListChart, but each bar gets its own
// color from the shared categorical rotation instead of one flat color,
// since these bars compare different measures rather than ranking one metric.
import ReactECharts from "echarts-for-react";
import { CHART_COLORS, tooltipTheme, baseGridOption, axisLabelStyle, resolveColor } from "../../../lib/chartTheme";

export default function CapacityBarChart({ items, title, emptyLabel = "No data yet" }) {
  if (!items.length) return (
    <p className="text-xs" style={{ color: "var(--text-3)" }}>{emptyLabel}</p>
  );

  const max = Math.max(1, ...items.map((i) => i.value));
  const reversed = [...items].reverse();

  const option = {
    ...baseGridOption,
    grid: { left: 8, right: 44, top: title ? 28 : 4, bottom: 4, containLabel: true },
    title: title ? { text: title, left: "center", textStyle: { fontSize: 12, color: resolveColor("var(--text-muted)"), fontWeight: 500 } } : undefined,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipTheme(), valueFormatter: (v) => v.toLocaleString() },
    xAxis: { type: "value", max, show: false },
    yAxis: {
      type: "category",
      data: reversed.map((i) => i.label),
      axisLabel: axisLabelStyle(),
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: "bar",
      data: reversed.map((i, idx) => ({
        value: i.value,
        itemStyle: { color: resolveColor(CHART_COLORS[(items.length - 1 - idx) % CHART_COLORS.length]), borderRadius: [0, 6, 6, 0] },
      })),
      barWidth: 14,
      label: {
        show: true, position: "right", color: resolveColor("var(--text-primary)"),
        fontFamily: "JetBrains Mono, SFMono-Regular, Consolas, monospace", fontSize: 11,
        formatter: (p) => p.value.toLocaleString(),
      },
    }],
  };

  return (
    <ReactECharts
      option={option}
      style={{ width: "100%", height: Math.max(120, items.length * 40 + (title ? 28 : 0)) }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
