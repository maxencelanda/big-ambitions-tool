import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Candidate, StaffMember } from "../api";
import { businessLink } from "../components/BusinessTables";
import { Column, SortableTable } from "../components/SortableTable";
import { percent } from "../format";

const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(2)}`);

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Cap({ cap }: { cap: number | null | undefined }) {
  if (cap == null) return <span className="muted">—</span>;
  return <span className={cap < 100 ? "neg" : undefined}>{cap}</span>;
}

function Candidates({ candidates }: { candidates: Candidate[] }) {
  const skills = useMemo(() => [...new Set(candidates.map((c) => c.mainSkill))].sort(), [candidates]);
  const businesses = useMemo(() => [...new Set(candidates.flatMap((c) => c.fitsDetail.map((f) => f.business)))].sort(), [candidates]);
  const [skill, setSkill] = useState("all");
  const [business, setBusiness] = useState("all");
  const [fullOnly, setFullOnly] = useState(false);
  const [minSkill, setMinSkill] = useState(0);

  // Pour un commerce choisi, on juge chaque candidat dans CE commerce ; sinon dans son meilleur commerce.
  const rows = candidates
    .map((c) => {
      const fit = business === "all" ? null : c.fitsDetail.find((f) => f.business === business);
      if (business !== "all" && !fit) return null;
      return fit ? { ...c, bestBusiness: fit.business, bestAddress: fit.address, bestCap: fit.cap, effectiveSkill: fit.effectiveSkill,
                     wagePerEffectivePoint: fit.wagePerEffectivePoint, missingAtBest: fit.missing } : c;
    })
    .filter((c): c is Candidate => Boolean(c))
    .filter((c) => (skill === "all" || c.mainSkill === skill) && c.mainSkillValue >= minSkill && (!fullOnly || (c.bestCap ?? 100) >= 100));

  const columns: Column<Candidate>[] = [
    { key: "name", label: "Candidate", render: (c) => <span title={`Skills: ${c.skills}\nDemands: ${c.demands}`}>{c.name}</span> },
    { key: "mainSkill", label: "Skill", render: (c) => <>{c.mainSkill} <b>{c.mainSkillValue.toFixed(0)}</b></> },
    { key: "hourlyWage", label: "Wage/h", num: true, render: (c) => usd(c.hourlyWage), title: "Candidates ask exactly the market wage for their skill" },
    { key: "bestBusiness", label: business === "all" ? "Best fit" : "Business", render: (c) => (c.bestAddress
      ? <span title={c.fitsDetail.map((f) => `${f.business}: satisfaction ${f.cap ?? "—"}${f.missing ? ` — ${f.missing}` : ""}`).join("\n")}>
          {businessLink({ address: c.bestAddress, name: c.bestBusiness })}{c.fits > 1 && business === "all" ? <span className="muted"> +{c.fits - 1}</span> : null}</span>
      : <span className="muted">no matching business</span>) },
    { key: "bestCap", label: "Satisfaction", num: true, title: "Satisfaction this candidate will settle at there (60 / 80 / 100), from the demands that can be met",
      render: (c) => <Cap cap={c.bestCap} /> },
    { key: "effectiveSkill", label: "Effective skill", num: true, title: "Skill × satisfaction: what customers actually get",
      render: (c) => (c.effectiveSkill != null ? c.effectiveSkill.toFixed(0) : "—") },
    { key: "wagePerEffectivePoint", label: "$/point", num: true, title: "Hourly wage per point of effective skill (lower is better value)",
      render: (c) => (c.wagePerEffectivePoint != null && Number.isFinite(c.wagePerEffectivePoint) ? c.wagePerEffectivePoint.toFixed(3) : "—") },
    { key: "missingAtBest", label: "To fix first", render: (c) => (c.missingAtBest ? <span className="muted" title={c.missingAtBest}>{c.missingAtBest.length > 60 ? `${c.missingAtBest.slice(0, 60)}…` : c.missingAtBest}</span> : "") },
    { key: "hoursUntilExpiring", label: "Expires in", num: true, className: (c) => ((c.hoursUntilExpiring ?? 999) <= 12 ? "neg" : undefined),
      render: (c) => (c.hoursUntilExpiring != null ? `${c.hoursUntilExpiring} h` : "—") },
    { key: "source", label: "Source", value: (c) => c.sourceBusiness ?? "headhunter",
      render: (c) => (c.fromJobBoard ? <span className="muted">job board · {c.sourceBusiness}</span> : <span className="muted">headhunter</span>) },
  ];

  return (
    <div className="card section">
      <h2>Candidates</h2>
      <p className="hint">Ranked by effective skill (skill × the satisfaction they will settle at) then by wage per point. Hover a name for skills and demands, a business for every possible fit.</p>
      <div className="controls">
        <label>Skill
          <select value={skill} onChange={(e) => setSkill(e.target.value)}>
            <option value="all">All</option>{skills.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label>For
          <select value={business} onChange={(e) => setBusiness(e.target.value)}>
            <option value="all">Their best business</option>{businesses.map((b) => <option key={b}>{b}</option>)}
          </select>
        </label>
        <label>Min skill
          <select value={minSkill} onChange={(e) => setMinSkill(Number(e.target.value))}>
            {[0, 50, 70, 90, 100].map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className="toggle"><input type="checkbox" checked={fullOnly} onChange={(e) => setFullOnly(e.target.checked)} /> Only those who would reach 100 satisfaction</label>
        <span className="muted">{rows.length} candidate(s)</span>
      </div>
      <SortableTable rows={rows} columns={columns} rowKey={(c) => c.id} initialSort="effectiveSkill" maxHeight={640} />
    </div>
  );
}

function Wages({ employees }: { employees: StaffMember[] }) {
  const columns: Column<StaffMember>[] = [
    { key: "name", label: "Employee" },
    { key: "business", label: "Business", render: (e) => (e.address ? businessLink({ address: e.address, name: e.business }) : "—") },
    { key: "mainSkillValue", label: "Skill", num: true, render: (e) => `${e.mainSkill ?? ""} ${e.mainSkillValue?.toFixed(0) ?? ""}` },
    { key: "hourlyWage", label: "Wage/h", num: true, render: (e) => usd(e.hourlyWage) },
    { key: "marketWage", label: "Market wage", num: true, title: "What a candidate with the same skill asks today", render: (e) => usd(e.marketWage) },
    { key: "wageRatio", label: "vs market", num: true, className: (e) => ((e.wageRatio ?? 1) > 1.05 ? "neg" : undefined),
      render: (e) => (e.wageRatio != null ? percent(e.wageRatio) : "—") },
    { key: "satisfaction", label: "Satisfaction", num: true, render: (e) => e.satisfaction.toFixed(0) },
    { key: "satisfactionCap", label: "Settles at", num: true, title: "Satisfaction it moves towards, from the share of demands met",
      render: (e) => <Cap cap={e.satisfactionCap} /> },
    { key: "unmetDemands", label: "Unmet demands", render: (e) => (e.unmetDemands ? <span className="muted">{e.unmetDemands}</span> : "") },
  ];
  return (
    <div className="card section">
      <h2>Your staff: wages and demands</h2>
      <p className="hint">Market wage = skill base wage × (1 + skill^1.05 / 100) × difficulty — exactly what candidates ask. Below 100 % means the employee is cheaper than a new hire of the same level.</p>
      <SortableTable rows={employees} columns={columns} rowKey={(e) => e.id} initialSort="wageRatio" maxHeight={560} />
    </div>
  );
}

export function Recruitment() {
  const { data, isLoading, error } = useQuery({ queryKey: ["recruitment"], queryFn: api.recruitment });
  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error || !data || data.empty) return <div className="page"><div className="card empty">{(error as Error)?.message ?? "No data"}</div></div>;
  const s = data.summary;
  return (
    <div className="page">
      <h1>Recruitment</h1>
      <p className="subtitle">Candidates judged against your businesses with the game's own rules: wages, job demands and the satisfaction they lead to.</p>
      <div className="grid tiles">
        <Tile label="Candidates" value={String(s.candidates)} sub={`${s.expiringWithin24h} expire within 24 h`} />
        <Tile label="Held below 100 satisfaction" value={String(s.cappedEmployees)} sub={`of ${s.employees} employees — fixable`} />
        <Tile label="Paid above market" value={String(s.overpaid)} sub="> 105 % of a new hire's wage" />
        <Tile label="Paid below market" value={String(s.underpaid)} sub="< 85 %: hard to replace at that price" />
      </div>

      <div className="grid two section">
        <div className="card">
          <h2>Fix these demands first</h2>
          <p className="hint">Satisfaction settles at 60, 80 or 100 depending on the share of demands met; customer service counts skill × satisfaction.</p>
          {data.fixes.length ? (
            <ul className="alerts">
              {data.fixes.map((f, i) => (
                <li key={i} className="alert sev-medium" style={{ cursor: "default" }}>
                  <span className="sev"><span className="dot" />{f.employees.length}</span>
                  <span className="who">{businessLink({ address: f.address, name: f.business })} · {f.demand}</span>
                  <span className="what">{f.fix[0].toUpperCase() + f.fix.slice(1)} — {f.employees.map((e) => `${e.name} (${e.cap})`).join(", ")}</span>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Every employee's demands are met.</p>}
        </div>
        <div className="card">
          <h2>Positions to fill</h2>
          <p className="hint">Poached employees and office hours short of desks</p>
          {data.openings.length ? (
            <ul className="alerts">
              {data.openings.map((o, i) => (
                <li key={i} className="alert sev-low" style={{ cursor: "default" }}>
                  <span className="sev"><span className="dot" />{o.kind}</span>
                  <span className="who">{o.address ? businessLink({ address: o.address, name: o.business }) : o.business ?? "—"}</span>
                  <span className="what">{o.detail}</span>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Nothing to fill.</p>}
        </div>
      </div>

      <Candidates candidates={data.candidates} />
      <Wages employees={data.employees} />
    </div>
  );
}
