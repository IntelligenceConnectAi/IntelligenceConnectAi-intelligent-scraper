// Generic donut chart primitive — now ECharts-backed (§10/§11.3), same props
// as before so every call site (Dashboard, My Leads, History, Admin Overview)
// keeps working untouched. Degrades to a flat gray ring + empty message when
// every value is 0 — rendered as plain CSS, not fed through ECharts at all,
// so there's never a NaN%/divide-by-zero arc.
// SVG renderer (not canvas) so segment colors passed as CSS var() strings —
// several call sites already do this — keep resolving correctly.
import ReactECharts from "echarts-for-react";
import { tooltipTheme, baseGridOption, resolveColor, PANEL_BG_SOLID } from "../../lib/chartTheme";

export default function DonutChart({
  segments,             // [{ label, value, color }]
  size = 140,
  strokeWidth = 16,
  centerValue,
  centerLabel,
  emptyLabel = "No data yet",
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const outerR = size / 2;
  const innerPercent = Math.max(0, ((outerR - strokeWidth) / outerR) * 100);

  const option = total === 0 ? null : {
    ...baseGridOption,
    tooltip: { trigger: "item", ...tooltipTheme(), valueFormatter: (v) => v.toLocaleString() },
    series: [{
      type: "pie",
      radius: [`${innerPercent}%`, "100%"],
      center: ["50%", "50%"],
      avoidLabelOverlap: false,
      silent: false,
      label: { show: false },
      labelLine: { show: false },
      emphasis: { scale: true, scaleSize: 4 },
      itemStyle: { borderColor: resolveColor(PANEL_BG_SOLID), borderWidth: 2 },
      data: segments.filter(s => s.value > 0).map(s => ({
        name: s.label, value: s.value, itemStyle: { color: resolveColor(s.color) },
      })),
    }],
  };

  return (
    <div className="flex flex-col items-center">
      <div style={{ position: "relative", width: size, height: size }}>
        {total === 0 ? (
          <div style={{
            width: size, height: size, borderRadius: "50%",
            border: `${strokeWidth}px solid var(--border)`, boxSizing: "border-box",
          }} />
        ) : (
          <ReactECharts
            option={option}
            style={{ width: size, height: size }}
            opts={{ renderer: "svg" }}
            notMerge
          />
        )}
        <div style={{
          position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
          textAlign: "center", pointerEvents: "none",
        }}>
          {total === 0 ? (
            <p className="text-xs" style={{ color: "var(--text-3)" }}>{emptyLabel}</p>
          ) : (
            <>
              {centerValue != null && <p className="stat-number" style={{ fontSize: "1.5rem" }}>{centerValue}</p>}
              {centerLabel && <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>{centerLabel}</p>}
            </>
          )}
        </div>
      </div>

      {total > 0 && (
        <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 mt-3">
          {segments.filter(s => s.value > 0).map(s => (
            <div key={s.label} className="flex items-center gap-1.5 text-xs">
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: s.color, flexShrink: 0 }} />
              <span style={{ color: "var(--text-2)" }}>{s.label}</span>
              <span className="mono" style={{ color: "var(--text)" }}>
                {s.value.toLocaleString()} · {Math.round((s.value / total) * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
