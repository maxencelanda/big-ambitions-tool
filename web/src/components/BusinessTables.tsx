import { Link } from "react-router-dom";
import { BusinessRow } from "../api";
import { change, money, percent, signedPercent } from "../format";
import { SeverityBadges } from "./Insights";
import { Column, SortableTable } from "./SortableTable";

export function businessLink(b: { address: string; name: string | null; status?: string }, label?: string) {
  const fallback = b.status === "closed" ? `Closed business · ${b.address}` : b.address;
  return <Link to={`/businesses/${encodeURIComponent(b.address)}`}>{label ?? b.name ?? fallback}</Link>;
}

const neg = (v: number | null | undefined) => ((v ?? 0) < 0 ? "neg" : undefined);

/** Centres de profit : CA, profit, évolution, marges, salaires, frais de structure répartis. */
const CURRENT_ONLY = ["delta", "employees", "satisfaction"];

/** ``period`` : tableau sur une période libre (P&L), sans comparaison ni état courant. */
export function ProfitCenterTable({ rows, showInsights = false, period = false }: { rows: BusinessRow[]; showInsights?: boolean; period?: boolean }) {
  const columns: Column<BusinessRow>[] = [
    { key: "name", label: "Business", value: (b) => b.name,
      render: (b) => <>{businessLink(b)} <span className="muted">{b.typeLabel}</span>{b.isNew && <> <span className="tag">new</span></>}</> },
    { key: "segment", label: "Segment", render: (b) => <span className="tag">{b.segment}</span> },
    { key: "revenue", label: "Revenue", num: true, render: (b) => money(b.revenue, { compactForm: false }) },
    { key: "operatingProfit", label: "Profit", num: true, className: (b) => neg(b.operatingProfit),
      render: (b) => money(b.operatingProfit, { compactForm: false }) },
    { key: "delta", label: "vs prev.", num: true, value: (b) => change(b.operatingProfit, b.previousOperatingProfit ?? null),
      className: (b) => neg(change(b.operatingProfit, b.previousOperatingProfit ?? null)),
      render: (b) => (b.isNew ? <span className="muted">new</span> : signedPercent(change(b.operatingProfit, b.previousOperatingProfit ?? null))) },
    { key: "margin", label: "Margin", num: true, render: (b) => percent(b.margin) },
    { key: "payrollRatio", label: "Payroll", num: true, title: "Salaries / revenue",
      className: (b) => ((b.payrollRatio ?? 0) > 0.5 ? "neg" : undefined), render: (b) => percent(b.payrollRatio) },
    { key: "allocatedOverhead", label: "Overhead", num: true, title: "Share of headquarters, warehouses and group staff costs",
      render: (b) => money(b.allocatedOverhead, { compactForm: false }) },
    { key: "profitAfterOverhead", label: "After overhead", num: true, className: (b) => neg(b.profitAfterOverhead),
      render: (b) => money(b.profitAfterOverhead, { compactForm: false }) },
    { key: "employees", label: "Staff", num: true },
    { key: "satisfaction", label: "Satisf.", num: true, title: "Customer satisfaction" },
  ];
  if (showInsights) {
    columns.push({ key: "insights", label: "Attention", value: (b) => (b.insights?.high ?? 0) * 100 + (b.insights?.medium ?? 0) * 10 + (b.insights?.low ?? 0),
                   render: (b) => <SeverityBadges counts={b.insights} /> });
  }
  const shown = period ? columns.filter((c) => !CURRENT_ONLY.includes(c.key)) : columns;
  return <SortableTable rows={rows} columns={shown} rowKey={(b) => b.address} initialSort="operatingProfit" />;
}

/** Centres de coût : siège, entrepôts — leur coût et ce qu'il représente. */
export function CostCenterTable({ rows, totalRevenue, period = false }: { rows: BusinessRow[]; totalRevenue: number; period?: boolean }) {
  const columns: Column<BusinessRow>[] = [
    { key: "name", label: "Cost center", value: (b) => b.name, render: (b) => <>{businessLink(b)} <span className="muted">{b.typeLabel}</span></> },
    { key: "segment", label: "Role", render: (b) => <span className="tag">{b.segment}</span> },
    { key: "operatingProfit", label: "Cost", num: true, className: () => "neg", render: (b) => money(b.operatingProfit, { compactForm: false }) },
    { key: "profitPerDay", label: "Per day", num: true, render: (b) => money(b.profitPerDay, { compactForm: false }) },
    { key: "salaries", label: "Salaries", num: true, render: (b) => money(b.salaries, { compactForm: false }) },
    { key: "rent", label: "Rent", num: true, render: (b) => money(b.rent, { compactForm: false }) },
    { key: "share", label: "% of revenue", num: true, title: "Cost as a share of total business revenue",
      value: (b) => (totalRevenue ? -b.operatingProfit / totalRevenue : null),
      render: (b) => percent(totalRevenue ? -b.operatingProfit / totalRevenue : null, 1) },
    { key: "employees", label: "Staff", num: true },
  ];
  const shown = period ? columns.filter((c) => !CURRENT_ONLY.includes(c.key)) : columns;
  return <SortableTable rows={rows} columns={shown} rowKey={(b) => b.address} initialSort="operatingProfit" initialDesc={false} />;
}
