// Last section of the New Request form, right before Submit. The warning
// note always stays visible regardless of the toggle; the Terms &amp;
// Conditions checkbox only appears (and must be checked to submit) when
// "Yes — keep all numbers" is selected.
export default function DncPhoneNumbersField({ included, onIncludedChange, termsAgreed, onTermsAgreedChange }) {
  return (
    <div className="mt-5">
      <div className="pl-divider">🚫 DNC Phone Numbers</div>
      <p className="text-sm mb-3" style={{ color: "var(--text-2)" }}>Do you want DNC phone numbers included?</p>

      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={included}
          className={`pl-toggle ${included ? "is-on" : ""}`}
          onClick={() => onIncludedChange(!included)}
        >
          <span className="pl-toggle-knob" />
        </button>
        <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
          {included ? "Yes — keep all numbers" : "No — remove Public DNC numbers"}
        </span>
      </div>

      <div className="pl-warning-note mt-3">
        <p><b>⚠ Please note:</b> DNC = Do-Not-Call / Do-Not-Disturb numbers.</p>
        <p className="mt-1">
          You are <b>solely responsible</b> for any DNC numbers or anything else. We will <b>not</b> be
          responsible for this. This task is entirely your responsibility.
        </p>
      </div>

      {included && (
        <label className="pl-dnc-agree mt-3">
          <input
            type="checkbox"
            checked={termsAgreed}
            onChange={(e) => onTermsAgreedChange(e.target.checked)}
          />
          I agree to the Terms &amp; Conditions and I have read all the terms and conditions.
        </label>
      )}
    </div>
  );
}
