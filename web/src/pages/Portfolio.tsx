import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, CandidateProduct, CurrentProduct, Portfolio as PortfolioData, PortfolioBusiness } from "../api";
import { businessLink } from "../components/BusinessTables";
import { baseOption, Chart, useThemeColors } from "../components/Chart";
import { Column, SortableTable } from "../components/SortableTable";
import { money, percent } from "../format";
import { WindowSelect } from "./Dashboard";

const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(2)}`);
const perDay = (v: number | null | undefined) => (v == null ? "—" : `${money(v)}/day`);

const VERDICT: Record<string, { label: string; className?: string }> = {
  close: { label: "Fix or sell", className: "neg" },
  "drop-effort": { label: "Not worth your time", className: "neg" },
  optimize: { label: "Optimize", className: "pos" },
  low: { label: "Low earner" },
  keep: { label: "Keep" },
  drop: { label: "Drop", className: "neg" },
  review: { label: "Review" },
  import: { label: "Import it", className: "pos" },
  automate: { label: "Automate" },
};

function Verdict({ v }: { v: string }) {
  const x = VERDICT[v] ?? { label: v };
  return <span className={`tag ${x.className ?? ""}`}>{x.label}</span>;
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Businesses({ data }: { data: PortfolioData }) {
  const columns: Column<PortfolioBusiness>[] = [
    { key: "name", label: "Business", render: (b) => <>{businessLink(b)} <span className="muted">{b.typeLabel}</span></> },
    { key: "profitPerDay", label: "Profit/day", num: true, title: "Operating profit per active day over the window (before HQ and warehouse costs)",
      render: (b) => <span className={b.profitPerDay < 0 ? "neg" : undefined}>{money(b.profitPerDay)}</span> },
    { key: "margin", label: "Margin", num: true, render: (b) => percent(b.margin) },
    { key: "capital", label: "Invested", num: true, title: "Purchase value of the furniture and equipment in the building", render: (b) => money(b.capital) },
    { key: "paybackDays", label: "Payback", num: true, title: "Days of profit to earn back what is invested", render: (b) => (b.paybackDays == null ? "—" : `${b.paybackDays.toFixed(0)} d`) },
    { key: "profitPerEmployee", label: "/employee", num: true, render: (b) => money(b.profitPerEmployee) },
    { key: "upside", label: "Within reach", num: true, value: (b) => b.likelyGainPerDay + b.productGainPerDay,
      title: "Reliable levers (hours, staffing, marketing, prices: high or medium confidence) + products to add or import",
      render: (b) => {
        const v = b.likelyGainPerDay + b.productGainPerDay;
        const lines = [...b.levers.map((l) => `${l.title}: +$${l.gainPerDay.toFixed(0)}/day (${l.confidence})`),
          b.productGainPerDay ? `Products (top 3 to add, imports): +$${b.productGainPerDay.toFixed(0)}/day` : ""].filter(Boolean);
        return v > 0 ? <span className="pos" title={lines.join("\n")}>+{money(v)}</span> : <span className="muted">—</span>;
      } },
    { key: "verdict", label: "Verdict", value: (b) => ["close", "drop-effort", "optimize", "low", "keep"].indexOf(b.verdict),
      render: (b) => <><Verdict v={b.verdict} /> <span className="muted">{b.reason}</span></>, className: () => "wrap" },
  ];
  return (
    <div className="card">
      <h2>Businesses</h2>
      <p className="hint">
        Profit per active day over days {data.firstDay}–{data.lastDay}. A typical business makes {money(data.typicalProfitPerDay)}/day (median).
        Hover “Within reach” for the levers; uncertain ideas (low confidence) are left out of it.
      </p>
      <SortableTable rows={data.businesses} columns={columns} rowKey={(b) => b.address} initialSort="profitPerDay" />
    </div>
  );
}

const PIE_COLORED = 5;

/** Classement par profit (après frais de structure) et part de chaque commerce dans le profit total. */
function Ranking({ data }: { data: PortfolioData }) {
  const t = useThemeColors();
  const profit = (b: PortfolioBusiness) => b.profitAfterOverheadPerDay ?? b.profitPerDay;
  const sorted = [...data.businesses].sort((a, b) => profit(b) - profit(a));
  const total = sorted.reduce((s, b) => s + Math.max(profit(b), 0), 0);
  let running = 0;
  type Row = PortfolioBusiness & { rank: number; profit: number; share: number; cumulative: number; roi: number | null };
  const rows: Row[] = sorted.map((b, i) => {
    const p = profit(b);
    running += Math.max(p, 0);
    return { ...b, rank: i + 1, profit: p, share: total ? p / total : 0, cumulative: total ? running / total : 0,
             roi: b.capital ? p / b.capital : null };
  });
  const colors = [t.series1, t.series2, t.series3, t.series4, t.series5];
  const option = useMemo(() => ({
    ...baseOption(t),
    tooltip: { ...baseOption(t).tooltip, trigger: "item",
      formatter: (p: { name: string; value: number; percent: number }) => `<b>${p.name}</b><br/>${money(p.value)}/day · ${p.percent.toFixed(1)} %` },
    series: [{
      type: "pie", radius: ["40%", "66%"], center: ["50%", "52%"], startAngle: 90,
      itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 },
      label: { color: t.secondary, fontSize: 11, formatter: (p: { name: string; percent: number }) => `${p.name}
