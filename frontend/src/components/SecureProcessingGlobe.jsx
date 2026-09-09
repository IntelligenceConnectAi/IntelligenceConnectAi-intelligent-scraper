// Animated secure-processing globe + panel, per
// INTELLIGENT_SCRAPER_UI_STYLING_REQUIREMENTS.md §15-§26.
// Presentation-only: no polling, no real scraper progress, no technical
// stage/percentage data — a fixed visual indicator plus a client-facing
// status message supplied by the caller.
import { ShieldCheck } from "lucide-react";

const DEFAULT_COPY = {
  business: {
    title: "Preparing your leads securely",
    message:
      "Your request has been submitted successfully.\n" +
      "We are preparing your lead list securely.\n" +
      "Your completed files will be added to your account when they are ready.\n" +
      "We will notify you as soon as the request is completed.",
  },
  people: {
    title: "Preparing your lead list securely",
    message:
      "Your request has been submitted successfully.\n" +
      "Our data team is preparing your lead list.\n" +
      "Your completed file will be added to your account within 24 hours.\n" +
      "We will notify you as soon as it is ready.",
  },
};

const ORBITS = [
  { id: "orbitA", d: "M52 130 A158 38 0 1 0 368 130 A158 38 0 1 0 52 130", rotate: 0, dur: "5.6s" },
  { id: "orbitB", d: "M72 130 A138 62 0 1 0 348 130 A138 62 0 1 0 72 130", rotate: 18, dur: "7.2s" },
  { id: "orbitC", d: "M38 130 A172 86 0 1 0 382 130 A172 86 0 1 0 38 130", rotate: -14, dur: "8.8s" },
  { id: "orbitD", d: "M94 130 A116 50 0 1 0 326 130 A116 50 0 1 0 94 130", rotate: 30, dur: "6.4s" },
];

