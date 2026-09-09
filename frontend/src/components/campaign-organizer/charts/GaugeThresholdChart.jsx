// Value-vs-limit gauge for the Guardrails Reports capacity checks (dials/SMS/
// emails per number/inbox per day) — same gauge-series shape as
// UsageRadialChart, but a single-stop threshold color (green under the
// limit, red over) instead of a segmented usage ring.
import ReactECharts from "echarts-for-react";
import { baseGridOption, resolveColor } from "../../../lib/chartTheme";

export default function GaugeThresholdChart({ label, value, limit, unit = "" }) {
  const ok = value <= limit;
  const axisMax = Math.max(limit * 1.4, value * 1.15, 1);
  const color = resolveColor(ok ? "var(--success)" : "var(--danger-2)");

  const option = {
    ...baseGridOption,
    series: [{
      type: "gauge",
      startAngle: 220,
      endAngle: -40,
      min: 0,
      max: axisMax,
      radius: "92%",
      pointer: { show: false },
      progress: { show: false },
      axisLine: { lineStyle: { width: 14, color: [[Math.min(value / axisMax, 1), color], [1, resolveColor("var(--border-soft)")]] } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      detail: { show: false },
      data: [{ value }],
    }],
  };

  return (
    <div className="flex flex-col items-center">
      <div style={{ position: "relative", width: 140, height: 140 }} role="img" aria-label={`${label}: ${value} of ${limit} limit`}>
        <ReactECharts option={option} style={{ width: 140, height: 140 }} opts={{ renderer: "svg" }} notMerge />
        <div style={{
          position: "absolute", inset: 0, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", pointerEvents: "none",
        }}>
          <p className="mono font-semibold" style={{ fontSize: "0.95rem", color: "var(--text-primary)", margin: 0 }}>
            {value.toLocaleString()}{unit}
          </p>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>/ {limit.toLocaleString()}{unit}</p>
        </div>
      </div>
      <p className="text-xs mt-2 text-center" style={{ color: "var(--text-muted)" }}>{label}</p>
      <p className="text-xs" style={{ color: ok ? "var(--success)" : "var(--danger-2)" }}>
        {ok ? "✓ within limit" : "⛔ over limit"}
      </p>
    </div>
  );
}
