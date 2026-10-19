import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export type Source = {
  save: string; name: string; path: string; importedAt: string;
  day: number; time: string; money: number; businesses: number; employees: number;
};

export type Status = {
  source: Source | null;
  saveRoot: string;
  watching: boolean;
  busy: boolean;
  pending: string | null;
  lastImport: { save: string; day: number; time: string; seconds: number; at: string } | null;
  lastError: { save: string; error: string; at: string } | null;
  jobs: Record<string, string>;
  hasReference: boolean;
  reference: { available: boolean; stale: boolean | null; version: { extractedAt?: string } | null };
  checks: { checkedAt: string; byStatus: Record<string, number> } | null;
  history: { table: string; firstDay: number; lastDay: number; rows: number }[];
};

export type Window = { days: number; firstDay: number; lastDay: number };

/** P&L d'un commerce sur une période (pnl.by_business), enrichi pour les listes. */
export type BusinessRow = {
  address: string; name: string | null; typeLabel: string | null; segment: string; status: "active" | "closed";
  costCenter: boolean; neighborhood?: string | null; employees?: number | null; satisfaction?: number | null;
  creationDay?: number | null; isNew?: boolean;
  revenue: number; cogs: number; grossMargin: number; salaries: number; rent: number; marketing: number;
  licensingFees: number; theft: number; otherCosts: number; operatingProfit: number;
  margin: number | null; grossMarginRate: number | null; payrollRatio: number | null; revenueShare: number | null;
  allocatedOverhead: number | null; allocatedDetail: Record<string, number> | null; profitAfterOverhead: number | null;
  profitPerDay: number; previousOperatingProfit?: number | null;
  insights?: Partial<Record<Severity, number>>;
};

export type Severity = "high" | "medium" | "low" | "info" | "positive";

export type Insight = {
  severity: Severity; category: string; address: string; business: string;
  title: string; detail: string; action: string | null; impactPerDay: number | null;
  evidence: Record<string, unknown>;
};

export type Dashboard = {
  empty?: boolean;
  source: Source | null;
  window: Window;
  kpis: {
    money: number; investments: number | null; netLiquid: number; profitWindow: number;
    profitPreviousWindow: number; operatingProfit: number; overhead: number; lastDayProfit: number | null;
    businesses: number; costCenters: number; employees: number;
  };
  dailyProfit: { day: number; totalProfit: number; totalBusinessProfit: number }[];
  businesses: BusinessRow[];
  costCenters: BusinessRow[];
  insights: Insight[];
  insightCounts: Record<Severity, number>;
};

export type PnlLine = { key: string; label: string; kind: "line" | "subtotal" | "total"; values: number[]; total: number };
export type Pnl = {
  empty?: boolean;
  granularity: "day" | "week" | "year"; scope: string; allocated: boolean;
  periods: { key: number; label: string; firstDay: number; lastDay: number; daysCovered: number; complete: boolean }[];
  lines: PnlLine[];
  reconciliationGap: number | null; dataFrom: number; dataTo: number;
};

export type Product = {
  item: string; label: string; units: number; unitsPerDay: number; revenue: number; cogs?: number; margin?: number;
  marginRate?: number | null; avgPrice?: number | null; price?: number | null; ceiling?: number | null;
  headroom?: number | null; optimal?: number | null; monopoly?: number | boolean | null;
  lowestCompetitor?: string | null; lowestCompetitorPrice?: number | null; refusalRate?: number | null;
  pricingManager?: number | boolean | null; stock?: number | null; daysOfCover?: number | null;
};

export type Employee = {
  id: string; name: string; hourlyWage: number; weeklyHours: number; weeklyDays: number; satisfaction: number;
  dayHired: number; isAbsent: boolean; isComplaining: boolean; demands: string; skills: string;
  mainSkill: string | null; mainSkillValue: number | null; status: "active" | "poached"; beingReplaced: boolean | number | null;
};

export type BusinessDetail = {
  address: string;
  business: Record<string, any>;
  building: { sqm: number; trafficIndex: number; neighborhood: string; buildingSize: string } | null;
  window: Window;
  pnl: BusinessRow | null;
  daily: { day: number; sales: number; resources: number; salaries: number; rent: number; marketing: number; profit: number; customers: number | null }[];
  products: Product[];
  employees: Employee[];
  staffing: Staffing | null;
  staffingHours: StaffingHour[];
  marketing: Marketing | null;
  marketingOptions: MarketingOption[];
  satisfactionHistory: { day: number; satisfaction: number; satCustomerService: number; satPricing: number; satCleanliness: number; satFacility: number }[];
  suppliers: { sourceAddress: string; sourceBusiness: string | null; item: string; targetAmount: number }[];
  serves: { destinationAddress: string; destinationBusiness: string | null; item: string; targetAmount: number }[];
  insights: Insight[];
};

