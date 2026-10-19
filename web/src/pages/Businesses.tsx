import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { CostCenterTable, ProfitCenterTable } from "../components/BusinessTables";
import { CustomersOverview } from "../components/CustomersOverview";
import { WindowSelect } from "./Dashboard";

export function Businesses() {
  const [window, setWindow] = useState(7);
  const { data, isLoading, error } = useQuery({ queryKey: ["businesses", window], queryFn: () => api.businesses(window) });

  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error) return <div className="page"><div className="card empty">{(error as Error).message}</div></div>;
  if (!data || data.empty) return <div className="page"><div className="card empty">No data yet.</div></div>;

  const profitCenters = data.businesses.filter((b) => !b.costCenter);
  const costCenters = data.businesses.filter((b) => b.costCenter && b.segment !== "other");
  const totalRevenue = profitCenters.reduce((s, b) => s + b.revenue, 0);

  return (
    <div className="page">
      <h1>Businesses</h1>
      <p className="subtitle">Days {data.window.firstDay}–{data.window.lastDay} · <WindowSelect value={window} onChange={setWindow} /> · click a business for its detail page</p>
      <div className="card">
        <h2>Profit centers</h2>
        <p className="hint">Retail and office businesses: they are expected to make money</p>
        <ProfitCenterTable rows={profitCenters} showInsights />
      </div>
      <CustomersOverview />
      <div className="card section">
        <h2>Cost centers</h2>
        <p className="hint">Headquarters and warehouses: judged on cost and on the businesses they serve</p>
        <CostCenterTable rows={costCenters} totalRevenue={totalRevenue} />
      </div>
    </div>
  );
}
