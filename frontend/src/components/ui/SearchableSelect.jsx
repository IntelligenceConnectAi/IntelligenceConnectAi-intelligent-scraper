import { useEffect, useId, useMemo, useRef, useState } from "react";

/**
 * Type-to-filter single-select combobox. Renders like a normal `.input`
 * until focused, then opens a popover of options (optionally grouped) that
 * narrows as you type. An optional `pinnedOption` (e.g. "Other — not
 * listed") always renders last, unaffected by the filter text.
 */
export default function SearchableSelect({
  value,
  onChange,
  options, // [{ value, label, group? }]
  placeholder = "Search…",
  pinnedOption, // { value, label }
}) {
  const inputId = useId();
  const containerRef = useRef(null);
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightIndex, setHighlightIndex] = useState(-1);

  const selected = useMemo(() => {
    if (pinnedOption && value === pinnedOption.value) return pinnedOption;
    return options.find((o) => o.value === value) || null;
  }, [options, value, pinnedOption]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, query]);

  const groups = useMemo(() => {
    const order = [];
    const map = new Map();
    for (const opt of filtered) {
      const g = opt.group || "";
      if (!map.has(g)) { map.set(g, []); order.push(g); }
      map.get(g).push(opt);
    }
    return order.map((g) => [g, map.get(g)]);
  }, [filtered]);

  const flatList = useMemo(() => (pinnedOption ? [...filtered, pinnedOption] : filtered), [filtered, pinnedOption]);

  useEffect(() => {
    function onDocMouseDown(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  const commit = (opt) => {
    onChange(opt.value);
    setIsOpen(false);
    setQuery("");
    setHighlightIndex(-1);
  };

  const handleKeyDown = (e) => {
    if (!isOpen && (e.key === "ArrowDown" || e.key === "Enter")) { setIsOpen(true); return; }
    if (!isOpen) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const dir = e.key === "ArrowDown" ? 1 : -1;
      setHighlightIndex((prev) => {
        const next = prev + dir;
        if (next < 0) return flatList.length - 1;
        if (next >= flatList.length) return 0;
        return next;
      });
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (highlightIndex >= 0 && flatList[highlightIndex]) commit(flatList[highlightIndex]);
      return;
    }
    if (e.key === "Escape") { setIsOpen(false); setQuery(""); }
  };

  return (
    <div className="relative pl-combobox" ref={containerRef}>
      <input
        id={inputId}
        className="input"
        value={isOpen ? query : (selected ? selected.label : "")}
        onChange={(e) => { setQuery(e.target.value); setIsOpen(true); setHighlightIndex(-1); }}
        onFocus={() => { setIsOpen(true); setQuery(""); }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        autoComplete="off"
      />
      {isOpen && (
        <div className="pl-combobox-popover">
          {groups.map(([group, opts]) => (
            <div key={group || "_"}>
              {group && <div className="pl-combobox-group-label">{group}</div>}
              {opts.map((opt) => (
                <button
                  type="button"
                  key={opt.value}
                  className={`pl-combobox-option ${flatList.indexOf(opt) === highlightIndex ? "is-active" : ""}`}
                  onMouseDown={(e) => { e.preventDefault(); commit(opt); }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="pl-combobox-option" style={{ opacity: 0.6, cursor: "default" }}>No matches</div>
          )}
          {pinnedOption && (
            <button
              type="button"
              className={`pl-combobox-option ${flatList.indexOf(pinnedOption) === highlightIndex ? "is-active" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); commit(pinnedOption); }}
              style={{ borderTop: "1px solid var(--border)" }}
            >
              {pinnedOption.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
