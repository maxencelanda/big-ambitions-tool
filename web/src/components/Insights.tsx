import { useState } from "react";
import { Link } from "react-router-dom";
import { Insight, Severity } from "../api";
import { money } from "../format";

const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High", medium: "Medium", low: "Low", info: "Info", positive: "Good",
};

export function InsightList({ insights, showBusiness = true, empty = "Nothing stands out.", maxHeight }: {
  insights: Insight[]; showBusiness?: boolean; empty?: string; maxHeight?: number;
}) {
  const [open, setOpen] = useState<number | null>(null);
  if (!insights.length) return <p className="muted">{empty}</p>;
  return (
    <ul className={`alerts${maxHeight ? " scroll" : ""}`} style={maxHeight ? { maxHeight } : undefined}>
      {insights.map((i, n) => (
        <li key={n} className={`alert sev-${i.severity}`} onClick={() => setOpen(open === n ? null : n)}>
          <span className="sev"><span className="dot" />{SEVERITY_LABEL[i.severity]}</span>
          <span className="who">
            {showBusiness && <><Link to={`/businesses/${encodeURIComponent(i.address)}`} onClick={(e) => e.stopPropagation()}>{i.business}</Link> · </>}
            {i.title}
            {i.impactPerDay ? <span className="impact"> {i.severity === "positive" ? "+" : "≈"}{money(i.impactPerDay)}/day</span> : null}
          </span>
          <span className="what">
            {open === n ? i.detail : truncate(i.detail, 120)}
            {open === n && i.action && <span className="action">→ {i.action}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function truncate(text: string, length: number) {
  return text.length > length ? `${text.slice(0, length).trimEnd()}…` : text;
}

export function SeverityBadges({ counts }: { counts?: Partial<Record<Severity, number>> }) {
  if (!counts) return null;
  return (
    <span className="badges">
      {(["high", "medium", "low", "positive"] as Severity[]).filter((s) => counts[s]).map((s) => (
        <span key={s} className={`badge sev-${s}`} title={`${counts[s]} ${SEVERITY_LABEL[s].toLowerCase()} point(s)`}>
          <span className="dot" />{counts[s]}
        </span>
      ))}
    </span>
  );
}