export type Marketing = {
  address: string; business: string; sqm: number; trafficIndex: number; marketingStrength: number;
  valuePerCustomer: number | null; observedCustomersPerDay: number; calibration: number;
  currentCampaigns: string; currentCost: number; currentPromotion: number; currentCustomersPerDay: number;
  bestCampaigns: string; bestCost: number; bestPromotion: number; bestCustomersPerDay: number; gainPerDay: number | null;
  samePromotionCampaigns: string | null; samePromotionCost: number | null; saturationPromotion: number | null;
};
export type MarketingOption = {
  campaigns: string; cost: number; marketingPoints: number; promotion: number; customersPerDay: number;
  profitPerDay: number | null; current: number | boolean; best: number | boolean;
};
export type Staffing = {
  stationKind: string; customersPerStationHour: number; avgCustomersPerDay: number;
  staffedStationHoursPerWeek: number; neededStationHoursPerWeek: number; idleStationHoursPerWeek: number;
  idleShare: number | null; idleWagesPerWeek: number; peakStaffed: number; peakNeeded: number; understaffedHours: number;
};
export type StaffingHour = {
  day: number; hour: number; expectedCustomers: number; staffedStations: number; neededStations: number;
  idleStations: number; idleWages: number; short: number | boolean;
};
export type CustomerPoint = { day: number; customers: number; revenue: number; revenuePerCustomer: number | null };
export type CustomersData = {
  empty?: boolean; firstDay: number; lastDay: number;
  businesses: { address: string; name: string; typeLabel: string; segment: string; customerCapacity: number;
                series: CustomerPoint[]; avg7: number | null; avgPrev7: number | null }[];
  total: { day: number; customers: number }[];
};

export type PriceRow = {
  address: string; business: string; neighborhood: string; item: string; itemLabel: string;
  price: number; ceiling: number; headroom: number; optimal: number; defaultPrice: number;
  lowestCompetitorPrice: number | null; lowestCompetitor: string | null; monopoly: number | boolean;
  pricingManager: number | boolean; unitCost: number | null; unitMargin: number | null;
  refusalRate: number | null; ordersSampled: number; unitsPerDay: number; revenuePerDay: number;
  avgSoldPrice: number | null; gainPerDay: number; competitors: number; rivalSellers: number | null;
  demand: number | null; providers: number | null; optimalProviders: number | null; activeEvents: string | null;
  cappedByCompetitor: boolean;
};
export type PricesOverview = {
  prices: PriceRow[];
  summary: { products: number; atCeiling: number; belowCeiling: number; aboveCeiling: number; monopolies: number; cappedByCompetitor: number; gainPerDay: number };
};
export type PriceHistory = {
  address: string; item: string; label: string | null; neighborhood: string | null;
  series: { day: number; units?: number; revenue?: number; soldPrice?: number; price?: number; ceiling?: number;
            optimal?: number; lowestCompetitorPrice?: number | null; monopoly?: number; minCompetitor?: number; competitors?: number }[];
};
export type MarketRow = {
  item: string; itemLabel: string; neighborhood: string; demand: number; providers: number; optimalProviders: number;
  roomForProviders: number; rivalSellers: number; monopolyPossible: number | boolean; monopoly: number | boolean;
  playerSells: number | boolean; playerPrice: number | null; defaultPrice: number; optimal: number; ceiling: number;
  lowestCompetitorPrice: number | null; lowestCompetitor: string | null; avgCompetitorPrice: number | null;
  purchasePriceEstimate: number | null; unitMarginAtOptimal: number | null; importPriceIndex: number;
  activeEvents: string | null; eventDemandImpact: number | null; purchaseMultiplier: number;
  suppliers?: string | null;
};
export type Opportunity = {
  score: number; components: { demand: number; room: number; monopoly: number; location: number; margin: number };
  demandAfter: number; cannibalizedPerDay: number; cannibalizationShare: number; affectedBusinesses: string | null;
  pros: string[]; cons: string[]; saturation: number; avgPrice: number;
  businessType: string; label: string; segment: string; neighborhood: string; neighborhoodLabel: string;
  products: number; productsWithDemand: number; avgDemand: number; maxDemand: number; roomForProviders: number;
  rivalSellers: number; monopolyPossibleProducts: number; avgUnitMargin: number | null; sameTypeCompetitors: number;
  playerBusinesses: string | null; freeBuildings: number; cheapestRent: number | null; bestTraffic: number | null;
  bestSpaces: { address: string; rent: number | null; sqm: number; traffic: number }[]; activeEvents: string | null;
};
export type MarketEvent = {
  kind: string; item: string | null; itemLabel: string | null; neighborhood: string | null; startDay: number;
  endDay: number | null; active: number | boolean; demandImpact: number | null; businessType: string | null;
  businessTypeLabel: string | null; businessName: string | null; rivalName: string | null; address: string | null;
  relevance: "direct" | "neighborhood" | "city";
};
export type Rival = {
  rivalId: string; name: string; lastWeeklyIncome: number | null; businesses: number | null; businessesInCity: number;
  inYourNeighborhoods?: number; special: number | boolean; specialActive: number | boolean | null; isImporter: number | boolean; isWholesaler: number | boolean;
};
export type Activity = {
  today: number; days: number; events: MarketEvent[];
  monopolyChanges: { itemLabel: string; neighborhood: string; change: "gained" | "lost"; fromDay: number; toDay: number; playerSells: number }[];
  rivals: Rival[];
};

