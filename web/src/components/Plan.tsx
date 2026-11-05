import { useMemo, useState } from "react";
import { Plan, PlanDay, PlanHour } from "../api";
import { money } from "../format";
import { baseOption, Chart, ThemeColors } from "./Chart";

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const STATION_LABEL: Record<string, string> = {
  desk: "desks", hairdresserchair: "chairs", checkoutcounter: "checkouts", cashregister: "cash registers",
};

/** « 12–20 h » (ou plusieurs plages) pour les heures d'ouverture actuelles d'un jour. */
function ranges(hours: number[]): string {
  if (!hours.length) return "closed";
  const sorted = [...hours].sort((a, b) => a - b);
  const out: string[] = [];
  let start = sorted[0], prev = sorted[0];
  for (const h of [...sorted.slice(1), null]) {
    if (h !== null && h === prev + 1) { prev = h; continue; }
    out.push(`${start}–${prev + 1} h`);
    if (h !== null) start = prev = h;
  }
  return out.join(", ");
}

export function idealHours(d: PlanDay): string {
  return d.openFrom === null ? "closed" : `${d.openFrom}–${d.openTo} h`;
}

export function PlanCard({ plan, days, hours, t }: { plan: Plan; days: PlanDay[]; hours: PlanHour[]; t: ThemeColors }) {
  const [day, setDay] = useState(1);
  const label = STATION_LABEL[plan.stationKind] ?? "stations";
  const byHour = useMemo(() => {
    const cells = new Map(hours.filter((h) => h.day === day).map((h) => [h.hour, h]));
    return Array.from({ length: 24 }, (_, hour) => cells.get(hour) ?? { day, hour, open: false, openNow: false, customers: 0, stations: 0, stationsNow: 0 });
  }, [hours, day]);
  const option = useMemo(() => ({
    ...baseOption(t),
    legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.secondary } },
    grid: { ...baseOption(t).grid, top: 30 },
    tooltip: { ...baseOption(t).tooltip, trigger: "axis", formatter: (items: { dataIndex: number }[]) => {
      const h = byHour[items[0].dataIndex];
      return `${h.hour}:00–${h.hour + 1}:00<br/>Now: ${h.openNow ? `open, ${h.stationsNow} staffed` : "closed"}`
        + `<br/>Ideal: ${h.open ? `open, ${h.stations} staffed for ${h.customers.toFixed(1)} customers` : "closed"}`;
    } },
    xAxis: { type: "category", data: byHour.map((h) => `${h.hour}h`), axisTick: { show: false },
             axisLine: { lineStyle: { color: t.axis } }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted } },
    series: [
      { name: "Staffed now", type: "bar", barMaxWidth: 12, barGap: "15%", itemStyle: { color: t.series1, borderRadius: [4, 4, 0, 0] }, data: byHour.map((h) => h.stationsNow) },
      { name: "Ideal", type: "bar", barMaxWidth: 12, itemStyle: { color: t.series2, borderRadius: [4, 4, 0, 0] }, data: byHour.map((h) => h.stations) },
    ],
  }), [byHour, t]);
  const openNow = (d: number) => ranges(hours.filter((h) => h.day === d && h.openNow).map((h) => h.hour));

  return (
    <div className="card">
      <h2>Ideal hours, staffing & marketing</h2>
      <p className="hint">
        For each of the 64 campaign mixes: customers expected hour by hour (game formulas; the game rounds up, so even a quiet
        hour brings a customer), {label} needed at {plan.customersPerStationHour} customer{plan.customersPerStationHour > 1 ? "s" : ""}/h
        each, then each day the run of hours where the margin ({money(plan.valuePerCustomer)}/customer) beats the wages
        ({money(plan.stationWage)}/h per {label.replace(/s$/, "")}). The mix with the best weekly profit wins.
      </p>
      <div className="mk-lines">
        <div><span className="muted">Now</span> {plan.currentCampaigns} · promotion {plan.currentPromotion} · {plan.currentCustomersPerDay.toFixed(0)} customers/day
          · {plan.currentStationHoursPerWeek} {label.replace(/s$/, "")}-hours/week · {money(plan.currentProfitPerDay)}/day</div>
        <div><span className="muted">Ideal</span> <b>{plan.campaigns}</b> ({money(plan.marketingCost)}/day) · promotion {plan.promotion}
          · {plan.customersPerDay.toFixed(0)} customers/day · {plan.stationHoursPerWeek} {label.replace(/s$/, "")}-hours/week · {money(plan.profitPerDay)}/day
          {plan.gainPerDay >= 1 ? <span className="impact"> +{money(plan.gainPerDay)}/day</span> : <span className="muted"> (already optimal)</span>}</div>
        <div><span className="muted">Team</span> peak {plan.peakStations} of {plan.stationsInstalled} {label} staffed · about <b>{plan.employees}</b> employees
          at ≈{plan.weeklyHoursPerEmployee.toFixed(0)} h/week (12 h/day max)
          {plan.moreStationsExtra ? <> · {plan.moreStationsExtra} more {label} would add {money(plan.moreStationsGainPerDay)}/day</> : null}</div>
      </div>
      <div className="segmented" role="group" aria-label="Day" style={{ marginBottom: 8 }}>
        {WEEKDAYS.map((d, i) => <button key={d} className={i + 1 === day ? "on" : ""} onClick={() => setDay(i + 1)}>{d}</button>)}
      </div>
      <Chart option={option} height={220} label={`Staffed ${label} per hour, now and ideal`} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>Day</th><th>Open now</th><th>Ideal hours</th><th title="Number of staffed stations × hours">Ideal shifts</th>
            <th className="num">Customers</th><th className="num">Peak</th></tr></thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.day}>
                <td>{d.label}</td><td>{openNow(d.day)}</td><td><b>{idealHours(d)}</b></td>
                <td>{d.shifts || "—"}</td><td className="num">{d.customers.toFixed(0)}</td><td className="num">{d.peakStations}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        Model vs model: “now” is your current schedule and campaigns through the same formulas
        {plan.calibration < 0.95 ? `, calibrated on observed sales (${Math.round((1 - plan.calibration) * 100)} % of modeled customers do not buy)` : ""}.
        Not modeled: cleaning, employees' schedule demands, satisfaction changes.
      </p>
    </div>
  );
}
