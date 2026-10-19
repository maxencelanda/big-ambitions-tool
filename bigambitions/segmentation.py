"""Segmentation statistique des centres de profit : ACP puis classification ascendante hiérarchique de Ward.

Chaque commerce ouvert depuis au moins ``window`` jours est décrit par ~20 variables calculées sur la fenêtre.
Les *leviers* (structure de coûts, activité, qualité, prix, emplacement) sont les variables actives ; les
*résultats* (marge, profit par jour / employé / m², CA, tendance) sont supplémentaires : ils ne forment pas les
groupes, ils servent à dire lesquels réussissent. Après centrage-réduction par modèle économique :

1. ACP sur les leviers : on garde les axes qui expliquent 80 % de la variance (au moins 2) ;
2. Ward sur ces axes ; le nombre de groupes maximise la silhouette (2 à 5 groupes) ;
3. chaque groupe est nommé d'après ses valeurs-tests et classé par sa rentabilité moyenne ;
4. chaque commerce est comparé à la meilleure moitié de ses pairs (même modèle, plus rentables que lui) : ses
   plus gros écarts sur les leviers pilotables deviennent des actions, chiffrées quand c'est possible.

Les commerces plus récents sont projetés sur les axes (individus supplémentaires) et rattachés au groupe le plus
proche, sans peser sur le modèle. L'historique projette les fenêtres passées sur le modèle d'aujourd'hui, ce qui
rend les groupes comparables d'une semaine à l'autre.
"""
from __future__ import annotations

import math
import sqlite3
from typing import Any

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.stats import theilslopes
from sklearn.metrics import silhouette_samples, silhouette_score

from . import pnl

VARIANCE_TARGET = 0.80
MAX_GROUPS = 5
MIN_GROUP_SIZE = 2
GAP_THRESHOLD = 0.5   # écart minimal, en écarts-types, pour proposer une action
HISTORY_STEPS = 6     # fenêtres passées projetées, une par semaine
SERVICE_STATIONS = {"hairdresserchair"}  # poste de service : le client est servi, pas encaissé
MODEL_LABEL = {"office": "office businesses", "shop": "shops", "service": "service shops"}


def _money(x: float) -> float:
    """Échelle compressée pour les montants (gère les pertes) : asinh(x / 1000)."""
    return math.asinh(x / 1000)


# key, libellé, famille, sens (+1 : plus c'est haut, mieux c'est ; 0 : descriptif), pilotable, transformation
VARIABLES: list[tuple[str, str, str, int, bool, Any]] = [
    ("margin", "Operating margin", "profitability", 1, False, None),
    ("profitPerDay", "Profit / day", "profitability", 1, False, _money),
    ("profitPerEmployee", "Profit / employee / day", "profitability", 1, False, _money),
    ("profitPerSqm", "Profit / m² / day", "profitability", 1, False, None),
    ("cogsRatio", "Purchases / revenue", "costs", -1, False, None),  # mix de produits (prix déjà au plafond)
    ("payrollRatio", "Wages / revenue", "costs", -1, True, None),
    ("rentRatio", "Rent / revenue", "costs", -1, False, None),
    ("marketingRatio", "Marketing / revenue", "costs", -1, True, None),
    ("revenuePerDay", "Revenue / day", "activity", 1, False, _money),
    ("customersPerDay", "Customers / day", "activity", 1, False, lambda x: math.log1p(max(x, 0))),
    ("revenuePerCustomer", "Revenue / customer", "activity", 1, False, lambda x: math.log1p(max(x, 0))),
    ("idleShare", "Idle station-hours", "activity", -1, True, None),
    ("satCustomerService", "Customer service", "quality", 1, True, None),
    ("satPricing", "Price satisfaction", "quality", 0, False, None),
    ("satCleanliness", "Cleanliness", "quality", 1, True, None),
    ("satFacility", "Facility", "quality", 1, True, None),
    ("priceVsCeiling", "Price / ceiling", "price", 1, True, None),
    ("monopolyShare", "Products in monopoly", "price", 1, False, None),
    ("refusalRate", "Refused on price", "price", -1, True, None),
    ("trend", "Profit trend", "dynamics", 1, False, None),
    ("trafficIndex", "Building traffic", "location", 1, False, None),
]
VAR = {v[0]: v for v in VARIABLES}
PROFITABILITY = [v[0] for v in VARIABLES if v[2] == "profitability"]
# Résultats : projetés sur les axes sans les former.
SUPPLEMENTARY = set(PROFITABILITY) | {"revenuePerDay", "trend"}

