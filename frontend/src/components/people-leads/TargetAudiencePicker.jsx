// Ported from "reference only.html" stepBusiness()'s audienceBlock
// (~line 1434-1440): always rendered once a business type is known — for a
// fixed-serves niche the matching option is pre-selected with a note, but
// the user can still override it.

const OPTIONS = [
  { value: "Consumers", title: "People / Households", desc: "Homeowners, consumers, and families" },
  { value: "Businesses", title: "Businesses", desc: "Companies and decision-makers" },
];

export default function TargetAudiencePicker({ audience, onChange, preselectNote }) {
  return (
    <div className="mt-5">
      <div className="pl-divider">who do you want to target?</div>
      {preselectNote && <div className="pl-note mt-2 mb-2">{preselectNote}</div>}
      <div className="grid gap-3 sm:grid-cols-2 mt-2">
        {OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`pl-option-card ${audience === opt.value ? "is-selected" : ""}`}
            onClick={() => onChange(opt.value)}
          >
            <span className="pl-option-title">{opt.title}</span>
            <span className="pl-option-desc">{opt.desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
