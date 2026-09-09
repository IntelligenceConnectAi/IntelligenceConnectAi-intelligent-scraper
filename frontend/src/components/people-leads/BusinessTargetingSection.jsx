import SearchableSelect from "../ui/SearchableSelect";
import TargetAudiencePicker from "./TargetAudiencePicker";
import FilterStackModule from "./FilterStackModule";
import GeoTargetingFields from "./GeoTargetingFields";
import { BUSINESS_NICHES, NICHE_CATEGORIES } from "../../lib/businessNiches";
import { US_STATES } from "../../lib/usStates";

const OTHER_VALUE = "__other__";

export const initialTargetingState = {
  businessName: "",
  nicheId: "",
  isOtherBusinessType: false,
  otherBusinessType: "",
  audience: "",
  consumerStacks: ["bal"],
  businessStacks: ["bal"],
  stateName: "",
  cities: [],
  zips: [],
};

const NICHE_OPTIONS = BUSINESS_NICHES.map((n) => ({ value: n.id, label: n.name, group: n.category }));
const OTHER_OPTION = { value: OTHER_VALUE, label: "Other — not listed" };

function selectedNiche(targeting) {
  if (targeting.isOtherBusinessType) return null;
  return BUSINESS_NICHES.find((n) => n.id === targeting.nicheId) || null;
}

function audienceLabel(serves) {
  return serves === "Consumers" ? "people and households" : "other businesses";
}

/**
 * Owns the full "tell us about your business" targeting flow (business
 * name/type, who to target, filter stack, state/cities/zip), mirroring
 * "reference only.html"'s stepBusiness(). Reports the whole shape up via a
 * single onChange so the parent form just holds one useState.
 */
export default function BusinessTargetingSection({ value: targeting, onChange }) {
  const patch = (partial) => onChange({ ...targeting, ...partial });

  const niche = selectedNiche(targeting);

  const handleBusinessTypeChange = (val) => {
    if (val === OTHER_VALUE) {
      patch({
        isOtherBusinessType: true, nicheId: "",
        audience: "", consumerStacks: ["bal"], businessStacks: ["bal"],
      });
      return;
    }
    const n = BUSINESS_NICHES.find((x) => x.id === val);
    const nextAudience = n && n.serves !== "Both" ? n.serves : "";
    patch({
      isOtherBusinessType: false, nicheId: val,
      audience: nextAudience, consumerStacks: ["bal"], businessStacks: ["bal"],
    });
  };

  const preselectNote = (!targeting.isOtherBusinessType && niche && niche.serves !== "Both")
    ? `Most ${niche.name} businesses sell to ${audienceLabel(niche.serves)} — we have pre-selected that for you. Change it if your business is different.`
    : null;

  const toggleStack = (key, field) => {
    const current = targeting[field];
    const idx = current.indexOf(key);
    if (idx === -1) {
      patch({ [field]: [...current, key] });
    } else if (current.length > 1) {
      patch({ [field]: current.filter((k) => k !== key) });
    }
  };

  const showBusinessTypePicked = targeting.isOtherBusinessType || !!niche;

  return (
    <div className="space-y-4">
      <div>
        <label className="label">Business name</label>
        <input
          value={targeting.businessName}
          onChange={(e) => patch({ businessName: e.target.value })}
          placeholder="e.g. ABC Heating & Air"
          className="input"
          autoComplete="off"
        />
      </div>

      <div>
        <label className="label">Business type</label>
        <SearchableSelect
          value={targeting.isOtherBusinessType ? OTHER_VALUE : targeting.nicheId}
          onChange={handleBusinessTypeChange}
          options={NICHE_OPTIONS}
          pinnedOption={OTHER_OPTION}
          placeholder="Choose your business…"
        />
        {targeting.isOtherBusinessType && (
          <input
            value={targeting.otherBusinessType}
            onChange={(e) => patch({ otherBusinessType: e.target.value })}
            placeholder="Tell us your business type"
            className="input mt-2"
            autoComplete="off"
          />
        )}
      </div>

      {niche && (
        <div className="pl-option-card is-selected" style={{ cursor: "default" }}>
          <span className="pl-option-title">{niche.name}</span>
          <span className="pl-option-desc"><b>Category:</b> {niche.category} &nbsp;·&nbsp; <b>Serves:</b> {niche.serves}</span>
        </div>
      )}

      {showBusinessTypePicked && (
        <TargetAudiencePicker
          audience={targeting.audience}
          onChange={(audience) => patch({ audience })}
          preselectNote={preselectNote}
        />
      )}

      <FilterStackModule
        niche={niche}
        isOther={targeting.isOtherBusinessType}
        otherName={targeting.otherBusinessType}
        audience={targeting.audience}
        consumerStacks={targeting.consumerStacks}
        businessStacks={targeting.businessStacks}
        onToggleConsumerStack={(k) => toggleStack(k, "consumerStacks")}
        onToggleBusinessStack={(k) => toggleStack(k, "businessStacks")}
      />

      <div className="mt-5">
        <label className="label">Which state do you market in?</label>
        <select
          className="input"
          value={targeting.stateName}
          onChange={(e) => patch({ stateName: e.target.value, cities: [], zips: [] })}
        >
          <option value="">Choose your state…</option>
          {US_STATES.map((s) => <option key={s.abbr} value={s.name}>{s.name}</option>)}
        </select>
      </div>

      {targeting.stateName && (
        <GeoTargetingFields
          stateName={targeting.stateName}
          audience={targeting.audience}
          cities={targeting.cities}
          onCitiesChange={(cities) => patch({ cities })}
          zips={targeting.zips}
          onZipsChange={(zips) => patch({ zips })}
        />
      )}
    </div>
  );
}
