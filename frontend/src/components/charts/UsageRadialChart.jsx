// Centerpiece "Monthly Usage" gauge — segmented radial gauge per §11.1: cyan
// segment for used, violet segment for processing, muted navy track for
// remaining. Same `used/remaining/limit/renewalDate/daysUntilReset/
// processingCount` props as before. Center % uses Number Flow's roll-in
// (satisfies the "center number rolls" animation ask); the arc itself is a
// static segmented ring rather than a literal sweep-in tween — ECharts
// doesn't cleanly animate multi-color axisLine stops, and the existing
// glow-pulse halo plus the rolling number already read as "alive."
import ReactECharts from "echarts-for-react";
import NumberFlow from "@number-flow/react";
import { baseGridOption, resolveColor, BUSINESS_SECONDARY, BRAND_PURPLE_BRIGHT, BORDER_SOFT } from "../../lib/chartTheme";

export default function UsageRadialChart({ used, remaining, limit, renewalDate, daysUntilReset, processingCount }) {
  const limitSafe = limit > 0 ? limit : 0;
  const pct = limitSafe > 0 ? Math.min(Math.round((used / limitSafe) * 100), 100) : 0;
  const usedFrac = limitSafe > 0 ? Math.min(Math.max(used, 0) / limitSafe, 1) : 0;
  const procFrac = limitSafe > 0
    ? Math.min(Math.max(processingCount ?? 0, 0) / limitSafe, 1 - usedFrac)
    : 0;

  const colorStops = usedFrac + procFrac <= 0
    ? [[1, resolveColor(BORDER_SOFT)]]
    : [
        [usedFrac, resolveColor(BUSINESS_SECONDARY)],
        [usedFrac + procFrac, resolveColor(BRAND_PURPLE_BRIGHT)],
        [1, resolveColor(BORDER_SOFT)],
      ];

  const option = {
    ...baseGridOption,
    series: [{
      type: "gauge",
      startAngle: 220,
      endAngle: -40,
      min: 0,
      max: 100,
      radius: "92%",
      pointer: { show: false },
      progress: { show: false },
      axisLine: { lineStyle: { width: 18, color: colorStops } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      detail: { show: false },
      data: [{ value: pct }],
    }],
  };

  return (
    <div className="dashboard-panel flex flex-col items-center">
      <p className="dashboard-panel-title self-start w-full">Monthly Usage</p>

      <div
        className="animate-glow"
        style={{ position: "relative", width: 200, height: 200, borderRadius: "50%" }}
        role="img"
        aria-label={`${pct}% of monthly leads used`}
      >
        <ReactECharts option={option} style={{ width: 200, height: 200 }} opts={{ renderer: "svg" }} notMerge />
        <div style={{
          position: "absolute", inset: 0, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", pointerEvents: "none",
        }}>
          <p className="kpi-value" style={{ fontSize: "2.25rem", margin: 0 }}>
            <NumberFlow value={pct} suffix="%" />
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>used</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 w-full mt-5 text-center">
        <div>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>Used</p>
          <p className="text-sm mono font-semibold" style={{ color: "var(--text-primary)" }}>{used.toLocaleString()}</p>
        </div>
        <div>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>Remaining</p>
          <p className="text-sm mono font-semibold" style={{ color: "var(--text-primary)" }}>{remaining.toLocaleString()}</p>
        </div>
        <div>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>Limit</p>
          <p className="text-sm mono font-semibold" style={{ color: "var(--text-primary)" }}>
            {limit ? limit.toLocaleString() : "—"}
          </p>
        </div>
      </div>

      {(daysUntilReset != null || processingCount > 0) && (
        <p className="text-xs mt-3 text-center" style={{ color: "var(--text-muted)" }}>
          {daysUntilReset != null && (
            <>Resets in {daysUntilReset} {daysUntilReset === 1 ? "day" : "days"}
              {renewalDate ? ` · ${new Date(renewalDate).toLocaleDateString("en-US", { month: "short", day: "numeric" })}` : ""}
            </>
          )}
          {processingCount > 0 && (
            <> {daysUntilReset != null ? "· " : ""}{processingCount} request{processingCount === 1 ? "" : "s"} processing</>
          )}
        </p>
      )}
    </div>
  );
}
