import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Candidate, NegotiationOption, StaffMember } from "../api";
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

const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)} %`);
const acceptAt = (mood: number) => (mood >= 50 ? 0.95 : mood >= 25 ? 0.975 : 0.99);
const up = (v: number, step: number) => Math.ceil(Math.round((v / step) * 1e6) / 1e6) * step;

/** Humeur après une réponse du candidat, en fourchette : le jeu ne l'affiche pas, on la déduit de sa réaction. */
function moodAfter(prev: number, next: number): [number, number] {
  if (next < prev - 0.001) return [4, 6]; // contre-proposition : −4 à −6
  if (Math.abs(next - prev) <= 0.001) return [10, 20]; // refus ferme : −10 à −20
  return [25, 30]; // proposition relevée : −25 à −30
}

/** Suivi d'une négociation en cours : on saisit chaque contre-proposition, l'outil suit l'humeur et donne les offres. */
function Tracker({ c, n, target }: { c: Candidate; n: number; target: number }) {
  const start = c.negotiationMood ?? 100;
  const [counters, setCounters] = useState<number[]>(c.negotiationPending ? [] : [c.asking ?? c.hourlyWage]);
  const [input, setInput] = useState("");
  let low = start, high = start;
  for (let i = 1; i < counters.length; i++) {
    const [a, b] = moodAfter(counters[i - 1], counters[i]);
    low -= b; high -= a;
  }
  const rounds = counters.length - (c.negotiationPending ? 0 : 1);
  const last = counters[counters.length - 1];
  const sat = (m: number) => Math.min(100, 50 + (m - 100) / 2);
  const close = last ? up(last * acceptAt(low), 0.01) + 0.01 : null;
  const add = () => {
    const v = Number(input.replace(",", "."));
    if (v > 0) { setCounters([...counters, v]); setInput(""); }
  };
  const risky = low - 6 < 20;
  return (
    <div>
      <h3>Live negotiation</h3>
      <p className="muted" style={{ fontSize: 12, margin: "0 0 6px" }}>
        The game does not show their mood: type each counter-offer they send, the tool deduces it (−4 to −6 per counter, −10 to −20 if they hold firm).
      </p>
      <div className="controls">
        <label>Their new counter $<input type="number" step="0.05" value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") add(); }} style={{ width: 90 }} /></label>
        <button className="btn" onClick={add}>Add</button>
        <button className="btn" disabled={counters.length <= (c.negotiationPending ? 0 : 1)} onClick={() => setCounters(counters.slice(0, -1))}>Undo</button>
        <button className="btn" onClick={() => setCounters(c.negotiationPending ? [] : [c.asking ?? c.hourlyWage])}>Reset</button>
      </div>
      {counters.length > 0 && (
        <p className="muted" style={{ fontSize: 12 }}>Their offers: {counters.map((v) => usd(v)).join(" → ")}</p>
      )}
      {last ? (
        <ul className="script">
          <li>Round {rounds} · mood {low === high ? low : `${low}–${high}`} · satisfaction if hired now{" "}
            <b>{sat(low) === sat(high) ? sat(low).toFixed(0) : `${sat(low).toFixed(0)}–${sat(high).toFixed(0)}`}</b></li>
          {!risky && rounds < target && <li>Keep negotiating: offer <b>{usd(up(last * n, 0.01) + 0.01)}</b> ({target - rounds} round{target - rounds > 1 ? "s" : ""} left in your plan)</li>}
          <li>{rounds >= target || risky ? <b>Close now</b> : "To close now"}: offer <b>{usd(close)}</b> ({pct(acceptAt(low))} of {usd(last)})
            {risky && <span className="neg"> — one more round could make them walk away</span>}</li>
        </ul>
      ) : <p className="muted">Type their current counter-offer.</p>}
    </div>
  );
}

/** Négociation d'un candidat : seuils exacts, options (rounds → salaire, satisfaction) et suivi en direct. */
function Negotiation({ c }: { c: Candidate }) {
  const [rounds, setRounds] = useState(c.bestRounds ?? 0);
  const n = c.negotiateThreshold ?? 0.9;
  const option = c.negotiation.find((o) => o.rounds === rounds) ?? c.negotiation[0];
  const steps = option?.script ? option.script.split("; ").map((x) => x.split("→").map(Number)) : [];
  const startDays = (c.startDays ?? "").split(", ").filter(Boolean);
  const columns: Column<NegotiationOption>[] = [
    { key: "rounds", label: "Rounds", num: true, render: (o) => <>{o.rounds}{o.rounds === c.bestRounds ? <span className="tag"> max</span> : o.rounds === c.balancedRounds ? <span className="tag"> balanced</span> : null}</> },
    { key: "final", label: "Wage you get", num: true, title: "Expected (cautious: slowest counter-offers, biggest mood drops)",
      render: (o) => <><b>{usd(o.final)}</b> <span className="muted">({usd(o.finalCautious)})</span></> },
    { key: "saving", label: "Saved/h", num: true, value: (o) => (c.asking ?? 0) - o.final, render: (o) => usd((c.asking ?? 0) - o.final) },
    { key: "savingPerWeek", label: "Saved/week", num: true, title: "At 40 h a week", render: (o) => `$${o.savingPerWeek.toFixed(0)}` },
    { key: "mood", label: "Mood left", num: true, render: (o) => <>{o.mood} <span className="muted">({o.moodCautious})</span></> },
    { key: "satisfaction", label: "Satisfaction at hire", num: true, title: "50 + (mood − 100) / 2, then up to +0.6 per hour worked towards their cap",
      render: (o) => <>{o.satisfaction.toFixed(0)} <span className="muted">({o.satisfactionCautious.toFixed(0)})</span></> },
  ];
  return (
    <div className="card section">
      <h2>Negotiate with {c.name}</h2>
      <p className="hint">
        Thresholds are drawn when the negotiation starts, from the candidate and the day: the tool reproduces the game's draw exactly.
        Offers from <b>{pct(n)}</b> of their last counter get a counter-offer about halfway (−4 to −6 mood each);
        between {pct(c.firmThreshold)} and {pct(n)} they hold firm (−10 to −20 mood); below {pct(c.firmThreshold)} they raise their price.
        They accept 95 % of their last counter while mood ≥ 50 (97.5 % from 25, 99 % below), and walk away under 20.
        No signing bonus: they count it over 1,920 hours.
      </p>
      <div className="mk-lines">
        {c.negotiationPending
          ? <div><span className="muted">In progress</span> negotiation already started: thresholds are fixed, mood {c.negotiationMood}.</div>
          : <div><span className="muted">When</span> start on <b>day {c.negotiationStartDay}</b>
              {startDays.length > 1 && <span className="muted"> (threshold by start day: {startDays.join(" · ")})</span>}</div>}
        <div><span className="muted">Asking</span> {usd(c.asking)}/h · <span className="muted">max saving</span> <b>{usd(c.bestWage)}</b> after {c.bestRounds} rounds
          (satisfaction at hire ≈{c.bestSatisfaction?.toFixed(0)}) · <span className="muted">balanced</span> {usd(c.balancedWage)} after {c.balancedRounds} rounds (≈{c.balancedSatisfaction?.toFixed(0)})</div>
      </div>
      <SortableTable rows={c.negotiation} columns={columns} rowKey={(o) => String(o.rounds)} initialSort="rounds" initialDesc={false} maxHeight={260} />
      <div className="grid two section">
        <div>
          <h3>Script for{" "}
            <select value={rounds} onChange={(e) => setRounds(Number(e.target.value))}>
              {c.negotiation.map((o) => <option key={o.rounds} value={o.rounds}>{o.rounds}</option>)}
            </select> round(s)</h3>
          <ol className="script">
            {steps.map(([offer, next], i) => (
              <li key={i}>Offer <b>{usd(offer)}</b> ({pct(n)} of {usd(i === 0 ? c.asking : steps[i - 1][1])}) → they counter ≈ {usd(next)}</li>
            ))}
            <li>Offer <b>{usd(option?.final)}</b> ({pct(acceptAt(option?.mood ?? 100))} of their last counter): <b>accepted</b>.</li>
          </ol>
          <p className="muted" style={{ fontSize: 12 }}>Counters are random (40–60 % of the way): compute each offer from their actual last counter.</p>
        </div>
        <Tracker c={c} n={n} target={rounds} />
      </div>
    </div>
  );
}

function Candidates({ candidates }: { candidates: Candidate[] }) {
  const skills = useMemo(() => [...new Set(candidates.map((c) => c.mainSkill))].sort(), [candidates]);
  const businesses = useMemo(() => [...new Set(candidates.flatMap((c) => c.fitsDetail.map((f) => f.business)))].sort(), [candidates]);
  const [skill, setSkill] = useState("all");
  const [business, setBusiness] = useState("all");
  const [fullOnly, setFullOnly] = useState(false);
  const [minSkill, setMinSkill] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const chosen = candidates.find((c) => c.id === selected);

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
    { key: "name", label: "Candidate", render: (c) => (
      <button className="linklike" title={`Skills: ${c.skills}\nDemands: ${c.demands}\nClick: negotiation plan`} onClick={() => setSelected(c.id)}>{c.name}</button>) },
    { key: "mainSkill", label: "Skill", render: (c) => <>{c.mainSkill} <b>{c.mainSkillValue.toFixed(0)}</b></> },
    { key: "hourlyWage", label: "Asks/h", num: true, render: (c) => usd(c.asking ?? c.hourlyWage), title: "Candidates ask the market wage for their skill (rounded up to 5 cents)" },
    { key: "bestWage", label: "Negotiated/h", num: true, title: "Best wage with the negotiation plan (max saving); click for the script",
      render: (c) => (c.bestWage != null ? <button className="linklike" onClick={() => setSelected(c.id)}>{usd(c.bestWage)}</button> : "—") },
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
      {chosen && <Negotiation key={chosen.id} c={chosen} />}
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
