import { CONSUMER_AUDIENCE, BUSINESS_AUDIENCE } from "../../lib/audienceProfiles";
import {
  CONSUMER_STACK_META, BUSINESS_STACK_META, STACK_ORDER,
  qualNote, strengthNote, splitCategoryChips, bizOppClass, bizOppLabel,
} from "../../lib/filterStackMeta";

// Ported from "reference only.html"'s icmseAudienceStacksHTML /
// icmseBizAudienceHTML (~lines 1105-1262). Structure, copy, and toggle
// behavior are verbatim; only the CSS classes are Scrapper's own.

function StackCard({ stackKey, meta, selected, onToggle, children }) {
  return (
    <button
      type="button"
      className={`pl-stack-card ${selected ? "is-selected" : ""} ${meta.rec ? "is-recommended" : ""}`}
      onClick={() => onToggle(stackKey)}
    >
      {meta.rec && <span className="pl-stack-star">★</span>}
      <div className="pl-stack-tag">{meta.tag}</div>
      <div className="pl-stack-name">{meta.name}</div>
      <div className="pl-stack-sub">{meta.sub}</div>
      {children}
      <span className="pl-stack-check">{selected ? "Selected" : "Select"}</span>
    </button>
  );
}

function ChipList({ value }) {
  const chips = splitCategoryChips(value);
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {chips.map((c) => <span key={c} className="badge badge-people">{c}</span>)}
    </div>
  );
}

function ConsumerFilterStackModule({ niche, stacks, onToggle }) {
  const A = CONSUMER_AUDIENCE[niche.id];
  if (!A) return <AudienceInDevelopment name={niche.name} />;
  const n = stacks.length;
  return (
    <div className="mt-5">
      <div className="pl-divider">your ideal customer</div>
      <div className="pl-note-block">
        <div className="pl-al">Who we target for {niche.name}</div>
        <p>{A.ideal}</p>
      </div>

      <div className="pl-divider">choose your filter stack{n > 1 ? "s" : ""}</div>
      <div className="pl-count">{n} of 3 selected · the starred stack is our recommendation</div>
      <div className="grid gap-3 sm:grid-cols-3 mt-2">
        {STACK_ORDER.map((k) => (
          <StackCard key={k} stackKey={k} meta={CONSUMER_STACK_META[k]} selected={stacks.includes(k)} onToggle={onToggle}>
            <div className="pl-stack-body">{A[k]}</div>
          </StackCard>
        ))}
      </div>

      <div className="pl-note-block mt-4">
        <div className="pl-al">Why these filters work</div>
        <p>{A.why}</p>
      </div>

      <div className="pl-info-box">
        <div className="pl-info-cell">
          <div className="pl-al">Lead quality score</div>
          <div className="pl-qual">{A.qual}</div>
          <div className="pl-qual-note">{qualNote(A.qual)}</div>
        </div>
        <div className="pl-info-cell">
          <div className="pl-al">Always excluded</div>
          <div className="pl-excl">{A.excl}</div>
        </div>
      </div>
    </div>
  );
}

function BusinessFilterStackModule({ niche, stacks, onToggle }) {
  const A = BUSINESS_AUDIENCE[niche.id];
  if (!A) return <AudienceInDevelopment name={niche.name} />;
  const oc = bizOppClass(A.opp);
  const n = stacks.length;
  return (
    <div className="mt-5">
      <div className="pl-divider">your commercial opportunity</div>
      <div className={`pl-bizopp pl-bizopp-${oc}`}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <span className={`badge pl-bizbadge-${oc}`}>{bizOppLabel(A.opp)}</span>
          <span className="pl-bizstars">{A.strength}</span>
        </div>
        <p className="mt-2">{A.why}</p>
        <div className="pl-bizdeal mt-2"><b>Typical deal size:</b> {A.deal}</div>
      </div>

      <div className="pl-note-block mt-4">
        <div className="pl-al">One thing to confirm</div>
        <p>Commercial work sometimes needs different licensing, insurance or crew size than residential. If you're already set up for it, this is ready to run. If you're working toward it, we'll build the strategy now so it's live the day you are.</p>
      </div>

      <div className="pl-info-cell mt-4">
        <div className="pl-al">What you can sell them</div>
        <ChipList value={A.sells} />
      </div>

      <div className="pl-note-block mt-4">
        <div className="pl-al">Your ideal business customer</div>
        <p>{A.ideal}</p>
      </div>

      <div className="pl-divider">choose your target audience{n > 1 ? "s" : ""}</div>
      <div className="pl-count">{n} of 3 selected · the starred audience is our recommendation</div>
      <div className="grid gap-3 sm:grid-cols-3 mt-2">
        {STACK_ORDER.map((k) => {
          const chipCount = splitCategoryChips(A[k]).length;
          return (
            <StackCard key={k} stackKey={k} meta={BUSINESS_STACK_META[k]} selected={stacks.includes(k)} onToggle={onToggle}>
              <div className="pl-stack-sub">{chipCount} categories</div>
              <ChipList value={A[k]} />
            </StackCard>
          );
        })}
      </div>

      <div className="pl-info-box">
        <div className="pl-info-cell">
          <div className="pl-al">Commercial fit</div>
          <div className="pl-qual">{A.strength}</div>
          <div className="pl-qual-note">{strengthNote(A.strength)}</div>
        </div>
        <div className="pl-info-cell">
          <div className="pl-al">Who we leave out</div>
          <div className="pl-excl">{A.excl}</div>
        </div>
      </div>
    </div>
  );
}

function AudienceInDevelopment({ name }) {
  return (
    <div className="pl-note-block mt-5">
      Audience profile for <b>{name}</b> is in development. Everything else in your strategy will still build normally.
    </div>
  );
}

/**
 * Orchestrates which variant to render: Consumer, Business, an in-development
 * fallback (real niche with no matching data), or nothing at all (no audience
 * chosen yet, or "Other" business type with no audience chosen yet).
 */
export default function FilterStackModule({
  niche, isOther, otherName, audience, consumerStacks, businessStacks, onToggleConsumerStack, onToggleBusinessStack,
}) {
  if (!audience) return null;

  if (isOther) {
    return <AudienceInDevelopment name={otherName || "this business"} />;
  }
  if (!niche) return null;

  if (audience === "Consumers") {
    return <ConsumerFilterStackModule niche={niche} stacks={consumerStacks} onToggle={onToggleConsumerStack} />;
  }
  if (audience === "Businesses") {
    return <BusinessFilterStackModule niche={niche} stacks={businessStacks} onToggle={onToggleBusinessStack} />;
  }
  return null;
}
