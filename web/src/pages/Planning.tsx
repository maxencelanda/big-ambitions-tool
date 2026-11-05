import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, Plan } from "../api";
import { businessLink } from "../components/BusinessTables";
import { useThemeColors } from "../components/Chart";
import { idealHours, PlanCard, ScheduleGrid, STATION_LABEL } from "../components/Plan";
import { Column, SortableTable } from "../components/SortableTable";
import { money, percent } from "../format";

/** « Mon–Fri 0–24 h · Sat–Sun 8–21 h » : jours consécutifs aux mêmes horaires regroupés. */
function week(plan: Plan): string {
  const days = plan.days ?? [];
  const out: string[] = [];
  let i = 0;
  while (i < days.length) {
    let j = i;
    while (j + 1 < days.length && idealHours(days[j + 1]) === idealHours(days[i])) j++;
    out.push(`${days[i].label}${j > i ? `–${days[j].label}` : ""} ${idealHours(days[i])}`);
    i = j + 1;
  }
  return out.join(" · ");
}

const columns = (select: (address: string) => void): Column<Plan>[] => [
  { key: "business", label: "Business", render: (p) => (
    <><button className="linklike" onClick={() => select(p.address)}>{p.business}</button>{" "}
      <span className="muted">· {businessLink({ address: p.address, name: p.business }, "page")}</span></>) },
  { key: "hours", label: "Ideal opening hours", value: (p) => week(p), className: () => "wrap" },
  { key: "peakStations", label: "Peak staffed", num: true, render: (p) => `${p.peakStations} / ${p.stationsInstalled} ${STATION_LABEL[p.stationKind] ?? ""}`,
    title: "Stations staffed at the busiest hour / installed" },
  { key: "breakEvenEfficiency", label: "Pays from", num: true, title: "Lowest efficiency (day × hour factor) at which an open hour pays its staff",
    render: (p) => (p.breakEvenEfficiency != null ? percent(p.breakEvenEfficiency, 1) : "—") },
  { key: "employees", label: "Employees", num: true, title: "About, at the business's usual weekly hours" },
  { key: "campaigns", label: "Ideal marketing", className: () => "wrap", render: (p) => <>{p.campaigns} <span className="muted">({money(p.marketingCost)}/day)</span></> },
  { key: "gainPerDay", label: "Profit/day (model)", num: true, title: "Now → ideal, and the gain",
    render: (p) => <>{money(p.currentProfitPerDay)} → {money(p.profitPerDay)}{" "}
      {p.gainPerDay >= 1 ? <b className="pos">+{money(p.gainPerDay)}</b> : <span className="muted">—</span>}</> },
];

/** Planning détaillé du commerce choisi : grille de la semaine, puis heure par heure et créneaux. */
function Selected({ address }: { address: string }) {
  const t = useThemeColors();
  const { data } = useQuery({ queryKey: ["business", address, 7], queryFn: () => api.business(address, 7) });
  if (!data?.plan) return <div className="card empty">Loading…</div>;
  return (
    <>
      <div className="section"><ScheduleGrid plan={data.plan} days={data.planDays} hours={data.planHours} /></div>
      <div className="section"><PlanCard plan={data.plan} days={data.planDays} hours={data.planHours} t={t} /></div>
    </>
  );
}

export function Planning() {
  const { data, isLoading, error } = useQuery({ queryKey: ["planning"], queryFn: api.planning });
  const [params, setParams] = useSearchParams();
  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error || !data || data.empty) return <div className="page"><div className="card empty">{(error as Error)?.message ?? "No data"}</div></div>;
  const total = data.plans.reduce((s, p) => s + Math.max(0, p.gainPerDay), 0);
  const selected = params.get("address") ?? data.plans[0]?.address;
  const select = (address: string) => setParams({ address });
  return (
    <div className="page">
      <h1>Hours & staffing</h1>
      <p className="subtitle">Ideal opening hours, staffed stations per hour and marketing, decided together · up to +{money(total)}/day in total</p>
      <div className="toolbar">
        <label>Business{" "}
          <select value={selected} onChange={(e) => select(e.target.value)}>
            {data.plans.map((p) => <option key={p.address} value={p.address}>{p.business}</option>)}
          </select>
        </label>
      </div>
      {selected && <Selected address={selected} />}
      <div className="card section">
        <h2>All businesses</h2>
        <p className="hint">
          Click a name to show its schedule above. The game gives every open hour at least one customer
          when its hourly factor is above zero, so offices with expensive services often pay for themselves around the clock.
          Cleaning and employees' schedule demands are not modeled: check them before changing the schedule.
        </p>
        <SortableTable rows={data.plans} columns={columns(select)} rowKey={(p) => p.address} initialSort="gainPerDay" />
      </div>
    </div>
  );
}