export type CandidateFit = {
  candidateId: string; business: string; address: string; demandsMet: number; demandsTotal: number;
  cap: number | null; arrangeable: number; missing: string | null; effectiveSkill: number; wagePerEffectivePoint: number;
};
export type Candidate = {
  id: string; name: string; gender: number; ageInDays: number; hourlyWage: number; demands: string; skills: string;
  mainSkill: string; mainSkillValue: number; sourceBusiness: string | null; fromJobBoard: number | boolean;
  hoursUntilExpiring: number | null; fits: number; bestBusiness: string | null; bestAddress: string | null;
  bestCap: number | null; effectiveSkill: number | null; wagePerEffectivePoint: number | null; missingAtBest: string | null;
  fitsDetail: CandidateFit[];
};
export type StaffMember = Employee & {
  business: string | null; address: string | null; segment: string | null; marketWage: number | null; wageRatio: number | null;
  demandsMet: number | null; demandsTotal: number | null; satisfactionCap: number | null; unmetDemands: string | null;
};
export type Recruitment = {
  empty?: boolean;
  summary: { candidates: number; expiringWithin24h: number; employees: number; cappedEmployees: number; overpaid: number; underpaid: number };
  openings: { kind: string; business: string | null; address: string | null; skill: string | null; detail: string }[];
  fixes: { address: string; business: string; demand: string; fix: string; employees: { name: string; satisfaction: number; cap: number }[] }[];
  employees: StaffMember[];
  candidates: Candidate[];
};

export type Recommendation = {
  key: string; category: string; address: string | null; business: string | null; title: string; steps: string[];
  why: string; gainPerDay: number | null; confidence: "high" | "medium" | "low"; effort: "low" | "medium" | "high";
  evidence: Record<string, unknown>; dismissed: boolean; rank: number;
};
export type Recommendations = {
  empty?: boolean; window: number;
  summary: { count: number; dismissed: number; gainHigh: number; gainMedium: number; gainLow: number };
  items: Recommendation[];
};
export type Supplier = {
  kind: "importer" | "wholesaler" | "factory"; supplier: string; address: string | null; neighborhood: string | null;
  item: string; itemLabel: string; available: number | boolean; needsGameOption: number | boolean;
  ingredients: string | null; contractAmount: number | null;
  purchasePriceEstimate: number | null; maxOrder: number | null;
};

