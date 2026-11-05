import { useMemo, useState } from "react";
import { Plan, PlanDay, PlanHour } from "../api";
import { money, percent } from "../format";
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
    return Array.from({ length: 24 }, (_, hour) => cells.get(hour) ?? { day, hour, open: false, openNow: false, efficiency: 0, customers: 0, stations: 0, stationsNow: 0 });
  }, [hours, day]);
  const option = useMemo(() => ({
    ...baseOption(t),
    legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.secondary } },
    grid: { ...baseOption(t).grid, top: 30 },
    tooltip: { ...baseOption(t).tooltip, trigger: "axis", formatter: (items: { dataIndex: number }[]) => {
      const h = byHour[items[0].dataIndex];
      return `${h.hour}:00–${h.hour + 1}:00 · efficiency ${percent(h.efficiency, 1)}<br/>Now: ${h.openNow ? `open, ${h.stationsNow} staffed` : "closed"}`
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
      {plan.breakEvenEfficiency != null && (
        <p className="hint">
          <b>An hour pays from {percent(plan.breakEvenEfficiency, 1)} efficiency</b> (day × hour factor of the business type, as on
          biggerambitions).
          {plan.firstCustomerEfficiency != null && plan.firstCustomerEfficiency >= plan.breakEvenEfficiency - 1e-9
            ? <> From there the game rounds up to 1 customer ({money(plan.valuePerCustomer)}), more than one {label.replace(/s$/, "")}'s wage ({money(plan.stationWage)}/h).</>
            : <> Below that, the few customers do not pay a {label.replace(/s$/, "")} ({money(plan.stationWage)}/h).</>}
          {" "}Hover the chart for each hour's efficiency.
        </p>
      )}
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

/** Intensité 1-4 d'une case selon le nombre de postes idéal, rapporté au pic de la semaine. */
function level(stations: number, peak: number): number {
  return stations > 0 && peak > 0 ? Math.max(1, Math.ceil((4 * stations) / peak)) : 0;
}

/** Planning de la semaine : jours × heures, postes idéaux (couleur et grand chiffre) et occupés aujourd'hui. */
export function ScheduleGrid({ plan, days, hours }: { plan: Plan; days: PlanDay[]; hours: PlanHour[] }) {
  const label = STATION_LABEL[plan.stationKind] ?? "stations";
  const one = label.replace(/s$/, "");
  const cells = new Map(hours.map((h) => [`${h.day}-${h.hour}`, h]));
  const peak = Math.max(1, ...hours.map((h) => h.stations));
  const nowRanges = (d: number) => ranges(hours.filter((h) => h.day === d && h.openNow).map((h) => h.hour));
  return (
    <div className="card">
      <h2>Weekly schedule</h2>
      <p className="hint">
        Each cell is one hour. <b>Big number and color: {label} to staff</b> in the ideal plan (one employee each);
        small number: staffed now in the game. Hover a cell for its efficiency, expected customers and who works it now.
      </p>
      <div className="sched-wrap">
        <table className="sched">
          <thead>
            <tr><th />{Array.from({ length: 24 }, (_, h) => <th key={h}>{h}</th>)}<th className="sched-sum">Ideal · now</th></tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.day}>
                <th scope="row">{d.label}</th>
                {Array.from({ length: 24 }, (_, hour) => {
                  const c = cells.get(`${d.day}-${hour}`);
                  const open = Boolean(c?.open), openNow = Boolean(c?.openNow);
                  const lv = open ? level(c!.stations, peak) : 0;
                  const title = `${d.label} ${hour}:00–${hour + 1}:00`
                    + (c ? ` · efficiency ${percent(c.efficiency, 1)}` : "")
                    + `\nIdeal: ${open ? `open, ${c!.stations} ${c!.stations === 1 ? one : label} for ${c!.customers.toFixed(1)} customers` : "closed"}`
                    + `\nNow: ${openNow ? `open, ${c!.stationsNow} staffed` : "closed"}${c?.staffNow ? ` (${c.staffNow})` : ""}`;
                  const cls = ["sched-cell", lv ? `lv${lv}` : "", openNow ? "now" : "", !open && openNow ? "cut" : ""].filter(Boolean).join(" ");
                  return (
                    <td key={hour} className={cls} title={title}>
                      {open && <span className="ideal">{c!.stations}</span>}
                      {openNow && <span className="cur">{c!.stationsNow}</span>}
                    </td>
                  );
                })}
                <td className="sched-sum"><b>{idealHours(d)}</b> · {nowRanges(d.day)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="sched-legend">
        <span><i className="sched-key lv1" /> <i className="sched-key lv2" /> <i className="sched-key lv3" /> <i className="sched-key lv4" /> fewer → more {label} (peak {peak})</span>
        <span><i className="sched-key now-key" /> open now in the game (small number = staffed now)</span>
        <span><i className="sched-key cut" /> open now, close it</span>
      </div>
    </div>
  );
}