${p.percent.toFixed(0)} %` },
      labelLine: { lineStyle: { color: t.axis } },
      data: rows.filter((r) => r.profit > 0).map((r, i) => ({
        name: r.name, value: Math.round(r.profit),
        // Les cinq premiers en couleur, les suivants en gris : leur nom reste au survol et dans le tableau.
        itemStyle: { color: i < PIE_COLORED ? colors[i] : t.muted, opacity: i < PIE_COLORED ? 1 : 0.55 },
        label: { show: r.share >= 0.04 },
        labelLine: { show: r.share >= 0.04 },
      })),
    }],
  }), [rows, t]);
  const columns: Column<Row>[] = [
    { key: "rank", label: "#", num: true },
    { key: "name", label: "Business", render: (r) => businessLink(r) },
    { key: "profit", label: "Profit/day", num: true, title: "After its share of HQ and warehouse costs",
      render: (r) => <span className={r.profit < 0 ? "neg" : undefined}>{money(r.profit)}</span> },
    { key: "share", label: "Share", num: true, render: (r) => percent(r.share, 1) },
    { key: "cumulative", label: "Cumulative", num: true, title: "Share of total profit made by this business and every one above it", render: (r) => percent(r.cumulative) },
    { key: "roi", label: "Return/day", num: true, title: "Profit per day / money invested in furniture and equipment", render: (r) => percent(r.roi, 1) },
    { key: "profitPerEmployee", label: "/employee", num: true, render: (r) => money(r.profitPerEmployee) },
    { key: "upside", label: "With levers", num: true, value: (r) => r.profit + r.likelyGainPerDay + r.productGainPerDay,
      title: "Profit/day if the reliable levers and product additions are applied", render: (r) => money(r.profit + r.likelyGainPerDay + r.productGainPerDay) },
  ];
  const top = rows.findIndex((r) => r.cumulative >= 0.8) + 1;
  return (
    <div className="card">
      <h2>Profit ranking</h2>
      <p className="hint">
        Profit per day after each business's share of HQ and warehouse costs: {money(total)}/day in all.
        The top {top} make 80 % of it. Closing a business loses its operating profit; most of its HQ and warehouse share stays.
      </p>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 3fr)", alignItems: "center" }}>
        <Chart option={option} height={360} label="Share of total profit per business" />
        <SortableTable rows={rows} columns={columns} rowKey={(r) => r.address} initialSort="rank" initialDesc={false} />
      </div>
    </div>
  );
}

function Products({ data }: { data: PortfolioData }) {
  const gain = (a: string) => (data.products[a]?.candidates ?? []).reduce((s, c) => s + c.marginPerDay, 0);
  const shops = data.businesses.filter((b) => data.products[b.address]).sort((a, b) => gain(b.address) - gain(a.address));
  const [address, setAddress] = useState(shops[0]?.address ?? "");
  const p = data.products[address];
  const current: Column<CurrentProduct>[] = [
    { key: "itemLabel", label: "Product", render: (c) => <>{c.itemLabel}{c.kind !== "product" && <span className="muted"> · {c.kind}</span>}</> },
    { key: "unitsPerDay", label: "Sold/day", num: true, render: (c) => c.unitsPerDay.toFixed(1) },
    { key: "price", label: "Price", num: true, render: (c) => usd(c.price) },
    { key: "unitCost", label: "Cost", num: true, title: "Average purchase cost of what was sold", render: (c) => usd(c.unitCost) },
    { key: "marginPerDay", label: "Margin/day", num: true, render: (c) => <span className={c.marginPerDay < 0 ? "neg" : undefined}>{money(c.marginPerDay)}</span> },
    { key: "share", label: "Share", num: true, title: "Share of the shop's product margin", render: (c) => percent(c.share, 1) },
    { key: "demand", label: "Demand", num: true, title: "Neighborhood demand (0–100)", render: (c) => c.demand ?? "—" },
    { key: "supply", label: "Supply", value: (c) => (c.imported ? 0 : 1),
      render: (c) => <span className="muted">{c.kind !== "product" ? "—" : `${c.imported ? "imported" : "bought"}${c.logistics ? " · logistics" : " · by hand"}`}</span> },
    { key: "verdict", label: "Verdict", value: (c) => ["drop", "review", "import", "automate", "keep"].indexOf(c.verdict),
      render: (c) => <><Verdict v={c.verdict} /> <span className="muted">{c.reason}</span></>, className: () => "wrap" },
  ];
  const candidates: Column<CandidateProduct>[] = [
    { key: "itemLabel", label: "Product", render: (c) => <>{c.itemLabel}{c.primary ? <span className="tag"> core</span> : null}</> },
    { key: "unitsPerDay", label: "Expected/day", num: true, title: "Units per day predicted by the game's formula, calibrated on this shop", render: (c) => c.unitsPerDay.toFixed(1) },
    { key: "price", label: "Price", num: true, title: "Highest price every customer of the neighborhood accepts", render: (c) => usd(c.price) },
    { key: "unitCost", label: "Cost", num: true, render: (c) => <>{usd(c.unitCost)} <span className="muted">{c.source}</span></> },
    { key: "marginPerDay", label: "Margin/day", num: true, render: (c) => <b className="pos">+{money(c.marginPerDay)}</b> },
    { key: "impact", label: "Fit", num: true, title: "How much this shop type sells it (1 = core product of the type)", render: (c) => percent(c.impact) },
    { key: "equipment", label: "Needs", value: (c) => (c.equipmentOwned ? 0 : c.equipmentCost ?? 1e9),
      render: (c) => <Needs c={c} /> },
    { key: "demand", label: "Demand", num: true, render: (c) => c.demand ?? "—" },
  ];
  if (!shops.length) return null;
  return (
    <div className="card">
      <h2>Products</h2>
      <p className="hint">
        In the game each product is drawn on its own: customers × sales ratio × neighborhood demand × satisfaction × how much the shop type sells it.
        Adding a product does not take sales from the others, and dropping one only loses its own margin. The formula is calibrated on each shop's real sales.
      </p>
      <div className="controls">
        <label>Shop
          <select value={address} onChange={(e) => setAddress(e.target.value)}>
            {shops.map((b) => <option key={b.address} value={b.address}>{b.name}</option>)}
          </select>
        </label>
        {p && <span className="muted">{p.customersPerDay.toFixed(0)} customers/day · real sales = {p.calibration.toFixed(2)} × formula</span>}
      </div>
      {p && (
        <>
          <h3>Sold now</h3>
          <SortableTable rows={p.current} columns={current} rowKey={(c) => c.item} initialSort="marginPerDay" />
          <h3 className="section">Worth adding</h3>
          {p.candidates.length
            ? <SortableTable rows={p.candidates} columns={candidates} rowKey={(c) => c.item} initialSort="marginPerDay" />
            : <p className="muted">Nothing worth a shelf: every product this shop type sells well is already there (services need their own station).</p>}
          {p.candidates.length > 0 && <p className="muted" style={{ fontSize: 12 }}>Each one needs shelf space and a supply (import contract or logistics target). Expect less if stock runs out.</p>}
        </>
      )}
    </div>
  );
}

function Needs({ c }: { c: CandidateProduct }) {
  if (c.equipmentOwned) return <span className="muted" title="Fits on furniture you already have, if it has room left">{c.equipmentOwned} (have one)</span>;
  if (c.equipment) return <span>{c.equipment} <span className="muted">${c.equipmentCost?.toLocaleString("en-US")} · pays back in {c.marginPerDay > 0 ? Math.max(1, Math.ceil((c.equipmentCost ?? 0) / c.marginPerDay)) : "—"} d</span></span>;
  return <span className="muted">—</span>;
}

function BestAdds({ data }: { data: PortfolioData }) {
  type Row = CandidateProduct & { business: PortfolioBusiness };
  const rows: Row[] = data.businesses.flatMap((b) => (data.products[b.address]?.candidates ?? []).map((c) => ({ ...c, business: b })));
  const columns: Column<Row>[] = [
    { key: "itemLabel", label: "Product" },
    { key: "business", label: "In", value: (r) => r.business.name, render: (r) => businessLink(r.business) },
    { key: "unitsPerDay", label: "Expected/day", num: true, render: (r) => r.unitsPerDay.toFixed(1) },
    { key: "marginPerDay", label: "Margin/day", num: true, render: (r) => <b className="pos">+{money(r.marginPerDay)}</b> },
    { key: "source", label: "Supply", render: (r) => <span className="muted">{r.source}</span> },
    { key: "equipment", label: "Needs", value: (r) => (r.equipmentOwned ? 0 : r.equipmentCost ?? 1e9), render: (r) => <Needs c={r} /> },
  ];
  return (
    <div className="card">
      <h2>Best products to add</h2>
      <SortableTable rows={rows} columns={columns} rowKey={(r) => `${r.business.address}|${r.item}`} initialSort="marginPerDay" maxHeight={380} />
    </div>
  );
}

function Lessons({ data }: { data: PortfolioData }) {
  const rows = useMemo(() => {
    const by = new Map<string, PortfolioBusiness[]>();
    for (const b of data.businesses) by.set(b.typeLabel, [...(by.get(b.typeLabel) ?? []), b]);
    return [...by.entries()].map(([type, list]) => {
      const profit = list.reduce((s, b) => s + b.profitPerDay, 0) / list.length;
      const capital = list.reduce((s, b) => s + b.capital, 0) / list.length;
      return { type, count: list.length, profit, capital, payback: profit > 0 ? capital / profit : null,
               perEmployee: list.reduce((s, b) => s + (b.profitPerEmployee ?? 0), 0) / list.length };
    });
  }, [data]);
  type Row = (typeof rows)[number];
  const columns: Column<Row>[] = [
    { key: "type", label: "Business type", render: (r) => <>{r.type} <span className="muted">×{r.count}</span></> },
    { key: "profit", label: "Profit/day", num: true, title: "Average per business", render: (r) => money(r.profit) },
    { key: "capital", label: "Invested", num: true, render: (r) => money(r.capital) },
    { key: "payback", label: "Payback", num: true, render: (r) => (r.payback == null ? "—" : `${r.payback.toFixed(0)} d`) },
    { key: "perEmployee", label: "/employee", num: true, render: (r) => money(r.perEmployee) },
  ];
  return (
    <div className="card">
      <h2>What pays best, by type</h2>
      <p className="hint">From your own businesses. For a new one, also check demand and free buildings in Market: a 4th agency of a type earns less once the neighborhood has enough providers.</p>
      <SortableTable rows={rows} columns={columns} rowKey={(r) => r.type} initialSort="profit" />
    </div>
  );
}

export function Portfolio() {
  const [window, setWindow] = useState(14);
  const { data, isLoading, error } = useQuery({ queryKey: ["portfolio", window], queryFn: () => api.portfolio(window) });
  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error || !data || data.empty) return <div className="page"><div className="card empty">{(error as Error)?.message ?? "No data"}</div></div>;
  const s = data.summary;
  const review = data.businesses.filter((b) => b.verdict === "close" || b.verdict === "drop-effort" || b.verdict === "low");
  return (
    <div className="page">
      <h1>Portfolio</h1>
      <p className="subtitle">What each business earns, what it could earn, and which products to add or drop · <WindowSelect value={window} onChange={setWindow} /></p>
      <div className="grid tiles">
        <Tile label="Profit" value={perDay(s.profitPerDay)} sub="all shops and offices, before HQ and warehouses" />
        <Tile label="Reliable levers" value={`+${perDay(s.likelyGainPerDay)}`} sub="hours, staffing, marketing, prices" />
        <Tile label="Products" value={`+${perDay(s.productGainPerDay)}`} sub="top 3 additions per shop + imports" />
        <Tile label="Invested" value={money(s.capital)} sub="furniture and equipment" />
        <Tile label="To review" value={String(review.length)} sub={review.length ? review.map((b) => b.name).join(", ") : "every business pulls its weight"} />
      </div>
      <div className="section"><Ranking data={data} /></div>
      <div className="section"><Businesses data={data} /></div>
      <div className="section"><Products data={data} /></div>
      <div className="grid two section">
        <BestAdds data={data} />
        <Lessons data={data} />
      </div>
    </div>
  );
}