function Globe({ variant, size }) {
  return (
    <svg
      className="secure-processing-globe"
      data-variant={variant}
      viewBox="0 0 420 260"
      width={size}
      height={Math.round((size * 260) / 420)}
      role="img"
      aria-label="Secure lead processing"
      style={{ display: "block", margin: "0 auto", maxWidth: "100%", height: "auto" }}
    >
      <defs>
        <radialGradient id={`globeFill-${variant}`} cx="38%" cy="32%" r="75%">
          <stop offset="0%" stopColor="var(--globe-secondary)" stopOpacity="0.9" />
          <stop offset="45%" stopColor="var(--globe-primary)" stopOpacity="0.55" />
          <stop offset="100%" stopColor="var(--globe-core)" stopOpacity="0.95" />
        </radialGradient>

        <filter id={`globeGlow-${variant}`} x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="9" />
        </filter>
        <filter id={`nodeGlow-${variant}`} x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="3.2" />
        </filter>

        <clipPath id={`globeClip-${variant}`}>
          <circle cx="210" cy="130" r="92" />
        </clipPath>

        {ORBITS.map(o => <path key={o.id} id={`${o.id}-${variant}`} d={o.d} />)}
      </defs>

      {/* 1. Outer atmospheric glow */}
      <g className="processing-globe__atmosphere">
        <circle cx="210" cy="130" r="112" fill="var(--globe-glow)" filter={`url(#globeGlow-${variant})`} opacity="0.55" />
      </g>

      {/* 2. Main globe circle + 10. central radial light (baked into the gradient) */}
      <g className="processing-globe__sphere">
        <circle cx="210" cy="130" r="92" fill={`url(#globeFill-${variant})`} stroke="var(--globe-primary)" strokeOpacity="0.55" strokeWidth="1" />
      </g>

      {/* 3-5. Rotating surface: abstract land silhouettes + latitude/longitude lines */}
      <g className="processing-globe__rotating-surface" clipPath={`url(#globeClip-${variant})`}>
        <ellipse cx="210" cy="130" rx="92" ry="9" fill="none" stroke="var(--globe-secondary)" strokeOpacity="0.32" strokeWidth="1" />
        <ellipse cx="210" cy="102" rx="82" ry="6" fill="none" stroke="var(--globe-secondary)" strokeOpacity="0.24" strokeWidth="1" />
        <ellipse cx="210" cy="158" rx="82" ry="6" fill="none" stroke="var(--globe-secondary)" strokeOpacity="0.24" strokeWidth="1" />

        <ellipse cx="210" cy="130" rx="30" ry="92" fill="none" stroke="var(--globe-secondary)" strokeOpacity="0.22" strokeWidth="1" />
        <ellipse cx="210" cy="130" rx="60" ry="92" fill="none" stroke="var(--globe-secondary)" strokeOpacity="0.22" strokeWidth="1" />

        <path d="M170 96 Q188 84 208 92 Q220 98 214 112 Q198 118 182 110 Q168 106 170 96 Z"
          fill="var(--globe-node)" opacity="0.28" />
        <path d="M222 138 Q246 130 262 144 Q266 156 250 162 Q230 160 222 150 Z"
          fill="var(--globe-secondary)" opacity="0.24" />
        <path d="M178 152 Q196 146 204 158 Q200 170 184 168 Q174 162 178 152 Z"
          fill="var(--globe-node)" opacity="0.22" />
      </g>

      {/* 6. Orbit lines (curved, glowing, animated dash) */}
      <g className="processing-globe__orbits">
        {ORBITS.map(o => (
          <use key={o.id} href={`#${o.id}-${variant}`} className="processing-globe__orbit"
            transform={`rotate(${o.rotate} 210 130)`} />
        ))}
      </g>

      {/* 7. Static glowing connection nodes */}
      <g className="processing-globe__static-nodes">
        {[
          [210, 46], [332, 130], [210, 214], [88, 130], [275, 78], [148, 186],
        ].map(([x, y], i) => (
          <circle key={i} className="processing-globe__static-node"
            cx={x} cy={y} r="3.2" fill="var(--globe-node)" filter={`url(#nodeGlow-${variant})`} />
        ))}
      </g>

      {/* 8-9. Moving light particles + glow trails, one per orbit, staggered speeds */}
      <g className="processing-globe__moving-nodes">
        {ORBITS.map(o => (
          <g key={o.id} transform={`rotate(${o.rotate} 210 130)`}>
            <circle r="7" fill="var(--globe-secondary)" opacity="0.14" filter={`url(#nodeGlow-${variant})`}>
              <animateMotion dur={o.dur} repeatCount="indefinite" rotate="auto">
                <mpath href={`#${o.id}-${variant}`} />
              </animateMotion>
            </circle>
            <circle className="processing-globe__moving-node" r="3.2" fill="var(--globe-secondary)">
              <animateMotion dur={o.dur} repeatCount="indefinite" rotate="auto">
                <mpath href={`#${o.id}-${variant}`} />
              </animateMotion>
            </circle>
          </g>
        ))}
      </g>
    </svg>
  );
}

export default function SecureProcessingGlobe({
  variant = "business",
  size = 320,
  title,
  message,
  compact = false,
  className = "",
}) {
  const copy = DEFAULT_COPY[variant] || DEFAULT_COPY.business;
  const resolvedTitle = title || copy.title;
  const resolvedMessage = message || copy.message;

  return (
    <div
      className={`secure-processing-panel ${compact ? "secure-processing-panel--compact" : ""} ${className}`.trim()}
      data-variant={variant}
    >
      <Globe variant={variant} size={compact ? Math.min(size, 200) : size} />

      <div>
        <p className="secure-processing-panel__title">{resolvedTitle}</p>
        <p className="secure-processing-panel__message">{resolvedMessage}</p>
        <div className="secure-processing-panel__security-note">
          <ShieldCheck size={14} strokeWidth={2} />
          <span>Internal processing details are hidden for security and accuracy.</span>
        </div>
      </div>
    </div>
  );
}
