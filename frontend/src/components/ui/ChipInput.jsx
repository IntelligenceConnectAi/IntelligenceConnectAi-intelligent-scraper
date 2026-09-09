import { useEffect, useId, useMemo, useRef, useState } from "react";

/**
 * Multi-value chip/tag input: type a value, press Enter or comma to commit
 * it as a chip; Backspace on an empty field removes the last chip. Generalizes
 * the zip/city chip patterns previously duplicated across PeopleLeads.jsx and
 * ScrapeLeads.jsx. Pass `suggestions` to add a type-to-filter popover under
 * the field (e.g. cities for the current state).
 */
export default function ChipInput({
  values,
  onChange,
  parseAndValidate = (text) => text.trim() || null,
  placeholder = "Type a value, press Enter or comma…",
  max,
  suggestions,
  minHeight = 60,
}) {
  const inputId = useId();
  const containerRef = useRef(null);
  const [text, setText] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);

  const atMax = typeof max === "number" && values.length >= max;

  const filteredSuggestions = useMemo(() => {
    if (!suggestions || !text.trim()) return [];
    const q = text.trim().toLowerCase();
    return suggestions
      .filter((s) => s.toLowerCase().includes(q) && !values.some((v) => v.toLowerCase() === s.toLowerCase()))
      .slice(0, 30);
  }, [suggestions, text, values]);

  useEffect(() => {
    function onDocMouseDown(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) setShowSuggestions(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  const commit = (raw) => {
    const parts = raw.split(",").map((p) => p.trim()).filter(Boolean);
    if (!parts.length) return;
    const next = [...values];
    for (const part of parts) {
      if (typeof max === "number" && next.length >= max) break;
      const parsed = parseAndValidate(part);
      if (!parsed) continue;
      if (next.some((v) => v.toLowerCase() === parsed.toLowerCase())) continue;
      next.push(parsed);
    }
    if (next.length !== values.length) onChange(next);
    setText("");
    setHighlightIndex(-1);
  };

  const handleChange = (e) => {
    const val = e.target.value;
    if (val.includes(",")) {
      const parts = val.split(",");
      commit(parts.slice(0, -1).join(","));
      setText(parts[parts.length - 1]);
    } else {
      setText(val);
    }
    setShowSuggestions(true);
    setHighlightIndex(-1);
  };

  const selectSuggestion = (s) => {
    commit(s);
    setShowSuggestions(false);
  };

  const handleKeyDown = (e) => {
    if (showSuggestions && filteredSuggestions.length > 0 && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      const dir = e.key === "ArrowDown" ? 1 : -1;
      setHighlightIndex((prev) => {
        const next = prev + dir;
        if (next < 0) return filteredSuggestions.length - 1;
        if (next >= filteredSuggestions.length) return 0;
        return next;
      });
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (showSuggestions && highlightIndex >= 0 && filteredSuggestions[highlightIndex]) {
        selectSuggestion(filteredSuggestions[highlightIndex]);
      } else if (text.trim()) {
        commit(text);
      }
      return;
    }
    if (e.key === "Escape") { setShowSuggestions(false); return; }
    if (e.key === "Backspace" && !text && values.length > 0) onChange(values.slice(0, -1));
  };

  const removeValue = (v) => onChange(values.filter((x) => x !== v));

  return (
    <div className="relative pl-chipfield" ref={containerRef}>
      <div
        className="input flex flex-wrap gap-1.5 items-start content-start cursor-text"
        style={{ padding: "8px 12px", minHeight }}
        onClick={() => document.getElementById(inputId)?.focus()}
      >
        {values.map((v) => (
          <span key={v} className="badge badge-people flex items-center gap-1 shrink-0">
            {v}
            <button type="button" onClick={(e) => { e.stopPropagation(); removeValue(v); }}
              className="hover:opacity-70 transition leading-none">×</button>
          </span>
        ))}
        {!atMax && (
          <input
            id={inputId}
            value={text}
            onChange={handleChange}
            onFocus={() => setShowSuggestions(true)}
            onKeyDown={handleKeyDown}
            placeholder={values.length === 0 ? placeholder : ""}
            className="flex-1 min-w-[120px] bg-transparent outline-none text-sm"
            style={{ color: "var(--text)", border: "none", padding: 0 }}
          />
        )}
      </div>
      {showSuggestions && filteredSuggestions.length > 0 && (
        <div className="pl-combobox-popover">
          {filteredSuggestions.map((s, i) => (
            <button
              type="button"
              key={s}
              className={`pl-combobox-option ${i === highlightIndex ? "is-active" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); selectSuggestion(s); }}
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
