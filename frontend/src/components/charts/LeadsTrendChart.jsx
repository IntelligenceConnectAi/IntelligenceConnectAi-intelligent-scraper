// "Leads Generated Over Time" — smooth multi-series area chart (§11.6).
// Takes already-bucketed real data (see DashboardOverview.jsx, which buckets
// already-fetched history entries by day client-side) — this component only
// renders, it doesn't fetch or fabricate anything.
import ReactECharts from "echarts-for-react";
import {
  tooltipTheme, baseGridOption, axisLabelStyle, axisLineStyle, splitLineStyle, resolveColor,
  BUSINESS_SECONDARY, PEOPLE_SECONDARY,
} from "../../lib/chartTheme";

export default function LeadsTrendChart({ points, emptyLabel = "No data yet" }) {
  const hasData = points?.length > 0 && points.some(p => p.business > 0 || p.people > 0);

  if (!hasData) {
    return (
      <div className="dashboard-panel">
        <p className="dashboard-panel-title">Leads Generated Over Time</p>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>{emptyLabel}</p>
      </div>
    );
  }

  const option = {
    ...baseGridOption,
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", ...tooltipTheme(), valueFormatter: (v) => v.toLocaleString() },
    legend: {
      top: 0, right: 0, icon: "circle", itemWidth: 8, itemHeight: 8,
      textStyle: { color: resolveColor("var(--text-secondary)"), fontSize: 12 },
    },
    xAxis: {
      type: "category",
      data: points.map(p => p.label),
      boundaryGap: false,
      axisLabel: axisLabelStyle(),
      axisLine: axisLineStyle(),
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: axisLabelStyle(),
      splitLine: splitLineStyle(),
    },
    series: [
      {
        name: "Business Leads",
        type: "line",
        smooth: true,
        symbol: "none",
        data: points.map(p => p.business),
        lineStyle: { color: resolveColor(BUSINESS_SECONDARY), width: 2 },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(99,217,255,0.28)" },
              { offset: 1, color: "rgba(99,217,255,0)" },
            ],
          },
        },
      },
      {
        name: "People Leads",
        type: "line",
        smooth: true,
        symbol: "none",
        data: points.map(p => p.people),
        lineStyle: { color: resolveColor(PEOPLE_SECONDARY), width: 2 },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(243,107,181,0.24)" },
              { offset: 1, color: "rgba(243,107,181,0)" },
            ],
          },
        },
      },
    ],
  };

  return (
    <div className="dashboard-panel">
      <p className="dashboard-panel-title">Leads Generated Over Time</p>
      <ReactECharts option={option} style={{ width: "100%", height: 260 }} opts={{ renderer: "svg" }} notMerge />
    </div>
  );
}
