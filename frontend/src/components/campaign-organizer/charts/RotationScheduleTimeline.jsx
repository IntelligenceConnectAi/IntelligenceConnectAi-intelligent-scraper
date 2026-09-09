// Gantt-style rotation-schedule timeline (caller ID / SMS number / email
// inbox rotation windows) — no existing analog in this app's chart set, but a
// standard ECharts pattern: a time x-axis + an invisible "base" bar series
// (offsets each row to its start date) stacked under a visible "duration" bar
// series (the actual date range), one category-axis row per resource.
import ReactECharts from "echarts-for-react";
import { CHART_COLORS, tooltipTheme, baseGridOption, axisLabelStyle, resolveColor } from "../../../lib/chartTheme";

const fmt = (d) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" });

export default function RotationScheduleTimeline({ rows, emptyLabel = "No schedule yet" }) {
  if (!rows.length) return (
    <p className="text-xs" style={{ color: "var(--text-3)" }}>{emptyLabel}</p>
  );

  // Category axes render top-to-bottom in array order — reverse so the first
  // row in `rows` appears at the top, matching BarListChart's convention.
  const reversed = [...rows].reverse();

  const option = {
    ...baseGridOption,
    grid: { left: 8, right: 24, top: 8, bottom: 24, containLabel: true },
    tooltip: {
      trigger: "item", ...tooltipTheme(),
      formatter: (p) => {
        if (p.seriesIndex !== 1) return "";
        const row = reversed[p.dataIndex];
        return `${row.label}<br/>${fmt(row.start)} → ${fmt(row.end)}`;
      },
    },
    xAxis: {
      type: "time",
      axisLabel: { ...axisLabelStyle(), formatter: (v) => fmt(v) },
      axisLine: { show: false },
      splitLine: { show: true, lineStyle: { color: resolveColor("var(--chart-grid-line)") } },
    },
    yAxis: {
      type: "category",
      data: reversed.map((r) => r.label),
      axisLabel: axisLabelStyle(),
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        stack: "schedule",
        data: reversed.map((r) => r.start.getTime()),
        itemStyle: { color: "transparent" },
        silent: true,
        tooltip: { show: false },
      },
      {
        type: "bar",
        stack: "schedule",
        data: reversed.map((r) => r.end.getTime() - r.start.getTime()),
        barWidth: 16,
        itemStyle: {
          color: (params) => resolveColor(CHART_COLORS[(reversed.length - 1 - params.dataIndex) % CHART_COLORS.length]),
          borderRadius: 4,
        },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ width: "100%", height: Math.max(120, rows.length * 40 + 40) }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
