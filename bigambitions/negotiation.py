"""Négociation de salaire avec un candidat : seuils exacts, meilleure stratégie et salaire obtenu.

Mécanique (AI.Employees.SalaryNegotiation, CandidateSalaryNegotiationParams) :

- le candidat demande d'abord son salaire (⌈salaire × 20⌉ / 20 ; × 1,25 pour l'employé d'un rival ou un débauché) ;
- à chaque offre du joueur (salaire + prime / 1920), comparée à la dernière proposition du candidat :
  - ≥ seuil d'acceptation (95 % si humeur ≥ 50, 97,5 % si ≥ 25, 99 % sinon) : accepté ;
  - ≥ seuil de négociation (tiré entre 80 et 90 %) : contre-proposition à mi-chemin (40 à 60 % vers l'offre du joueur,
    arrondie aux 5 cents supérieurs), humeur −4 à −6 ;
  - ≥ seuil de fermeté (tiré entre 60 et 70 %) : refus sans bouger, humeur −10 à −20 ;
  - en dessous : refus et proposition relevée de 10 à 20 %, humeur −25 à −30 ;
  - humeur < 20 : le candidat met fin à la négociation.
- à l'embauche, satisfaction = min(100, 50 + (humeur − 100) / 2) ; elle remonte ensuite d'au plus 0,6 point par heure
  travaillée vers son plafond (60 / 80 / 100 selon les exigences tenues).

Les deux seuils sont tirés une fois, au début de la négociation, avec UnityEngine.Random initialisé sur
``id.GetHashCode() + jour`` : on les reproduit exactement (111 négociations de la sauvegarde sur 111). Le jour où l'on
commence change donc les seuils. Le reste (pas de la contre-proposition, baisse d'humeur) n'est pas prévisible : on
donne un résultat attendu et un résultat prudent.

Meilleure stratégie : offrir à chaque round juste le seuil de négociation × la dernière proposition (la proposition
baisse de ≈ (1 − seuil) / 2 à chaque round, pour −5 d'humeur), puis conclure à 95 % (ou 97,5 / 99 %) de la dernière
proposition. Sans prime : le candidat compte une prime sur 1920 heures, bien plus que la durée de la plupart des
contrats.
"""
from __future__ import annotations

import math
from typing import Any

M32 = 0xFFFFFFFF
START_MOOD = 100
DECLINE_BELOW = 20
GOOD_MOOD, NEUTRAL_MOOD = 50, 25
ACCEPT = {"good": 0.95, "neutral": 0.975, "bad": 0.99}
NEGOTIATE_RANGE = (0.8, 0.9)
FIRM_RANGE = (0.6, 0.7)
STEP_EXPECTED, STEP_CAUTIOUS = 0.5, 0.4  # part du chemin vers l'offre du joueur (tirée entre 0,4 et 0,6)
DROP_EXPECTED, DROP_CAUTIOUS = 5, 6  # baisse d'humeur par contre-proposition (tirée entre 4 et 6)
MAX_ROUNDS = (START_MOOD - DECLINE_BELOW) // DROP_CAUTIOUS
RECOVERY_PER_HOUR = 0.6
RIVAL_MARKUP = 1.25
LOOKAHEAD_DAYS = 7


def _int32(h: int) -> int:
    h &= M32
    return h - (1 << 32) if h & 0x80000000 else h


def string_hash(s: str) -> int:
    """String.GetHashCode du runtime du jeu (.NET 64 bits, non randomisé)."""
    h1 = h2 = 5381
    chars = [ord(c) for c in s] + [0]
    i = 0
    while chars[i]:
        h1 = (((h1 << 5) + h1) ^ chars[i]) & M32
        if not chars[i + 1]:
            break
        h2 = (((h2 << 5) + h2) ^ chars[i + 1]) & M32
        i += 2
    return _int32(h1 + h2 * 1566083941)


class UnityRandom:
    """UnityEngine.Random : Xorshift128 initialisé par InitState(seed)."""

    def __init__(self, seed: int):
        s = [seed & M32]
        for _ in range(3):
            s.append((s[-1] * 1812433253 + 1) & M32)
        self.s = s

    def _next(self) -> int:
        x, y, z, w = self.s
        t = (x ^ (x << 11)) & M32
        new = (w ^ (w >> 19) ^ t ^ (t >> 8)) & M32
        self.s = [y, z, w, new]
        return new

    def range(self, lo: float, hi: float) -> float:
        u = (self._next() & 0x7FFFFF) / 8388607.0
        return hi + (lo - hi) * u


def thresholds(employee_id: str, day: int) -> tuple[float, float]:
    """(seuil de négociation, seuil de fermeté) d'une négociation commencée le jour ``day``."""
    r = UnityRandom(_int32(string_hash(employee_id) + day))
    return r.range(*NEGOTIATE_RANGE), r.range(*FIRM_RANGE)


def _ceil(value: float, step: float) -> float:
    return math.ceil(round(value / step, 6)) * step


