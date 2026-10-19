import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Recommendation } from "../api";
import { businessLink } from "../components/BusinessTables";
import { money } from "../format";
import { WindowSelect } from "./Dashboard";

const CATEGORY_LABEL: Record<string, string> = {
  pricing: "Pricing", staffing: "Staffing", marketing: "Marketing", employees: "Employee demands", markets: "Number of businesses",
  stock: "Stock", competition: "Competition", expansion: "Expansion", profitability: "Profitability",
};
const CONFIDENCE_HELP: Record<string, string> = {
  high: "Game formula, few assumptions",
  medium: "Game mechanics plus some estimates",
  low: "Strong assumptions: check in game before acting",
};

function Card({ r, onDismiss }: { r: Recommendation; onDismiss: (dismissed: boolean) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`card reco ${r.dismissed ? "dismissed" : ""}`}>
      <div className="reco-head">
        <div>
          <div className="reco-meta">
            <span className="tag">{CATEGORY_LABEL[r.category] ?? r.category}</span>
            <span className={`conf conf-${r.confidence}`} title={CONFIDENCE_HELP[r.confidence]}>{r.confidence} confidence</span>
            <span className="muted">effort {r.effort}</span>
          </div>
          <div className="reco-title">{r.title}</div>
          <div className="muted">{r.address ? businessLink({ address: r.address, name: r.business }) : r.business}</div>
        </div>
        <div className="reco-gain" title="Estimated gain per game day">
          {r.gainPerDay != null ? <>+{money(r.gainPerDay)}<small>/day</small></> : <small className="muted">not quantified</small>}
        </div>
      </div>
      {r.steps.length > 0 && <ol className="reco-steps">{r.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
      <div className="reco-foot">
        <button className="linklike" onClick={() => setOpen(!open)}>{open ? "Hide" : "Why?"}</button>
        <button className="btn" onClick={() => onDismiss(!r.dismissed)}>{r.dismissed ? "Restore" : "Dismiss"}</button>
      </div>
      {open && <p className="reco-why">{r.why}</p>}
    </div>
  );
}

export function Recommendations() {
  const [window, setWindow] = useState(7);
  const [category, setCategory] = useState("all");
  const [confidence, setConfidence] = useState("all");
  const [showDismissed, setShowDismissed] = useState(false);
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["recommendations", window], queryFn: () => api.recommendations(window) });
  const dismiss = useMutation({
    mutationFn: ({ key, dismissed }: { key: string; dismissed: boolean }) => api.dismiss(key, dismissed),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recommendations"] }),
  });

  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error || !data || data.empty) return <div className="page"><div className="card empty">{(error as Error)?.message ?? "No data"}</div></div>;

  const categories = [...new Set(data.items.map((r) => r.category))];
  const items = data.items.filter((r) => (showDismissed || !r.dismissed)
    && (category === "all" || r.category === category) && (confidence === "all" || r.confidence === confidence));
  const s = data.summary;

  return (
    <div className="page">
      <h1>Recommendations</h1>
      <p className="subtitle">Concrete actions ranked by estimated gain × confidence, built from the game's own formulas. Based on the last <WindowSelect value={window} onChange={setWindow} />.</p>
      <div className="grid tiles">
        <div className="card tile" title={CONFIDENCE_HELP.high}><div className="label">High confidence</div><div className="value">+{money(s.gainHigh)}/day</div></div>
        <div className="card tile" title={CONFIDENCE_HELP.medium}><div className="label">Medium confidence</div><div className="value">+{money(s.gainMedium)}/day</div></div>
        <div className="card tile" title={CONFIDENCE_HELP.low}><div className="label">Low confidence</div><div className="value">+{money(s.gainLow)}/day</div></div>
        <div className="card tile"><div className="label">Actions</div><div className="value">{s.count}</div>
          {s.dismissed > 0 && <div className="muted" style={{ fontSize: 12 }}>{s.dismissed} dismissed</div>}</div>
      </div>
      <p className="footnote">Gains are not additive across alternatives (e.g. closing vs opening a business in the same market).</p>
      <div className="controls section">
        <label>Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="all">All</option>{categories.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c] ?? c}</option>)}
          </select>
        </label>
        <label>Confidence
          <select value={confidence} onChange={(e) => setConfidence(e.target.value)}>
            <option value="all">All</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
          </select>
        </label>
        <label className="toggle"><input type="checkbox" checked={showDismissed} onChange={(e) => setShowDismissed(e.target.checked)} /> Show dismissed</label>
        <span className="muted">{items.length} action(s)</span>
      </div>
      <div className="reco-list">
        {items.map((r) => <Card key={r.key} r={r} onDismiss={(dismissed) => dismiss.mutate({ key: r.key, dismissed })} />)}
        {!items.length && <div className="card empty">Nothing to do with these filters.</div>}
      </div>
    </div>
  );
}
