import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, MarketEvent, MarketRow, Opportunity, Rival, Supplier } from "../api";
import { Column, SortableTable } from "../components/SortableTable";
import { money } from "../format";

const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(2)}`);
const NEIGHBORHOODS = [
  ["garmentdistrict", "Garment District"], ["hellskitchen", "Hell's Kitchen"], ["murrayhill", "Murray Hill"],
  ["midtown", "Midtown"], ["lowermanhattan", "Lower Manhattan"], ["industrycity", "Industry City"], ["thehamptons", "The Hamptons"],
];
const EVENT_LABEL: Record<string, string> = {
  business_opened: "Opened", business_closed: "Closed", hype: "Hype", shortage: "Shortage", backorder: "Backorder",
  large_player_purchase: "Large purchase", max_providers_exceeded: "Too many providers",
};

const SCORE_PARTS: { key: keyof Opportunity["components"]; label: string; weight: number; explain: string }[] = [
  { key: "demand", label: "Demand", weight: 35, explain: "demand of what it sells once you open (you become one more provider)" },
  { key: "room", label: "Room", weight: 20, explain: "how far providers are below the number the market absorbs" },
  { key: "monopoly", label: "Monopoly", weight: 15, explain: "share of its products no rival shop sells" },
  { key: "location", label: "Location", weight: 20, explain: "traffic of the best free space and how heavy its rent is" },
  { key: "margin", label: "Margin", weight: 10, explain: "unit margin at the optimal price, as a share of the price" },
];

function ScoreBar({ score }: { score: number }) {
  return (
    <span className="scorebar" title={`${score.toFixed(0)} / 100`}>
      <span className="track"><span className="fill" style={{ width: `${score}%` }} /></span>
      <b>{score.toFixed(0)}</b>
    </span>
  );
}

function OpportunityCard({ o }: { o: Opportunity }) {
  const space = o.bestSpaces[0];
  return (
    <div className="card opp-card">
      <div className="opp-head">
        <div>
          <div className="opp-title">{o.label}</div>
          <div className="muted">{o.neighborhoodLabel} · {o.segment}</div>
        </div>
        <div className="opp-score" title="Opportunity score out of 100">{o.score.toFixed(0)}</div>
      </div>
      <div className="opp-parts">
        {SCORE_PARTS.map((p) => (
          <div key={p.key} className="meter" title={`${p.label} (${p.weight} % of the score): ${p.explain}`}>
            <span>{p.label}</span>
            <span className="track"><span className="fill" style={{ width: `${o.components[p.key] * 100}%`, display: "block" }} /></span>
            <span className="val">{Math.round(o.components[p.key] * 100)}</span>
          </div>
        ))}
      </div>
      <ul className="reasons">
        {o.pros.map((r) => <li key={r} className="pro">✓ {r}</li>)}
        {o.cons.map((r) => <li key={r} className="con">✗ {r}</li>)}
      </ul>
      {space && (
        <p className="opp-space">
          Best space: <b>{space.address}</b> · traffic {space.traffic} · {space.sqm.toLocaleString("en-US")} m² · ≈{money(space.rent)}/day
          {o.freeBuildings > 1 && <span className="muted"> · {o.freeBuildings - 1} other free space(s)</span>}
        </p>
      )}
    </div>
  );
}

function Opportunities() {
  const [segment, setSegment] = useState("all");
  const [onlyFree, setOnlyFree] = useState(true);
  const [hideMine, setHideMine] = useState(true);
  const [details, setDetails] = useState(false);
  const { data = [], isLoading } = useQuery({ queryKey: ["opportunities"], queryFn: api.opportunities });
  const rows = data.filter((o) => (segment === "all" || o.segment === segment) && (!onlyFree || o.freeBuildings > 0)
    && (!hideMine || !o.playerBusinesses));
  // Meilleures pistes : uniquement là où l'on peut ouvrir aujourd'hui (local libre).
  const top = rows.filter((o) => o.freeBuildings > 0).slice(0, 6);

  const columns: Column<Opportunity>[] = [
    { key: "score", label: "Score", render: (o) => <ScoreBar score={o.score} />,
      title: "Opportunity score out of 100 (see “How the score works”)" },
    { key: "label", label: "Business type", render: (o) => <>{o.label} <span className="muted">{o.segment}</span>
      {o.activeEvents && <> <span className="tag">{o.activeEvents}</span></>}</> },
    { key: "neighborhoodLabel", label: "Neighborhood" },
    { key: "demandAfter", label: "Demand", num: true, title: "Demand of its products now → once you open",
      render: (o) => <>{o.avgDemand.toFixed(0)} <span className="muted">→ {o.demandAfter.toFixed(0)}</span></> },
    { key: "cannibalizedPerDay", label: "Takes from you", num: true, title: "Revenue per day your shops here would lose to the lower demand",
      className: (o) => (o.cannibalizedPerDay >= 1 ? "neg" : undefined), render: (o) => (o.cannibalizedPerDay >= 1 ? `${money(o.cannibalizedPerDay)}/d` : "—") },
    { key: "saturation", label: "Saturation", num: true, title: "Providers ÷ number the market absorbs (100 % = full)",
      className: (o) => (o.saturation >= 1 ? "neg" : undefined), render: (o) => `${Math.round(o.saturation * 100)}%` },
    { key: "monopolyPossibleProducts", label: "Monopoly possible", num: true, title: "Products no rival shop sells here",
      render: (o) => `${o.monopolyPossibleProducts}/${o.productsWithDemand}` },
    { key: "bestSpace", label: "Best free space", value: (o) => o.components.location,
      render: (o) => (o.bestSpaces[0] ? <span title={o.bestSpaces.map((s) => `${s.address}: traffic ${s.traffic}, ${s.sqm} m², ≈${money(s.rent)}/day`).join("\n")}>
        traffic {o.bestSpaces[0].traffic} · ≈{money(o.bestSpaces[0].rent)}/d</span> : <span className="muted">none</span>) },
    { key: "playerBusinesses", label: "Yours", render: (o) => o.playerBusinesses ?? "" },
  ];
  const extra: Column<Opportunity>[] = [
    { key: "rivalSellers", label: "Rival shops", num: true, title: "Most rival-owned shops on one of its products" },
    { key: "sameTypeCompetitors", label: "Same type", num: true, title: "Existing businesses of this type in the neighborhood" },
    { key: "avgUnitMargin", label: "Unit margin", num: true, render: (o) => usd(o.avgUnitMargin) },
    { key: "avgPrice", label: "Avg price", num: true, title: "Average optimal price of its products", render: (o) => usd(o.avgPrice) },
    { key: "freeBuildings", label: "Free spaces", num: true },
  ];

  return (
    <>
      <div className="card">
        <h2>Where to open next</h2>
        <p className="hint">Each business type you can create, in each neighborhood, gets an <b>opportunity score out of 100</b>. Top picks only include places with a free building today.</p>
        <div className="controls">
          <label>Segment
            <select value={segment} onChange={(e) => setSegment(e.target.value)}>
              <option value="all">All</option><option value="retail">Retail</option><option value="office">Office</option>
            </select>
          </label>
          <label className="toggle"><input type="checkbox" checked={onlyFree} onChange={(e) => setOnlyFree(e.target.checked)} /> Only with a free space</label>
          <label className="toggle"><input type="checkbox" checked={hideMine} onChange={(e) => setHideMine(e.target.checked)} /> Hide where I already run one</label>
        </div>
        <details className="explain">
          <summary>How the score works</summary>
          <p>Score = weighted sum of five parts (each 0–100), minus up to 20 points for cannibalization.
            It is a ranking aid built on the game's own formulas — not a revenue forecast.</p>
          <ul>{SCORE_PARTS.map((p) => <li key={p.key}><b>{p.label}</b> ({p.weight} %) — {p.explain}</li>)}</ul>
          <p>How the game works: demand = 100 − providers × 100 ÷ optimal providers (never below ≈30), and your own shops count as providers.
            Opening here adds a provider to each of its products, which lowers demand for your existing shops selling them too:
            “takes ≈ $/day” is that loss on their last 7 days of sales. Office businesses get customers in proportion to demand;
            retail customers come from the building and promotion, demand sets how much they buy.</p>
        </details>
      </div>

      {isLoading ? <div className="card empty section">Loading…</div> : (
        <div className="opp-grid section">
          {top.map((o) => <OpportunityCard key={`${o.businessType}|${o.neighborhood}`} o={o} />)}
          {!top.length && <div className="card empty">No option matches these filters.</div>}
        </div>
      )}

      <div className="card section">
        <div className="controls" style={{ marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>All options</h2>
          <span className="muted">{rows.length} option(s)</span>
          <label className="toggle"><input type="checkbox" checked={details} onChange={(e) => setDetails(e.target.checked)} /> More columns</label>
        </div>
        <SortableTable rows={rows} columns={details ? [...columns, ...extra] : columns}
                       rowKey={(o) => `${o.businessType}|${o.neighborhood}`} initialSort="score" />
      </div>
    </>
  );
}

function Products() {
  const [neighborhood, setNeighborhood] = useState("garmentdistrict");
  const [onlyMine, setOnlyMine] = useState(false);
  const { data = [], isLoading } = useQuery({ queryKey: ["market", neighborhood], queryFn: () => api.market(neighborhood) });
  const rows = data.filter((r) => !onlyMine || r.playerSells);
  const columns: Column<MarketRow>[] = [
    { key: "itemLabel", label: "Product" },
    { key: "demand", label: "Demand", num: true },
    { key: "providers", label: "Providers", num: true, render: (r) => `${r.providers} / ${r.optimalProviders}`, title: "Current / optimal number of providers" },
    { key: "rivalSellers", label: "Rival shops", num: true },
    { key: "playerSells", label: "You", render: (r) => (r.monopoly ? <span className="tag">monopoly</span> : r.playerSells ? <span className="tag">selling</span> : r.monopolyPossible ? <span className="muted">no rival</span> : "") },
    { key: "playerPrice", label: "Your price", num: true, render: (r) => usd(r.playerPrice) },
    { key: "lowestCompetitorPrice", label: "Cheapest rival", num: true, render: (r) => (r.lowestCompetitorPrice != null ? <span title={r.lowestCompetitor ?? ""}>{usd(r.lowestCompetitorPrice)}</span> : "—") },
    { key: "ceiling", label: "Ceiling", num: true, render: (r) => usd(r.ceiling) },
    { key: "purchasePriceEstimate", label: "Purchase", num: true, title: "Wholesale price × import index × difficulty × shortage", render: (r) => usd(r.purchasePriceEstimate) },
    { key: "unitMarginAtOptimal", label: "Margin at optimal", num: true, render: (r) => usd(r.unitMarginAtOptimal) },
    { key: "importPriceIndex", label: "Import index", num: true, render: (r) => (r.importPriceIndex ? r.importPriceIndex.toFixed(2) : "—") },
    { key: "suppliers", label: "Where to buy", render: (r) => (r.suppliers
      ? <span className="muted" title={r.suppliers}>{r.suppliers.length > 40 ? `${r.suppliers.slice(0, 40)}…` : r.suppliers}</span> : "") },
    { key: "activeEvents", label: "Events", render: (r) => (r.activeEvents ? `${r.activeEvents}${r.eventDemandImpact ? ` (${r.eventDemandImpact > 0 ? "+" : ""}${r.eventDemandImpact})` : ""}` : "") },
  ];
  return (
    <div className="card">
      <h2>Products by neighborhood</h2>
      <p className="hint">Market Insider data plus what the game does not show: the acceptance ceiling, rival shops blocking a monopoly, purchase price and unit margin.</p>
      <div className="controls">
        <div className="segmented" role="group" aria-label="Neighborhood">
          {NEIGHBORHOODS.map(([key, label]) => (
            <button key={key} className={key === neighborhood ? "on" : ""} onClick={() => setNeighborhood(key)}>{label}</button>
          ))}
        </div>
        <label className="toggle"><input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} /> Only what I sell</label>
        <span className="muted">{isLoading ? "Loading…" : `${rows.length} product(s)`}</span>
      </div>
      <SortableTable rows={rows} columns={columns} rowKey={(r) => r.item} initialSort="demand" />
    </div>
  );
}

const KIND_LABEL: Record<Supplier["kind"], string> = { importer: "import", wholesaler: "wholesale", factory: "factory" };

function Suppliers() {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  const [mine, setMine] = useState(false);
  const { data = [], isLoading } = useQuery({ queryKey: ["suppliers"], queryFn: () => api.suppliers() });
  const needle = search.trim().toLowerCase();
  const rows = data.filter((s) => (kind === "all" || s.kind === kind) && (!mine || s.contractAmount != null)
    && (!needle || s.itemLabel.toLowerCase().includes(needle) || s.supplier.toLowerCase().includes(needle)));
  const columns: Column<Supplier>[] = [
    { key: "itemLabel", label: "Product" },
    { key: "supplier", label: "Supplier", render: (s) => (s.kind === "factory"
      ? <>{s.supplier}<div className="muted" style={{ whiteSpace: "normal", maxWidth: 520, fontSize: 12 }}>{s.ingredients}</div></>
      : <>{s.supplier} <span className="muted">· {s.address}</span></>) },
    { key: "kind", label: "Type", render: (s) => <>
      <span className="tag">{KIND_LABEL[s.kind]}</span>
      {Boolean(s.needsGameOption) && <> <span className="muted" title="Importable here only because the custom-game option “all products available from importers” is on">game option</span></>}
    </> },
    { key: "neighborhood", label: "Neighborhood", render: (s) => s.neighborhood ?? "—" },
    { key: "contractAmount", label: "Your contract", num: true, title: "Units per delivery in your current import contract",
      render: (s) => (s.contractAmount != null ? `${s.contractAmount.toLocaleString("en-US")} / delivery` : "") },
    { key: "purchasePriceEstimate", label: "Purchase", num: true, title: "Wholesale price × import index × difficulty × shortage (same formula for all suppliers; delivery fees and purchasing agents not included). Factory: ingredient cost per unit, without wages, rent or machines",
      render: (s) => usd(s.purchasePriceEstimate) },
    { key: "maxOrder", label: "Max order", num: true, render: (s) => s.maxOrder?.toLocaleString("en-US") ?? "—" },
  ];
  return (
    <div className="card">
      <h2>Where to buy</h2>
      <p className="hint">Importers (piers) from the game data, wholesalers from what they stock in your save, and factory recipes for what can only be manufactured (expensive clothing, electronics…). Search a product or a supplier.</p>
      <div className="controls">
        <label>Search <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="e.g. Whisky" /></label>
        <div className="segmented" role="group" aria-label="Supplier type">
          {[["all", "All"], ["importer", "Importers"], ["wholesaler", "Wholesalers"], ["factory", "Factory recipes"]].map(([k, l]) => (
            <button key={k} className={k === kind ? "on" : ""} onClick={() => setKind(k)}>{l}</button>
          ))}
        </div>
        <label className="toggle"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> My import contracts</label>
        <span className="muted">{isLoading ? "Loading…" : `${rows.length} offer(s)`}</span>
      </div>
      <SortableTable rows={rows} columns={columns} rowKey={(s) => `${s.kind}|${s.address ?? ""}|${s.item}`} initialSort="itemLabel" initialDesc={false} maxHeight={640} />
    </div>
  );
}

function Activity() {
  const [days, setDays] = useState(30);
  const [relevance, setRelevance] = useState("near");
  const { data, isLoading } = useQuery({ queryKey: ["activity", days], queryFn: () => api.activity(days) });
  if (isLoading || !data) return <div className="card empty">Loading…</div>;
  const events = data.events.filter((e) => relevance === "all" || (relevance === "near" ? e.relevance !== "city" : e.relevance === "direct"));
  const eventColumns: Column<MarketEvent>[] = [
    { key: "startDay", label: "Day", num: true },
    { key: "kind", label: "Event", render: (e) => <span className="tag">{EVENT_LABEL[e.kind] ?? e.kind}</span> },
    { key: "what", label: "What", value: (e) => e.businessName ?? e.itemLabel,
      render: (e) => (e.businessName ? <>{e.businessName} <span className="muted">{e.businessTypeLabel}</span></> : e.itemLabel ?? "—") },
    { key: "rivalName", label: "Rival", render: (e) => e.rivalName ?? "" },
    { key: "neighborhood", label: "Where", render: (e) => <>{e.neighborhood ?? "whole city"}{e.address ? <span className="muted"> · {e.address}</span> : null}</> },
    { key: "demandImpact", label: "Demand", num: true, render: (e) => (e.demandImpact ? `${e.demandImpact > 0 ? "+" : ""}${e.demandImpact}` : "") },
    { key: "endDay", label: "Until", num: true, render: (e) => (e.endDay ? `day ${e.endDay}${e.active ? " · active" : ""}` : "") },
    { key: "relevance", label: "For you", render: (e) => (e.relevance === "direct" ? <span className="tag">direct</span> : e.relevance === "neighborhood" ? <span className="muted">your area</span> : "") },
  ];
  const rivalColumns: Column<Rival>[] = [
    { key: "name", label: "Rival", render: (r) => <>{r.name}{r.special ? <> <span className="tag">special{r.specialActive ? " · active" : ""}</span></> : null}</> },
    { key: "businessesInCity", label: "Businesses", num: true },
    { key: "inYourNeighborhoods", label: "In your areas", num: true },
    { key: "lastWeeklyIncome", label: "Weekly income", num: true, render: (r) => money(r.lastWeeklyIncome) },
    { key: "role", label: "Also", value: (r) => `${r.isImporter ? "importer " : ""}${r.isWholesaler ? "wholesaler" : ""}`,
      render: (r) => `${r.isImporter ? "importer " : ""}${r.isWholesaler ? "wholesaler" : ""}` },
  ];
  return (
    <>
      {data.monopolyChanges.length > 0 && (
        <div className="card">
          <h2>Monopoly changes since the previous import day</h2>
          <ul>{data.monopolyChanges.map((m, i) => <li key={i}><b>{m.change}</b>: {m.itemLabel} in {m.neighborhood} (day {m.fromDay} → {m.toDay})</li>)}</ul>
        </div>
      )}
      <div className="section">
        <div className="card">
          <h2>Market events</h2>
          <p className="hint">Businesses opened and closed by rivals, hypes, shortages — last {days} days</p>
          <div className="controls">
            <label>Period
              <select value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 60].map((d) => <option key={d} value={d}>{d} days</option>)}</select>
            </label>
            <div className="segmented" role="group" aria-label="Relevance">
              {[["direct", "Affects me"], ["near", "My areas"], ["all", "Whole city"]].map(([k, l]) => (
                <button key={k} className={k === relevance ? "on" : ""} onClick={() => setRelevance(k)}>{l}</button>
              ))}
            </div>
          </div>
          <SortableTable rows={events} columns={eventColumns} rowKey={(e) => `${e.kind}|${e.startDay}|${e.address ?? e.item}|${e.neighborhood}`} initialSort="startDay" maxHeight={520} />
        </div>
        <div className="card section">
          <h2>Rivals</h2>
          <p className="hint">Names come from the game's special rivals and from the businesses they opened</p>
          <SortableTable rows={data.rivals} columns={rivalColumns} rowKey={(r) => r.rivalId} initialSort="inYourNeighborhoods" />
        </div>
      </div>
    </>
  );
}

export function Market() {
  const [tab, setTab] = useState("opportunities");
  return (
    <div className="page">
      <h1>Market</h1>
      <p className="subtitle">Market Insider, improved: where to open, what each neighborhood wants, and what your rivals are doing.</p>
      <div className="controls">
        <div className="segmented" role="tablist">
          {[["opportunities", "Opportunities"], ["products", "Products by neighborhood"], ["suppliers", "Where to buy"], ["activity", "Rival activity"]].map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
      </div>
      {tab === "opportunities" && <Opportunities />}
      {tab === "products" && <Products />}
      {tab === "suppliers" && <Suppliers />}
      {tab === "activity" && <Activity />}
    </div>
  );
}