# {v} : valeur du commerce, {b} : médiane de ses pairs de référence.
ACTIONS = {
    "payrollRatio": "Wages are {v} of revenue vs {b} for your better peers: trim idle shifts or headcount (see Recommendations).",
    "marketingRatio": "Marketing is {v} of revenue vs {b}: try a cheaper campaign and watch customers.",
    "idleShare": "{v} of station-hours are idle vs {b}: cut the hours with no customers.",
    "satCustomerService": "Customer service {v} vs {b}: meet employee demands (satisfaction) or train skills.",
    "satCleanliness": "Cleanliness {v} vs {b}: add cleaning hours or a cleaner.",
    "satFacility": "Facility {v} vs {b}: better furniture, decor or a bigger space.",
    "priceVsCeiling": "Prices at {v} of the ceiling vs {b}: raise them (Prices page).",
    "refusalRate": "{v} of customers refuse the price vs {b}: lower slightly the most refused products.",
}
PERCENT = {"margin", "cogsRatio", "payrollRatio", "rentRatio", "marketingRatio", "idleShare", "priceVsCeiling",
           "monopolyShare", "refusalRate", "trend"}


def _all(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cur = db.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _snapshot_day(db: sqlite3.Connection, table: str, day: int) -> int | None:
    """Dernier instantané au plus tard ``day``, sinon le plus ancien (les instantanés commencent plus tard que le P&L)."""
    found = db.execute(f"SELECT max(day) FROM {table} WHERE day <= ?", (day,)).fetchone()[0]
    return found if found is not None else db.execute(f"SELECT min(day) FROM {table}").fetchone()[0]


def features(db: sqlite3.Connection, last_day: int, window: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Une ligne de variables brutes par centre de profit actif à ``last_day``."""
    first = last_day - window + 1
    snap = _snapshot_day(db, "hist_businesses", last_day)
    businesses = _all(db, "SELECT * FROM hist_businesses WHERE day = ? AND segment IN ('retail', 'office')", (snap,))
    finances = {r["address"]: r for r in pnl.by_business(db, first, last_day, allocate_overhead=False)}
    daily = {}
    for r in _all(db, "SELECT address, day, profit FROM hist_daily_finances WHERE day BETWEEN ? AND ?", (first, last_day)):
        daily.setdefault(r["address"], []).append((r["day"], r["profit"]))
    customers = {r["address"]: r["avg"] for r in _all(db, """
        SELECT address, avg(c) AS avg FROM (SELECT address, day, max(customers) AS c FROM hist_sales
        WHERE day BETWEEN ? AND ? GROUP BY address, day) GROUP BY address""", (first, last_day))}
    price_snap = _snapshot_day(db, "hist_prices", last_day) if "hist_prices" in _tables(db) else None
    prices = {r["address"]: r for r in _all(db, """
        SELECT address, avg(priceVsCeiling) AS priceVsCeiling, avg(monopoly) AS monopolyShare, avg(refusalRate) AS refusalRate
        FROM hist_prices WHERE day = ? GROUP BY address""", (price_snap,))} if price_snap is not None else {}
    # Les effectifs heure par heure n'existent que pour la sauvegarde courante.
    staffing = {r["address"]: r for r in _all(db, "SELECT * FROM staffing")} if "staffing" in _tables(db) else {}

    rows = []
    for b in businesses:
        f = finances.get(b["address"])
        if not f or f["status"] != "active" or (b["creationDay"] or 0) > last_day:
            continue
        revenue = f["revenue"] / window
        profit = f["operatingProfit"] / window
        points = sorted(daily.get(b["address"], []))
        trend = None
        if len(points) >= 5 and revenue:
            slope = theilslopes([p for _, p in points], [d for d, _ in points])[0]  # $ de profit gagnés par jour
            trend = slope * window / revenue  # variation du profit sur la fenêtre, en part du CA journalier
        cust = customers.get(b["address"])
        st = staffing.get(b["address"]) or {}
        pr = prices.get(b["address"]) or {}
        ratio = lambda line: -f[line] / f["revenue"] if f["revenue"] else None  # noqa: E731 - charges négatives
        rows.append({
            "address": b["address"], "name": b["name"], "typeLabel": b["typeLabel"], "segment": b["segment"],
            # Modèle économique, base des comparaisons : bureaux, boutiques, services en boutique (coiffeurs).
            "model": "office" if b["segment"] == "office" else ("service" if st.get("stationKind") in SERVICE_STATIONS else "shop"),
            "creationDay": b["creationDay"], "tooNew": b["creationDay"] is not None and b["creationDay"] > first,
            "revenueRaw": revenue, "idleWagesPerDay": (st.get("idleWagesPerWeek") or 0) / 7,
            "margin": profit / revenue if revenue else None,
            "profitPerDay": profit,
            "profitPerEmployee": profit / b["employees"] if b["employees"] else None,
            "profitPerSqm": profit / b["sqm"] if b["sqm"] else None,
            "cogsRatio": ratio("cogs"), "payrollRatio": ratio("salaries"), "rentRatio": ratio("rent"),
            "marketingRatio": ratio("marketing"),
            "revenuePerDay": revenue, "customersPerDay": cust,
            "revenuePerCustomer": revenue / cust if cust else None,
            "idleShare": st.get("idleShare"),
            "satCustomerService": b["satCustomerService"], "satPricing": b["satPricing"],
            "satCleanliness": b["satCleanliness"], "satFacility": b["satFacility"],
            "priceVsCeiling": pr.get("priceVsCeiling"), "monopolyShare": pr.get("monopolyShare"),
            "refusalRate": pr.get("refusalRate"),
            "trend": trend, "trafficIndex": b["trafficIndex"],
        })
    meta = {"firstDay": first, "lastDay": last_day, "snapshotDay": snap, "priceSnapshotDay": price_snap}
    return rows, meta


def _matrix(rows: list[dict[str, Any]], keys: list[str]) -> np.ndarray:
    out = np.full((len(rows), len(keys)), np.nan)
    for i, r in enumerate(rows):
        for j, k in enumerate(keys):
            v = r.get(k)
            if v is not None:
                t = VAR[k][5]
                out[i, j] = t(v) if t else v
    return out


class Model:
    """Standardisation intra-segment, ACP et centres des groupes appris sur l'échantillon ; sert aussi à projeter.

    Chaque variable est centrée sur la moyenne de son modèle économique (bureau / boutique / service) puis réduite
    par l'écart-type intra-modèle commun : un cabinet d'avocats est comparé aux autres bureaux, pas à un supermarché.
    Sans cela, l'ACP ne retrouve que le modèle économique (achats d'un côté, salaires de l'autre).
    """

    def __init__(self, x: np.ndarray, keys: list[str], segments: list[str]):
        segs = np.array(segments)
        self.segments = sorted(set(segments))
        overall = np.nanmedian(x, axis=0)
        self.medians, self.means = {}, {}
        x = x.copy()
        for seg in self.segments:
            rows = segs == seg
            med = np.nanmedian(np.where(np.isnan(x[rows]).all(axis=0), overall, x[rows]), axis=0)
            med = np.where(np.isnan(med), overall, med)
            x[rows] = np.where(np.isnan(x[rows]), med, x[rows])
            self.medians[seg], self.means[seg] = med, x[rows].mean(axis=0)
        centered = x - np.array([self.means[seg] for seg in segments])
        stds = centered.std(axis=0)
        keep = stds > 1e-9  # une variable constante n'apporte rien (ex. tous les prix au plafond)
        self.keys = [k for k, ok in zip(keys, keep) if ok]
        self.dropped = [k for k, ok in zip(keys, keep) if not ok]
        self.medians = {seg: v[keep] for seg, v in self.medians.items()}
        self.means = {seg: v[keep] for seg, v in self.means.items()}
        self.global_mean = x[:, keep].mean(axis=0)
        self.global_median = overall[keep]
        self.stds = stds[keep]
        self.z = centered[:, keep] / self.stds
        self.active = np.array([k not in SUPPLEMENTARY for k in self.keys])
        self.active_keys = [k for k in self.keys if k not in SUPPLEMENTARY]
        self.rows: list[dict[str, Any]] = []
        _, s, vt = np.linalg.svd(self.z[:, self.active], full_matrices=False)
        self.eigen = s ** 2 / len(self.z)
        self.ratio = self.eigen / self.eigen.sum()
        self.axes = vt
        cumulative = np.cumsum(self.ratio)
        self.kept = max(2, int(np.searchsorted(cumulative, VARIANCE_TARGET) + 1))
        self.kept = min(self.kept, len(self.ratio))
        self.scores = self.project(self.z)

    def standardize(self, x: np.ndarray, keys: list[str], segments: list[str]) -> np.ndarray:
        idx = [keys.index(k) for k in self.keys]
        x = x[:, idx]
        med = np.array([self.medians.get(seg, self.global_median) for seg in segments])
        mean = np.array([self.means.get(seg, self.global_mean) for seg in segments])
        return (np.where(np.isnan(x), med, x) - mean) / self.stds

    def project(self, z: np.ndarray) -> np.ndarray:
        return z[:, self.active] @ self.axes[: self.kept].T

    def correlations(self) -> np.ndarray:
        """Corrélation de chaque variable (active ou supplémentaire) avec chaque axe."""
        all_scores = self.z[:, self.active] @ self.axes.T
        sd = all_scores.std(axis=0)
        return np.array([[float(np.mean(self.z[:, j] * all_scores[:, a]) / sd[a]) if sd[a] > 1e-9 else 0.0
                          for j in range(len(self.keys))] for a in range(len(self.ratio))])


def _value_tests(z: np.ndarray, labels: np.ndarray, group: int) -> np.ndarray:
    """Valeur-test de chaque variable pour un groupe : écart de sa moyenne à 0, en écarts-types de l'échantillonnage."""
    n, ng = len(z), int((labels == group).sum())
    if ng == n:
        return np.zeros(z.shape[1])
    return z[labels == group].mean(axis=0) / math.sqrt((n - ng) / (n - 1) / ng)


def _fmt(key: str, value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if key in PERCENT:
        return f"{value * 100:.0f} %"
    if key in ("profitPerDay", "revenuePerDay", "profitPerEmployee", "revenuePerCustomer", "profitPerSqm"):
        return f"${value:,.0f}" if abs(value) >= 10 else f"${value:,.2f}"
    return f"{value:,.1f}" if abs(value) < 100 else f"{value:,.0f}"


def _axis_name(model: Model, loadings: np.ndarray) -> dict[str, Any]:
    """Pôles d'un axe : les variables les plus corrélées de chaque côté."""
    loadings = np.where([k in SUPPLEMENTARY for k in model.keys], 0.0, loadings)  # seuls les leviers nomment un axe
    order = np.argsort(loadings)
    plus = [model.keys[i] for i in order[::-1][:3] if loadings[i] > 0.5]
    minus = [model.keys[i] for i in order[:3] if loadings[i] < -0.5]
    short = lambda ks: ", ".join(VAR[k][1].lower() for k in ks)  # noqa: E731
    return {"plus": plus, "minus": minus,
            "name": " ↔ ".join(x for x in (short(plus), short(minus)) if x) or "no dominant variable"}


def _choose_k(scores: np.ndarray, tree: np.ndarray) -> tuple[int, list[dict[str, Any]]]:
    n = len(scores)
    candidates = []
    for k in range(2, min(MAX_GROUPS, n - 1) + 1):
        labels = fcluster(tree, k, criterion="maxclust")
        if len(set(labels)) < 2:
            continue
        smallest = int(min(np.bincount(labels)[1:]))  # fcluster numérote les groupes à partir de 1
        candidates.append({"k": k, "silhouette": round(float(silhouette_score(scores, labels)), 3),
                           "smallestGroup": smallest,
                           # saut d'inertie : hauteur de la fusion qu'on refuse en s'arrêtant à k groupes
                           "mergeHeight": round(float(tree[n - k, 2]), 3)})
    # Un groupe d'un seul commerce ne décrit pas un profil : on l'écarte tant qu'il existe une autre partition.
    usable = [c for c in candidates if c["smallestGroup"] >= MIN_GROUP_SIZE] or candidates
    best = max(usable, key=lambda c: c["silhouette"])["k"] if usable else 1
    return best, candidates


def analyse(db: sqlite3.Connection, window: int = 14) -> dict[str, Any]:
    tables = _tables(db)
    if not {"hist_daily_finances", "hist_businesses"} <= tables:
        return {"empty": True, "reason": "No history yet: sync a save first."}
    last = db.execute("SELECT max(day) FROM hist_daily_finances").fetchone()[0]
    rows, meta = features(db, last, window)
    sample = [r for r in rows if not r["tooNew"]]
    extra = [r for r in rows if r["tooNew"]]
    keys = [v[0] for v in VARIABLES]
    if len(sample) < 4:
        return {"empty": True, "reason": f"Only {len(sample)} business(es) open for {window} days: not enough to segment."}

    model = Model(_matrix(sample, keys), keys, [r["model"] for r in sample])
    model.rows = sample
    n = len(sample)
    tree = linkage(model.scores, method="ward")
    k, candidates = _choose_k(model.scores, tree)
    labels = fcluster(tree, k, criterion="maxclust") if k > 1 else np.ones(n, dtype=int)
    sil = silhouette_samples(model.scores, labels) if k > 1 else np.zeros(n)

    # Rentabilité de chaque commerce : moyenne de ses variables de rentabilité centrées-réduites.
    prof_idx = [model.keys.index(p) for p in PROFITABILITY if p in model.keys]
    performance = model.z[:, prof_idx].mean(axis=1)
    group_ids = sorted(set(labels.tolist()), key=lambda g: -performance[labels == g].mean())
    rank = {g: i for i, g in enumerate(group_ids)}  # 0 = groupe le plus rentable
    labels = np.array([rank[g] for g in labels])
    centroids = np.array([model.scores[labels == g].mean(axis=0) for g in range(k)])

    groups = []
    for g in range(k):
        members = labels == g
        tests = _value_tests(model.z, labels, g)
        order = np.argsort(-np.abs(tests))
        distinctive = [{"key": model.keys[j], "label": VAR[model.keys[j]][1], "valueTest": round(float(tests[j]), 2),
                        "groupValue": _mean_raw(sample, model.keys[j], members),
                        "overallValue": _mean_raw(sample, model.keys[j], np.ones(n, dtype=bool))}
                       for j in order[:6] if abs(tests[j]) >= 1.0]
        name = " · ".join(f"{'High' if d['valueTest'] > 0 else 'Low'} {d['label'].lower()}" for d in distinctive[:2])
        groups.append({
            "id": g, "name": name or "Average profile", "best": g == 0, "size": int(members.sum()),
            "performance": round(float(performance[members].mean()), 2),
            "silhouette": round(float(sil[members].mean()), 3) if k > 1 else None,
            "profitPerDay": round(sum(r["profitPerDay"] for r, m in zip(sample, members) if m), 2),
            "means": {key: _mean_raw(sample, key, members) for key in ("margin", "payrollRatio", "cogsRatio",
                                                                         "profitPerDay", "revenuePerDay", "satCustomerService")},
            "distinctive": distinctive,
        })

    businesses = []
    for i, r in enumerate(sample):
        businesses.append(_business(r, model, model.z[i], model.scores[i], int(labels[i]), float(sil[i]),
                                    float(performance[i]), _peers(sample, performance, r, float(performance[i])),
                                    k, supplementary=False))
    for r in extra:
        z = model.standardize(_matrix([r], keys), keys, [r["model"]])[0]
        s = model.project(z[None, :])[0]
        g = int(np.argmin(((centroids - s) ** 2).sum(axis=1)))
        perf = float(np.mean([z[j] for j in prof_idx]))
        businesses.append(_business(r, model, z, s, g, None, perf, _peers(sample, performance, r, perf),
                                    k, supplementary=True))

    correlations = model.correlations()
    axes = []
    for a in range(min(len(model.ratio), max(model.kept, 2))):
        axes.append({
            "index": a + 1, "variance": round(float(model.ratio[a]), 4), "kept": a < model.kept,
            **_axis_name(model, correlations[a]),
            "loadings": [{"key": key, "label": VAR[key][1], "correlation": round(float(correlations[a][j]), 3),
                          "supplementary": key in SUPPLEMENTARY,
                          "contribution": round(float(model.axes[a][model.active_keys.index(key)] ** 2 * 100), 1)
                                          if key not in SUPPLEMENTARY else None}
                         for j, key in enumerate(model.keys)],
        })

    return {
        **meta, "window": window, "sampleSize": n, "groupsCount": k,
        "varianceKept": round(float(model.ratio[: model.kept].sum()), 4), "axesKept": model.kept,
        "silhouette": round(float(sil.mean()), 3) if k > 1 else None, "kChoices": candidates,
        "variables": [{"key": v[0], "label": v[1], "family": v[2], "direction": v[3], "actionable": v[4],
                       "used": v[0] in model.keys, "supplementary": v[0] in SUPPLEMENTARY} for v in VARIABLES],
        "dropped": model.dropped,
        "axes": axes, "groups": groups,
        "businesses": sorted(businesses, key=lambda b: (b["group"], -b["performance"])),
        "history": _history(db, model, centroids, last, window, keys),
        "dendrogram": [[int(a), int(b), round(float(h), 3), int(c)] for a, b, h, c in tree],
        "dendrogramLabels": [r["name"] for r in sample],
    }


def _mean_raw(rows: list[dict[str, Any]], key: str, mask: np.ndarray) -> float | None:
    values = [r[key] for r, m in zip(rows, mask) if m and r.get(key) is not None]
    return round(float(np.mean(values)), 4) if values else None


def _peers(sample: list[dict[str, Any]], performance: np.ndarray, r: dict[str, Any], perf: float) -> list[int]:
    """Indices des pairs de référence : même modèle économique, meilleure moitié, plus rentables que ``r``."""
    same = [i for i, o in enumerate(sample) if o["model"] == r["model"]]
    if not same:
        return []
    median = float(np.median(performance[same]))
    return [i for i in same if sample[i]["address"] != r["address"]
            and performance[i] >= median and performance[i] > perf]


def _business(r: dict[str, Any], model: Model, z: np.ndarray, scores: np.ndarray, group: int, silhouette: float | None,
              performance: float, peers: list[int], k: int, supplementary: bool) -> dict[str, Any]:
    gaps = []
    if peers:
        peer_z = model.z[peers].mean(axis=0)
        for j, key in enumerate(model.keys):
            _, label, _, direction, actionable, _ = VAR[key]
            if not actionable or not direction or r.get(key) is None:
                continue
            values = [model.rows[i][key] for i in peers if model.rows[i].get(key) is not None]
            gap = (z[j] - peer_z[j]) * direction
            if gap > -GAP_THRESHOLD or not values:
                continue
            value, target = r[key], float(np.median(values))
            if (value - target) * direction >= 0:  # l'écart moyen vient d'un pair atypique : pas d'action
                continue
            gain = None
            if key in ("payrollRatio", "cogsRatio", "marketingRatio"):
                gain = (value - target) * r["revenueRaw"]
            elif key == "idleShare" and value:
                gain = r["idleWagesPerDay"] * (value - target) / value
            gaps.append({"key": key, "label": label, "value": round(value, 4), "peerValue": round(target, 4),
                         "gapSd": round(float(gap), 2), "gainPerDay": round(gain, 2) if gain else None,
                         "action": ACTIONS[key].format(v=_fmt(key, value), b=_fmt(key, target))})
        gaps.sort(key=lambda g: (-(g["gainPerDay"] or 0), g["gapSd"]))
    return {
        "address": r["address"], "name": r["name"], "typeLabel": r["typeLabel"], "segment": r["segment"],
        "model": r["model"], "modelLabel": MODEL_LABEL[r["model"]], "group": group, "supplementary": supplementary, "creationDay": r["creationDay"],
        "silhouette": round(silhouette, 3) if silhouette is not None and k > 1 else None,
        "performance": round(performance, 2),
        "peers": [model.rows[i]["name"] for i in peers],
        "coords": [round(float(c), 3) for c in scores],
        "values": {v[0]: (round(r[v[0]], 4) if r.get(v[0]) is not None else None) for v in VARIABLES},
        "gaps": gaps,
    }


def _history(db: sqlite3.Connection, model: Model, centroids: np.ndarray, last: int, window: int,
             keys: list[str]) -> list[dict[str, Any]]:
    """Groupe de chaque commerce aux fins de semaine passées, avec le modèle d'aujourd'hui."""
    first_finance = db.execute("SELECT min(day) FROM hist_daily_finances").fetchone()[0]
    first_snapshot = db.execute("SELECT min(day) FROM hist_businesses").fetchone()[0]
    out = []
    for step in range(HISTORY_STEPS + 1):
        end = last - 7 * step
        if end - window + 1 < first_finance:
            break
        rows, _ = features(db, end, window)
        if not rows:
            continue
        s = model.project(model.standardize(_matrix(rows, keys), keys, [r["model"] for r in rows]))
        nearest = ((s[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
        out.append({"day": end, "approximate": end < first_snapshot,
                    "groups": {r["address"]: int(g) for r, g in zip(rows, nearest)}})
    return out[::-1]