def accept_factor(mood: int) -> float:
    return ACCEPT["good"] if mood >= GOOD_MOOD else ACCEPT["neutral"] if mood >= NEUTRAL_MOOD else ACCEPT["bad"]


def satisfaction_at_hire(mood: int) -> float:
    return min(100.0, 50 + (mood - 100) / 2)


def simulate(counter: float, negotiate: float, rounds: int, step: float, drop: int, mood: int = START_MOOD) -> dict[str, Any]:
    """``rounds`` offres au seuil de négociation, puis l'offre de clôture. ``counter`` : dernière proposition du candidat."""
    script = []
    for _ in range(rounds):
        # Au cent supérieur, plus un cent de marge : le jeu compare des float32.
        offer = _ceil(counter * negotiate, 0.01) + 0.01
        new = _ceil(counter + (offer - counter) * step, 0.05)
        mood -= drop
        script.append({"offer": round(offer, 2), "counter": round(new, 2), "mood": mood})
        counter = new
    final = _ceil(counter * accept_factor(mood), 0.01) + 0.01
    return {"script": script, "lastCounter": round(counter, 2), "final": round(final, 2), "mood": mood,
            "satisfaction": satisfaction_at_hire(mood)}


def plan(employee_id: str, asking: float, day: int, expires_in_hours: int | None = None,
         pending: dict[str, Any] | None = None, weekly_hours: float = 40) -> dict[str, Any]:
    """Stratégie pour un candidat. ``pending`` : négociation déjà commencée (seuils, humeur et proposition figés)."""
    if pending:
        negotiate, firm = pending["negotiateThreshold"], pending["firmThreshold"]
        mood, counter, start_day = pending["mood"], pending["lastCounter"], None
        days = []
    else:
        horizon = LOOKAHEAD_DAYS if expires_in_hours is None else max(1, min(LOOKAHEAD_DAYS, expires_in_hours // 24 + 1))
        days = [{"day": d, "negotiate": thresholds(employee_id, d)[0]} for d in range(day, day + horizon)]
        best = min(days, key=lambda d: d["negotiate"])
        start_day = best["day"]
        negotiate, firm = thresholds(employee_id, start_day)
        mood, counter = START_MOOD, _ceil(asking, 0.05)
    options = _options(counter, negotiate, mood, weekly_hours)
    # Maximum d'économie sans risque d'abandon ; « équilibré » : la clôture reste à 95 % (humeur ≥ 50).
    best_k, balanced_k = _picks(options)
    # Le joueur ne commence pas forcément le jour conseillé : options pour chaque jour de début possible.
    for d in days:
        d["negotiate"], d["firm"] = thresholds(employee_id, d["day"])
        d["options"] = _options(counter, d["negotiate"], mood, weekly_hours)
        d["bestRounds"], d["balancedRounds"] = _picks(d["options"])
    return {
        "asking": round(counter, 2), "negotiateThreshold": negotiate, "firmThreshold": firm,
        "todayNegotiateThreshold": days[0]["negotiate"] if days else negotiate,
        "startDay": start_day, "days": days, "mood": mood, "pending": bool(pending),
        "bestRounds": best_k, "balancedRounds": balanced_k, "options": options,
    }


def _picks(options: list[dict[str, Any]]) -> tuple[int, int]:
    return options[-1]["rounds"], max((o["rounds"] for o in options if o["moodCautious"] >= GOOD_MOOD), default=0)


def _options(counter: float, negotiate: float, mood: int, weekly_hours: float) -> list[dict[str, Any]]:
    options = []
    for k in range(0, (mood - DECLINE_BELOW) // DROP_CAUTIOUS + 1):
        expected = simulate(counter, negotiate, k, STEP_EXPECTED, DROP_EXPECTED, mood)
        cautious = simulate(counter, negotiate, k, STEP_CAUTIOUS, DROP_CAUTIOUS, mood)
        options.append({"rounds": k, "final": expected["final"], "finalCautious": cautious["final"],
                        "mood": expected["mood"], "moodCautious": cautious["mood"],
                        "satisfaction": expected["satisfaction"], "satisfactionCautious": cautious["satisfaction"],
                        "savingPerWeek": round((counter - expected["final"]) * weekly_hours, 2),
                        "script": expected["script"]})
    return options


def pending_negotiations(game: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Négociations en cours par employé : seuils, humeur et dernière proposition du candidat."""
    out = {}
    for n in game.get("candidateSalaryNegotiations") or []:
        employee = n.get("employeeInstance") or {}
        offers = n.get("offers") or []
        mine = [o for o in offers if o.get("fromCandidate")]
        if n.get("completed") or not employee.get("id") or not mine or not n.get("negotiateThreshold"):
            continue
        last = mine[-1]
        out[employee["id"]] = {"negotiateThreshold": n["negotiateThreshold"], "firmThreshold": n["firmThreshold"],
                               "mood": n.get("mood", START_MOOD),
                               "lastCounter": last["hourlyWage"] + (last.get("signingBonus") or 0) / 1920}
    return out