export type SegGap = { key: string; label: string; value: number; peerValue: number; gapSd: number; gainPerDay: number | null; action: string };
export type SegBusiness = {
  address: string; name: string; typeLabel: string; segment: string; model: string; modelLabel: string; group: number;
  supplementary: boolean; creationDay: number | null; silhouette: number | null; performance: number; peers: string[];
  coords: number[]; values: Record<string, number | null>; gaps: SegGap[];
};
export type SegGroup = {
  id: number; name: string; best: boolean; size: number; performance: number; silhouette: number | null; profitPerDay: number;
  means: Record<string, number | null>;
  distinctive: { key: string; label: string; valueTest: number; groupValue: number | null; overallValue: number | null }[];
};
export type SegAxis = {
  index: number; variance: number; kept: boolean; name: string; plus: string[]; minus: string[];
  loadings: { key: string; label: string; correlation: number; contribution: number | null; supplementary: boolean }[];
};
export type Segmentation = {
  empty?: boolean; reason?: string;
  firstDay: number; lastDay: number; snapshotDay: number; window: number; sampleSize: number; groupsCount: number;
  varianceKept: number; axesKept: number; silhouette: number | null;
  kChoices: { k: number; silhouette: number; smallestGroup: number; mergeHeight: number }[];
  variables: { key: string; label: string; family: string; direction: number; actionable: boolean; used: boolean; supplementary: boolean }[];
  dropped: string[]; axes: SegAxis[]; groups: SegGroup[]; businesses: SegBusiness[];
  history: { day: number; approximate: boolean; groups: Record<string, number> }[];
};

export type ServerEvent = { type: string; at?: string; [key: string]: unknown };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  status: () => request<Status>("/api/status"),
  dashboard: (window = 7) => request<Dashboard>(`/api/dashboard?window=${window}`),
  pnl: (granularity: string, periods: number, scope: string, allocate: boolean) =>
    request<Pnl>(`/api/pnl?granularity=${granularity}&periods=${periods}&scope=${encodeURIComponent(scope)}&allocate=${allocate}`),
  pnlBusinesses: (firstDay: number, lastDay: number) =>
    request<{ firstDay: number; lastDay: number; businesses: BusinessRow[] }>(`/api/pnl/businesses?firstDay=${firstDay}&lastDay=${lastDay}`),
  businesses: (window = 7) => request<{ empty?: boolean; window: Window; businesses: BusinessRow[] }>(`/api/businesses?window=${window}`),
  business: (address: string, window = 7) =>
    request<BusinessDetail>(`/api/businesses/${encodeURIComponent(address)}?window=${window}`),
  recruitment: () => request<Recruitment>("/api/recruitment"),
  recommendations: (window = 7) => request<Recommendations>(`/api/recommendations?window=${window}`),
  dismiss: (key: string, dismissed: boolean) =>
    request("/api/recommendations/dismiss", { method: "POST", body: JSON.stringify({ key, dismissed }) }),
  suppliers: (item?: string) => request<Supplier[]>(`/api/suppliers${item ? `?item=${item}` : ""}`),
  segmentation: (window = 14) => request<Segmentation>(`/api/segmentation?window=${window}`),
  customers: (days = 60) => request<CustomersData>(`/api/customers?days=${days}`),
  prices: (window = 7) => request<PricesOverview>(`/api/prices?window=${window}`),
  priceHistory: (address: string, item: string) =>
    request<PriceHistory>(`/api/prices/history?address=${encodeURIComponent(address)}&item=${encodeURIComponent(item)}`),
  market: (neighborhood?: string) => request<MarketRow[]>(`/api/market${neighborhood ? `?neighborhood=${neighborhood}` : ""}`),
  opportunities: () => request<Opportunity[]>("/api/market/opportunities"),
  activity: (days = 30) => request<Activity>(`/api/market/activity?days=${days}`),
  sync: (force = false) => request("/api/sync", { method: "POST", body: JSON.stringify({ force }) }),
  refreshGamedata: () => request("/api/gamedata/refresh", { method: "POST" }),
  checkBiggerAmbitions: (refresh = false) =>
    request("/api/checks/biggerambitions", { method: "POST", body: JSON.stringify({ refresh }) }),
  setWatch: (enabled: boolean) => request("/api/watch", { method: "POST", body: JSON.stringify({ enabled }) }),
};

/** Écoute /api/events : rafraîchit les données après chaque import et renvoie le dernier événement. */
export function useServerEvents(): ServerEvent | null {
  const queryClient = useQueryClient();
  const [last, setLast] = useState<ServerEvent | null>(null);

  useEffect(() => {
    const source = new EventSource("/api/events");
    const handle = (message: MessageEvent) => {
      const event = JSON.parse(message.data) as ServerEvent;
      setLast(event);
      queryClient.invalidateQueries({ queryKey: ["status"] });
      if (event.type === "import_done" || event.type === "job_done") {
        queryClient.invalidateQueries();
      }
    };
    const kinds = ["import_started", "import_done", "import_retry", "import_failed", "change_detected",
      "watch_changed", "job_started", "job_done", "job_failed"];
    kinds.forEach((kind) => source.addEventListener(kind, handle));
    return () => source.close();
  }, [queryClient]);

  return last;
}
