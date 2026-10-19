# big-ambitions-tool

Lecture des sauvegardes de **Big Ambitions** (Hovgaard Games) et export en données exploitables.

## Application web (recommandé)

Double-clic sur **`start.cmd`**. Au premier lancement, il crée `.venv`, extrait les données du jeu et
construit l'interface. Il ouvre ensuite http://127.0.0.1:8765, qui n'écoute qu'en local.

- La surveillance des sauvegardes tourne dans le serveur. Le bandeau du haut indique la sauvegarde
  utilisée et contient les boutons **Sync now** (Maj+clic pour forcer), **Refresh game data**,
  **Check biggerambitions**, et l'interrupteur **Auto-sync**.
- L'interface se met à jour seule après chaque import (événements SSE sur `/api/events`).
- Pages : Dashboard, P&L (jour / semaine / année, groupe / segment / commerce, frais de structure répartis
  ou non), Businesses et une fiche par commerce, Prices (plafonds, concurrence, historique), Market
  (opportunités, produits par quartier, activité des rivaux).
- Recommandations : `GET /api/recommendations?window=7`, `POST /api/recommendations/dismiss {key, dismissed}`.
- Fournisseurs : `GET /api/suppliers?item=` (importateurs, grossistes et recettes d'usine, table `suppliers`). Les
  produits « extra » des quais (vêtements chers…) n'y figurent que si l'option de partie
  `allProductsAvailableFromImporters` est active ; sinon ils se fabriquent en usine (`out/gamedata/factories_recipes.json`).
- Marketing : tables `marketing` (campagnes actuelles / idéales par commerce) et `marketing_options` (combinaison la
  moins chère pour chaque niveau de promotion), formules du jeu dans `bigambitions/marketing.py` ; carte Marketing de
  la fiche commerce et recommandations « Marketing ».
- Segmentation : `GET /api/segmentation?window=14` (ACP + Ward, voir `bigambitions/segmentation.py`).
- Recrutement : `GET /api/recruitment` (candidats classés, exigences à corriger, salaires vs marché, postes à
  pourvoir). Tables `candidate_fits` (candidat × commerce) et `employee_demands` (exigence × employé).
- Clients et effectifs : `GET /api/customers?days=60` ; la fiche commerce inclut `staffing` / `staffingHours`
  (postes planifiés vs nécessaires, heure par heure — voir `bigambitions/staffing.py`).
- La base enregistre l'empreinte du code qui l'a construite (`source.codeVersion`) : après une mise à jour de
  l'outil, la sauvegarde courante est réimportée automatiquement.
- API marché : `GET /api/prices`, `GET /api/prices/history?address=&item=`, `GET /api/market?neighborhood=`,
  `GET /api/market/opportunities`, `GET /api/market/activity?days=30`.
- API : `GET /api/status`, `GET /api/dashboard?window=7`, `GET /api/pnl?granularity=week&periods=8&scope=group&allocate=true`,
  `GET /api/pnl/businesses?firstDay=&lastDay=`, `GET /api/businesses`, `GET /api/businesses/{adresse}`,
  `GET /api/insights`, `POST /api/sync {force}`,
  `POST /api/gamedata/refresh`, `POST /api/checks/biggerambitions {refresh}`, `POST /api/watch {enabled}`.
- Développement de l'interface : `.venv/Scripts/python app.py --no-browser`, puis `cd web && npm run dev`
  (http://localhost:5173, l'API passe par le proxy de Vite).

## Lignes de commande

```
python sync.py --watch              # base centrale tenue à jour en continu (ou double-clic sur watch.cmd)
python sync.py                      # importe une fois la sauvegarde la plus récente si elle a changé
python export.py                    # export ponctuel de la plus récente (JSON + CSV + SQLite)
python export.py "chemin/vers.hsg"  # export ponctuel d'une sauvegarde précise
python dump.py                      # uniquement l'arbre brut en JSON

python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python extract_gamedata.py   # référentiel du jeu -> out/gamedata (à relancer après chaque mise à jour du jeu)
python check_biggerambitions.py            # écarts biggerambitions.com / jeu -> table check_biggerambitions
python -m unittest discover -s tests -t .  # tests (formules de prix, y compris contre la vraie sauvegarde)
```

### Tables ajoutées par le référentiel

- `ref_items`, `ref_neighborhoods`, `ref_buildings`, `ref_business_types`, `ref_skills` : référentiel du
  jeu (recréé à chaque import).
- `prices` : chaque produit vendu par le joueur, avec prix, **plafond accepté par les clients** (formule
  du jeu, au centime près), prix optimal, prix de référence, concurrent le moins cher, monopole, coût
  unitaire, marge unitaire et taux de refus sur le prix.
- `market_prices` : chaque produit × quartier, avec demande, fournisseurs, prix bas, concurrent le moins
  cher, prix moyen des concurrents, plafond, coût d'achat estimé et marge au prix optimal.
- `businesses` gagne `segment` (retail / office / logistics / headquarters / other), `neighborhood`, `sqm`
  et `typeLabel`.
- `hist_*` : historique cumulé par jour de jeu, conservé entre les imports (`hist_daily_finances`,
  `hist_daily_totals`, `hist_sales`, `hist_transactions`, `hist_prices`, `hist_market`,
  `hist_businesses`, `hist_employees`). Si le jour de la sauvegarde recule, les jours suivants sont effacés.
- `check_biggerambitions` : rapport d'écarts entre le site et le jeu.

Voir `PLAN.md` pour la feuille de route et les mécaniques du jeu (formules de prix).

## Base centrale et surveillance (`sync.py`)

`out/bigambitions.sqlite` reflète **la sauvegarde la plus récente** (le .hsg modifié en dernier),
qui fait foi : les tables listées plus bas ne contiennent que son contenu.

- `source` : une ligne, le fichier dont viennent les données (chemin, jour de jeu, argent, date d'import).
- `snapshots` : une ligne ajoutée à chaque import, jamais effacée. Comme les sauvegardes auto
  (`Recover #0..2`) sont réécrites en boucle, c'est cette table qui garde l'historique de la partie.

En mode `--watch`, le dossier est scanné toutes les 3 s (`--interval`). Quand la sauvegarde la plus
récente change (nouveau fichier, ou date/taille différente), elle est importée dès qu'elle est restée
stable 2 s (`--settle`), le temps que le jeu finisse de l'écrire ; si elle est encore illisible, elle
est retentée. Toutes les tables sont recréées en une seule transaction : la base n'est jamais à
moitié à jour. Les sauvegardes plus anciennes sont ignorées ; si la plus récente est supprimée, la
suivante prend le relais. Au démarrage, la base est rattrapée si besoin.

```sql
-- profit des 7 derniers jours par commerce
SELECT business, round(sum(profit)) FROM daily_finances
WHERE day > (SELECT max(day) - 7 FROM daily_finances)
GROUP BY business ORDER BY 2 DESC;
```

Python 3.10+, aucune dépendance externe.

## Format des sauvegardes

Dossier : `%USERPROFILE%\AppData\LocalLow\Hovgaard Games\Big Ambitions\SaveGames\Big Ambitions\<characterId>\`

| Fichier | Contenu |
|---|---|
| `<nom>.hsg` | gzip → flux binaire **Odin Serializer** (Sirenix) ; racine = objet `GameInstance` (~15 Mo décompressé) |
| `<nom>.hsg.meta` | JSON : nom du personnage, âge, apparence (affiché dans le menu de chargement) |
| `<nom>.jpg`, `portrait.jpg` | captures pour le menu |
| `<Commerce>/*.jpg` | logos / enseignes des commerces |
| `Recover #0..2`, `Recover Midnight` | sauvegardes automatiques tournantes |

Le décodeur Odin (`bigambitions/odin.py`) est générique : il convertit tout le flux en dict/list Python,
aplatit les `List`/`Dictionary`/`Nullable` et résout les références internes.

## Sorties (`out/<sauvegarde>/`)

- `raw.json` : tout le contenu décodé.
- `summary.json` : vue d'ensemble du joueur + commerces.
- `save.sqlite` et `csv/*.csv` (séparateur `;`) : les tables ci-dessous.

| Table | Source dans `GameInstance` | Contenu |
|---|---|---|
| `businesses` | `BuildingRegistrations` (loués par le joueur) | nom, type, loyer, effectif, horaires, satisfaction, promotion, CA du dernier jour |
| `employees` | `EmployeeInstances` | nom, commerce, salaire horaire, heures/semaine, satisfaction, compétences, exigences |
| `inventory` | `itemInstances[].cargoInstances`, `VehicleInstances` | stock par commerce/véhicule et par produit, valeur d'achat |
| `retail_prices` | `retailPrices` | prix de vente par commerce et produit |
| `sales_history` | `orderHistory` | ventes journalières par produit : quantité, CA, coût de gros, marge |
| `daily_finances` | `financialSummaries[].businessIncomeStatements` | compte de résultat journalier par commerce (~60 derniers jours) |
| `daily_totals` | `financialSummaries` | totaux journaliers (profit global, assurance santé, ...) |
| `transactions` | `Transactions` | les 1000 dernières transactions bancaires |
| `vehicles` | `VehicleInstances` | type, stationnement, carburant, dégâts, chargement |
| `market` | `productMarketEntries` | demande et nombre de fournisseurs par produit et quartier |
| `market_events` | `marketEvents` | événements de marché |
| `city_buildings` | `BuildingRegistrations` | tous les bâtiments de la ville (rivaux, libres, joueur) |
| `buildings_for_sale` | `buildingsForSale` | immeubles à vendre |
| `rivals` | `rivalStates`, `specialRivalStates` | revenu hebdo et nombre de commerces des rivaux |
| `import_partnerships` | `importPartnerships` | contrats d'import : produits, quantités, entrepôt cible |
| `candidates` | `CandidateEmployeeInstances` | candidats au recrutement : compétences, salaire demandé, source (job board, chasseur) |
| `salary_negotiations` | `candidateSalaryNegotiations` | négociations salariales : salaire, prime, issue, humeur |
| `contacts` | `Contacts` | contacts du téléphone : type, adresse, nb de messages / non lus |
| `messages` | `Contacts[].messagesQueue` | tous les SMS, horodatés |
| `manager_plans` | `hrManagerPlans`, `logisticsManagerPlans`, `pricingManagerPlans`, `headhunterPlans` | un plan par manager du siège (kind = hr / logistics / pricing / headhunter) |
| `logistics_targets` | `logisticsManagerPlans[].destinations` | objectifs de stock : entrepôt -> commerce, produit, quantité |
| `pricing_plan_prices` | `pricingManagerPlans[].appliedPrices` | prix appliqués par les managers de prix, par quartier |
| `quests` | `CompletedQuestEntries`, `completedSideQuestEntries`, `activeSideQuestEntries`, `completedPersonalGoals` | quêtes et objectifs personnels |
| `notifications` | `notifications` | notifications du jeu, horodatées |

Les identifiants du jeu (`ba:itemname_burger`, `ba:street_fifthavenue`, ...) sont simplifiés en `burger`,
`fifthavenue`. Les adresses sont notées `<numéro> <rue>`, ce qui sert de clé de jointure entre les tables.

## Utilisation en Python

```python
from bigambitions import find_latest_save, load
from bigambitions.model import Save

save = Save(load(find_latest_save()))
save.player()            # dict
save.businesses()        # list[dict]
save.game["Money"]       # accès direct à l'arbre brut
```

## Limites

Les noms des rivaux et les enums numériques (diplômes, types d'événements, catégories de contact)
viennent des données du jeu, absentes de la sauvegarde : ils restent sous forme d'identifiants.
Le détail brut (positions des meubles, apparence des personnages, ...) n'est que dans `raw.json`.
