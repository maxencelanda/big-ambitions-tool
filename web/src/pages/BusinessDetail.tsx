import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, BusinessDetail as Detail, Employee, Product } from "../api";
import { businessLink } from "../components/BusinessTables";
import { baseOption, Chart, ThemeColors, useThemeColors } from "../components/Chart";
import { InsightList } from "../components/Insights";
import { Column, SortableTable } from "../components/SortableTable";
import { change, money, percent, signedPercent } from "../format";
import { WindowSelect } from "./Dashboard";

function Tile({ label, value, sub }: { label: string; value: string; sub?: React.ReactNode }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function DailyChart({ data, t, days }: { data: Detail; t: ThemeColors; days: number }) {
  const daily = data.daily.slice(-Math.max(days * 3, 21));
  const option = useMemo(() => ({
    ...baseOption(t),
    legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.secondary } },
    grid: { ...baseOption(t).grid, top: 30 },
    tooltip: { ...baseOption(t).tooltip, trigger: "axis", valueFormatter: (v: number) => money(v, { compactForm: false }) },
    xAxis: { type: "category", data: daily.map((d) => String(d.day)), boundaryGap: false, axisTick: { show: false },
             axisLine: { lineStyle: { color: t.axis } }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted, formatter: (v: number) => money(v) } },
    series: [
      { name: "Revenue", type: "line", data: daily.map((d) => Math.round(d.sales)), showSymbol: false, symbolSize: 8,
        lineStyle: { width: 2, color: t.series1 }, itemStyle: { color: t.series1 }, areaStyle: { color: t.series1, opacity: 0.1 } },
      { name: "Operating profit", type: "line", data: daily.map((d) => Math.round(d.profit)), showSymbol: false, symbolSize: 8,
        lineStyle: { width: 2, color: t.series2 }, itemStyle: { color: t.series2 } },
    ],
  }), [daily, t]);
  return <Chart option={option} height={280} label="Daily revenue and operating profit" />;
}

