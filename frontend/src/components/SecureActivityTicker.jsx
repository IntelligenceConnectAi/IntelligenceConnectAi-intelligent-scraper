// Secure activity ticker (§11.21) — client-safe, one item at a time, built
// with Motion's AnimatePresence (no separate ticker package). Sourced from
// the existing notifications endpoint (Phase 6) — already sanitized
// title/body text, no internal processing details.
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { api } from "../lib/api";

const CYCLE_MS = 6000;

export default function SecureActivityTicker() {
  const [items, setItems] = useState([]);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    api.listNotifications()
      .then(res => setItems((res.items || []).slice(0, 8)))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (paused || items.length <= 1) return;
    timerRef.current = setInterval(() => setIndex(i => (i + 1) % items.length), CYCLE_MS);
    return () => clearInterval(timerRef.current);
  }, [items, paused]);

  if (items.length === 0) return null;

  const current = items[index];

  return (
    <div
      className="dashboard-panel activity-ticker"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      tabIndex={0}
      role="status"
      aria-live="polite"
    >
      <span className="activity-ticker__dot" aria-hidden="true" />
      <AnimatePresence mode="wait">
        <motion.span
          key={current.id ?? index}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        >
          <strong style={{ color: "var(--text-primary)" }}>{current.title}</strong>
          {current.body ? <span style={{ color: "var(--text-muted)" }}> — {current.body}</span> : null}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}
