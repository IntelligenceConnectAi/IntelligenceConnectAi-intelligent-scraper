import { useState } from "react";
import ChipInput from "../ui/ChipInput";
import { CITY_MAP } from "../../lib/cityMap";

const CITY_LIMIT = 12;
const ZIP_LIMIT = 40;

function validateZip(text) {
  const val = text.trim().replace(/,+$/, "");
  return /^\d{5}$/.test(val) ? val : null;
}

// Ported from "reference only.html"'s icmseGeoHTML (~lines 1331-1381).
// County is intentionally never built here (out of scope per the product
// decision), not just hidden.
export default function GeoTargetingFields({ stateName, audience, cities, onCitiesChange, zips, onZipsChange }) {
  const [zipsOpen, setZipsOpen] = useState(zips.length > 0);
  const citySuggestions = CITY_MAP[stateName] || [];

  const cityNote = cities.length
    ? `${cities.length} ${cities.length === 1 ? "city" : "cities"} selected. Add as many as you serve.`
    : citySuggestions.length
      ? `Pick from the ${citySuggestions.length.toLocaleString()} cities in ${stateName}, or start typing.`
      : "Add one or more. Press Enter after each.";

  const zipNote = zips.length
    ? `${zips.length} ZIP ${zips.length === 1 ? "code" : "codes"} — we target these specifically.`
    : "Type any five-digit ZIP. Paste a whole list and we'll split it for you.";

  return (
    <div className="mt-5">
      <label className="label">Which cities do you market in?</label>
      <ChipInput
        values={cities}
        onChange={onCitiesChange}
        max={CITY_LIMIT}
        suggestions={citySuggestions}
        placeholder={cities.length ? "Add another city…" : "Start typing your city…"}
      />
      <div className="pl-geonote">{cityNote}</div>

      {zipsOpen ? (
        <div className="mt-4">
          <label className="label">
            ZIP codes
            <span className="ml-2 normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>Optional · tightest targeting</span>
          </label>
          <ChipInput
            values={zips}
            onChange={onZipsChange}
            max={ZIP_LIMIT}
            parseAndValidate={validateZip}
            placeholder="e.g. 78701 — or paste a list"
          />
          <div className="pl-geonote">{zipNote}</div>
          {audience === "Businesses" && (
            <div className="pl-geonote mt-1">
              Counties don't apply to business targeting — we find businesses by category and location, and cities plus ZIP codes are the two layers that narrow it.
            </div>
          )}
        </div>
      ) : (
        <button type="button" className="pl-ziptoggle" onClick={() => setZipsOpen(true)}>
          + Narrow it down by ZIP code
        </button>
      )}
    </div>
  );
}