function CustomersChart({ data, t }: { data: Detail; t: ThemeColors }) {
  const points = data.daily.filter((d) => d.customers != null);
  const option = useMemo(() => ({
    ...baseOption(t),
    tooltip: { ...baseOption(t).tooltip, trigger: "axis" },
    xAxis: { type: "category", data: points.map((d) => String(d.day)), axisTick: { show: false },
             axisLine: { lineStyle: { color: t.axis } }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted } },
    series: [{ name: "Customers", type: "bar", barMaxWidth: 24, itemStyle: { color: t.series1, borderRadius: [4, 4, 0, 0] },
               data: points.map((d) => d.customers) }],
  }), [points, t]);
  return <Chart option={option} height={240} label="Customers per day" />;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function MarketingCard({ data }: { data: Detail }) {
  const m = data.marketing!;
  const office = data.business?.segment === "office";
  return (
    <div className="card">
      <h2>Marketing</h2>
      <p className="hint">
        Promotion = traffic {m.trafficIndex} + reach × {m.marketingStrength} (neighborhood), max 100; reach = campaign m² / {m.sqm} m².
        Customers then stop at {office ? "the staffed desks" : "the customer capacity and service stations"}
        {m.saturationPromotion != null && <>: nothing more comes in above promotion <b>{m.saturationPromotion}</b></>}.
        {m.valuePerCustomer != null && <> A customer brings {money(m.valuePerCustomer)} of gross margin.</>}
      </p>
      <div className="mk-lines">
        <div><span className="muted">Now</span> {m.currentCampaigns} · {money(m.currentCost)}/day · promotion {m.currentPromotion}</div>
        <div>
          <span className="muted">Best</span> <b>{m.bestCampaigns}</b> · {money(m.bestCost)}/day · promotion {m.bestPromotion}
          {(m.gainPerDay ?? 0) >= 1 ? <span className="impact"> +{money(m.gainPerDay)}/day</span> : <span className="muted"> (already the best)</span>}
        </div>
        {m.samePromotionCampaigns && m.samePromotionCampaigns !== m.bestCampaigns && (
          <div><span className="muted">Same promotion, cheaper</span> {m.samePromotionCampaigns} · {money(m.samePromotionCost)}/day</div>
        )}
      </div>
      <div className="table-wrap" style={{ maxHeight: 260, overflowY: "auto" }}>
        <table>
          <thead><tr><th className="num">Promotion</th><th>Cheapest campaigns</th><th className="num">Cost</th><th className="num">Customers/day</th><th className="num" title="Gross margin of the customers minus the campaigns">Margin − cost</th></tr></thead>
          <tbody>
            {data.marketingOptions.map((o) => (
              <tr key={o.campaigns} style={o.best ? { fontWeight: 600 } : undefined}>
                <td className="num">{o.promotion}</td>
                <td>{o.campaigns}{Boolean(o.current) && <span className="tag"> now</span>}{Boolean(o.best) && <span className="tag"> best</span>}</td>
                <td className="num">{money(o.cost)}</td>
                <td className="num">{o.customersPerDay.toFixed(1)}</td>
                <td className="num">{money(o.profitPerDay)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        Game formulas, calibrated on the {m.observedCustomersPerDay.toFixed(0)} customers/day observed
        {m.calibration < 0.95 ? ` (${percent(1 - m.calibration)} of modeled customers do not buy)` : ""}.
      </p>
    </div>
  );
}

function StaffingCard({ data, t }: { data: Detail; t: ThemeColors }) {
  const s = data.staffing!;
  const days = [...new Set(data.staffingHours.map((h) => h.day))].sort();
  const [day, setDay] = useState(days[0]);
  const hours = data.staffingHours.filter((h) => h.day === day);
  const option = useMemo(() => ({
    ...baseOption(t),
    legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.secondary } },
    grid: { ...baseOption(t).grid, top: 30 },
    tooltip: { ...baseOption(t).tooltip, trigger: "axis", formatter: (items: { dataIndex: number }[]) => {
      const h = hours[items[0].dataIndex];
      return `${h.hour}:00 — ${h.expectedCustomers.toFixed(1)} customers expected<br/>Staffed ${h.staffedStations} · needed ${h.neededStations}`
        + (h.idleStations ? `<br/>${h.idleStations} idle (${money(h.idleWages, { compactForm: false })}/h)` : "");
    } },
    xAxis: { type: "category", data: hours.map((h) => `${h.hour}h`), axisTick: { show: false },
             axisLine: { lineStyle: { color: t.axis } }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted } },
    series: [
      { name: "Staffed", type: "bar", barMaxWidth: 16, itemStyle: { color: t.series1, borderRadius: [4, 4, 0, 0] }, data: hours.map((h) => h.staffedStations) },
      { name: "Needed", type: "bar", barMaxWidth: 16, itemStyle: { color: t.series2, borderRadius: [4, 4, 0, 0] }, data: hours.map((h) => h.neededStations) },
    ],
  }), [hours, t]);
  const label = { desk: "desks", hairdresserchair: "hairdresser chairs", checkoutcounter: "checkouts", cashregister: "cash registers" }[s.stationKind] ?? "stations";
  return (
    <div className="card">
      <h2>Staffing</h2>
      <p className="hint">
        Staffed {label} vs needed (expected customers ÷ {s.customersPerStationHour}/hour per station, +20 % margin).
        {" "}{s.idleStationHoursPerWeek} of {s.staffedStationHoursPerWeek} staffed hours/week are idle
        {s.idleWagesPerWeek ? ` ≈ ${money(s.idleWagesPerWeek)}/week of wages` : ""}.
      </p>
      <div className="segmented" role="group" aria-label="Day" style={{ marginBottom: 8 }}>
        {days.map((d) => <button key={d} className={d === day ? "on" : ""} onClick={() => setDay(d)}>{WEEKDAYS[d - 1]}</button>)}
      </div>
      <Chart option={option} height={220} label="Staffed and needed stations per hour" />
    </div>
  );
}

const productColumns: Column<Product>[] = [
  { key: "label", label: "Product" },
  { key: "unitsPerDay", label: "Units/day", num: true },
  { key: "revenue", label: "Revenue", num: true, render: (p) => money(p.revenue, { compactForm: false }) },
  { key: "marginRate", label: "Margin", num: true, render: (p) => percent(p.marginRate) },
  { key: "price", label: "Price", num: true, render: (p) => (p.price != null ? `$${p.price.toFixed(2)}` : "—") },
  { key: "ceiling", label: "Ceiling", num: true, title: "Highest price every customer of the neighborhood accepts (game formula)",
    render: (p) => (p.ceiling != null ? `$${p.ceiling.toFixed(2)}` : "—") },
  { key: "headroom", label: "Headroom", num: true, className: (p) => ((p.headroom ?? 0) < -0.005 ? "neg" : undefined),
    render: (p) => (p.headroom != null ? `$${p.headroom.toFixed(2)}` : "—") },
  { key: "lowestCompetitorPrice", label: "Cheapest rival", num: true,
    render: (p) => (p.lowestCompetitorPrice != null ? <span title={p.lowestCompetitor ?? undefined}>${p.lowestCompetitorPrice.toFixed(2)}</span> : "—") },
  { key: "monopoly", label: "Monopoly", render: (p) => (p.monopoly ? <span className="tag">monopoly</span> : "") },
  { key: "stock", label: "Stock", num: true, render: (p) => (p.stock != null ? p.stock.toLocaleString("en-US") : "—") },
  { key: "daysOfCover", label: "Days of stock", num: true, className: (p) => ((p.daysOfCover ?? 99) < 2 ? "neg" : undefined) },
];

const employeeColumns: Column<Employee>[] = [
  // SQLite renvoie les booléens en 0/1 : on les convertit pour ne pas afficher de « 0 ».
  { key: "name", label: "Employee", render: (e) => <>
    <span className={e.status === "poached" ? "muted" : undefined}>{e.name}</span>
    {e.status === "poached" && <> <span className="tag" title={e.beingReplaced ? "The headhunter is replacing them" : undefined}>poached{e.beingReplaced ? " · being replaced" : ""}</span></>}
    {Boolean(e.isAbsent) && <> <span className="tag">absent</span></>}
    {Boolean(e.isComplaining) && <> <span className="tag">complaining</span></>}
  </> },
  { key: "mainSkillValue", label: "Main skill", num: true, render: (e) => `${e.mainSkill ?? "—"} ${e.mainSkillValue?.toFixed(0) ?? ""}` },
  { key: "satisfaction", label: "Satisfaction", num: true, className: (e) => (e.satisfaction < 75 ? "neg" : undefined), render: (e) => e.satisfaction.toFixed(0) },
  { key: "hourlyWage", label: "Wage/h", num: true, render: (e) => `$${e.hourlyWage.toFixed(2)}` },
  { key: "weeklyHours", label: "Hours/week", num: true },
  { key: "dayHired", label: "Hired", num: true, render: (e) => `day ${e.dayHired}` },
  { key: "demands", label: "Demands" },
];

function Meter({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="meter">
      <span>{label}</span>
      <span className="track"><span className={`fill ${(value ?? 0) < 90 ? "low" : ""}`} style={{ width: `${value ?? 0}%`, display: "block" }} /></span>
      <span className="val">{value ?? "—"}</span>
    </div>
  );
}

export function BusinessDetail() {
  const { address = "" } = useParams();
  const [window, setWindow] = useState(7);
  const t = useThemeColors();
  const { data, isLoading, error } = useQuery({ queryKey: ["business", address, window], queryFn: () => api.business(address, window) });

  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error || !data) return <div className="page"><div className="card empty">{error ? (error as Error).message : "Not found"}</div></div>;

  const b = data.business;
  const p = data.pnl;
  const customerFacing = b.segment === "retail" || b.segment === "office";
  const customers = data.daily.slice(-window).filter((d) => d.customers != null);
  const avgCustomers = customers.length ? customers.reduce((s, d) => s + (d.customers ?? 0), 0) / customers.length : null;

  return (
    <div className="page">
      <div className="crumbs"><Link to="/businesses">Businesses</Link> / {b.name ?? address}</div>
      <div className="page-header">
        <h1>{b.name ?? (b.status === "closed" ? "Closed business" : address)}</h1>
        <span className="muted">{b.typeLabel} · {address} · {b.neighborhood ?? data.building?.neighborhood}</span>
        <span className="tag">{b.segment}</span>
        {b.status === "closed" && <span className="tag">closed</span>}
      </div>
      <p className="subtitle">Days {data.window.firstDay}–{data.window.lastDay} · <WindowSelect value={window} onChange={setWindow} /></p>

      {p && (
        <div className="grid tiles">
          {customerFacing ? (
            <>
              <Tile label="Revenue" value={money(p.revenue)} sub={p.revenueShare != null ? `${percent(p.revenueShare)} of group revenue` : undefined} />
              <Tile label="Operating profit" value={money(p.operatingProfit)}
                    sub={p.isNew ? "new business" : `${signedPercent(change(p.operatingProfit, p.previousOperatingProfit ?? null))} vs previous ${window} days`} />
              <Tile label="Margin" value={percent(p.margin)} sub={`gross ${percent(p.grossMarginRate)}`} />
              <Tile label="After overhead" value={money(p.profitAfterOverhead)} sub={`${money(p.allocatedOverhead)} allocated`} />
              <Tile label="Payroll / revenue" value={percent(p.payrollRatio)} sub={`${money(-p.salaries)} of salaries`} />
              <Tile label="Customers / day" value={avgCustomers != null ? avgCustomers.toFixed(0) : "—"} sub={`capacity ${b.customerCapacity ?? "—"} at once`} />
            </>
          ) : (
            <>
              <Tile label="Cost" value={money(p.operatingProfit)} sub={`${money(p.profitPerDay)} per day`} />
              <Tile label="Salaries" value={money(p.salaries)} sub={`${b.employees ?? 0} employees`} />
              <Tile label="Rent" value={money(p.rent)} sub={`${data.building?.sqm ?? "—"} m²`} />
            </>
          )}
        </div>
      )}

      <div className="grid two section">
        <div className="card">
          <h2>Revenue & profit per day</h2>
          <p className="hint">Operating profit before overhead</p>
          <DailyChart data={data} t={t} days={window} />
        </div>
        <div className="card">
          <h2>Attention points</h2>
          <p className="hint">Click a point for the numbers and the suggested action</p>
          <InsightList insights={data.insights} showBusiness={false} />
        </div>
      </div>

      {customerFacing && (
        <div className="grid two section">
          <div className="card">
            <h2>Customers per day</h2>
            <p className="hint">From daily sales; the game keeps about 16 days, the history grows with every import</p>
            <CustomersChart data={data} t={t} />
          </div>
          {data.staffing ? <StaffingCard data={data} t={t} /> : <div className="card"><h2>Staffing</h2><p className="muted">No service station to analyse.</p></div>}
        </div>
      )}

      {data.marketing && <div className="section"><MarketingCard data={data} /></div>}

      {data.products.length > 0 && (
        <div className="card section">
          <h2>Products & prices</h2>
          <p className="hint">Sales over the window, current price against the game's acceptance ceiling, competition and stock</p>
          <SortableTable rows={data.products} columns={productColumns} rowKey={(r) => r.item} initialSort="revenue" />
        </div>
      )}

      <div className="grid three section">
        {customerFacing && (
          <div className="card">
            <h2>Customer satisfaction</h2>
            <p className="hint">Overall {b.satisfaction ?? "—"} · promotion {b.promotion ?? "—"} (traffic {b.trafficIndex ?? "—"})</p>
            <Meter label="Customer service" value={b.satCustomerService} />
            <Meter label="Pricing" value={b.satPricing} />
            <Meter label="Cleanliness" value={b.satCleanliness} />
            <Meter label="Facility" value={b.satFacility} />
          </div>
        )}
        <div className="card">
          <h2>Building</h2>
          <dl className="kv">
            <dt>Size</dt><dd>{data.building?.sqm ?? "—"} m²</dd>
            <dt>Traffic index</dt><dd>{data.building?.trafficIndex ?? "—"}</dd>
            <dt>Rent</dt><dd>{b.rentPerDay != null ? `${money(b.rentPerDay)}/day` : "—"}</dd>
            <dt>Opening</dt><dd>{b.openDaysPerWeek ?? "—"} days/week, {b.openHours || "—"}</dd>
            <dt>Opened</dt><dd>{b.creationDay != null && b.creationDay >= 0 ? `day ${b.creationDay}` : "—"}</dd>
            <dt>Furniture</dt><dd>{money(b.furnitureValue)}</dd>
          </dl>
        </div>
        <div className="card">
          <h2>Logistics</h2>
          {data.suppliers.length > 0 && (
            <p className="hint">Supplied by {[...new Set(data.suppliers.map((s) => s.sourceBusiness ?? s.sourceAddress))].join(", ")}: {data.suppliers.length} stock target(s)</p>
          )}
          {data.serves.length > 0 && (
            <>
              <p className="hint">Delivers to:</p>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {[...new Map(data.serves.map((s) => [s.destinationAddress, s])).values()].map((s) => (
                  <li key={s.destinationAddress}>{businessLink({ address: s.destinationAddress, name: s.destinationBusiness })}
                    {" "}<span className="muted">({data.serves.filter((x) => x.destinationAddress === s.destinationAddress).length} products)</span></li>
                ))}
              </ul>
            </>
          )}
          {!data.suppliers.length && !data.serves.length && <p className="muted">No logistics manager plan involves this building.</p>}
        </div>
      </div>

      {data.employees.length > 0 && (
        <div className="card section">
          <h2>Staff ({data.employees.filter((e) => e.status !== "poached").length})</h2>
          <p className="hint">Customer service counts each employee's skill × satisfaction</p>
          <SortableTable rows={data.employees} columns={employeeColumns} rowKey={(e) => e.id} initialSort="satisfaction" initialDesc={false} />
        </div>
      )}
    </div>
  );
}
