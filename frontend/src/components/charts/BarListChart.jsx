// Ranked-list bar primitive — for top-N breakdowns (leads by state/industry,
// most requested locations, top clients) where a donut would be unreadable
// at 10 segments. Now ECharts-backed horizontal bar (§10/§11.11), same
// `items`/`emptyLabel` props as before so every call site keeps working.
import ReactECharts from "echarts-for-react";
import { tooltipTheme, baseGridOption, axisLabelStyle, resolveColor, BUSINESS_SECONDARY } from "../../lib/chartTheme";

export default function BarListChart({ items, emptyLabel = "No data yet" }) {
  if (!items.length) return (
    <p className="text-xs" style={{ color: "var(--text-3)" }}>{emptyLabel}</p>
  );

  const max = Math.max(1, ...items.map(i => i.value));
  // ECharts category axes render top-to-bottom in array order — reverse so
  // the first item in `items` appears at the top, matching the old list order.
  const reversed = [...items].reverse();

  const option = {
    ...baseGridOption,
    grid: { left: 8, right: 44, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipTheme(),
      valueFormatter: (v) => v.toLocaleString(),
    },
    xAxis: { type: "value", max, show: false },
    yAxis: {
      type: "category",
      data: reversed.map(i => i.label),
      axisLabel: axisLabelStyle(),
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: "bar",
      data: reversed.map(i => i.value),
      barWidth: 10,
      itemStyle: { color: resolveColor(BUSINESS_SECONDARY), borderRadius: [0, 6, 6, 0] },
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
      style={{ width: "100%", height: Math.max(90, items.length * 32) }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
