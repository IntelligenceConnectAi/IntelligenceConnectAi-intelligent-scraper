// Email Discovery fluid/liquid gauge — custom SVG + CSS wave animation, no
// library (§11.5 explicitly forbids installing an unmaintained liquid-gauge
// package). `attempted` has no literal backend field — "with website"
// businesses are the real candidate pool email-discovery runs against, so
// callers pass `total_with_website` as `attempted`; this is a genuine derived
// metric, not fabricated data.
export default function EmailDiscoveryFluidGauge({ found, attempted }) {
  const hasData = attempted > 0;
  const pct = hasData ? Math.min(Math.round((found / attempted) * 100), 100) : 0;
  const waveTop = 100 - pct;

  return (
    <div className="dashboard-panel flex flex-col items-center">
      <p className="dashboard-panel-title self-start w-full">Verified Emails</p>

      <div className="fluid-gauge" role="img" aria-label={hasData ? `${pct}% verified email rate` : "No verified email data yet"}>
        {hasData && (
          <div
            className="fluid-gauge__wave-group"
            style={{ position: "absolute", inset: 0, transform: `translateY(${waveTop}%)` }}
          >
            <svg
              className="fluid-gauge__wave"
              viewBox="0 0 240 40"
              preserveAspectRatio="none"
              style={{ position: "absolute", top: -20, left: 0, width: "200%", height: 40 }}
            >
              <path
                d="M0 20 C 30 5, 60 5, 90 20 C 120 35, 150 35, 180 20 C 210 5, 220 5, 240 20 L240 40 L0 40 Z"
                fill="var(--business-secondary)"
                opacity="0.85"
              />
            </svg>
            <div style={{
              position: "absolute", top: 20, left: 0, right: 0, bottom: 0,
              background: "var(--business-secondary)", opacity: 0.85,
            }} />
          </div>
        )}
        <div className="fluid-gauge__label">
          {hasData ? `${pct}%` : "—"}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 w-full mt-4 text-center">
        <div>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>Emails found</p>
          <p className="text-sm mono font-semibold" style={{ color: "var(--text-primary)" }}>{(found ?? 0).toLocaleString()}</p>
        </div>
        <div>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>With website</p>
          <p className="text-sm mono font-semibold" style={{ color: "var(--text-primary)" }}>{(attempted ?? 0).toLocaleString()}</p>
        </div>
      </div>
      {!hasData && (
        <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>No data yet</p>
      )}
    </div>
  );
}
