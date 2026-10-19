# Plan — outil d'analytics Big Ambitions

Usage local uniquement. Interface et noms du jeu en anglais (`locale_en.json`).

## Phase 0 — ce qu'on peut obtenir du jeu (terminée)

| Source | Obtenu | Comment |
|---|---|---|
| Sauvegarde `.hsg` | état complet de la partie | `bigambitions/odin.py` (déjà en place) |
| Bundles Addressables du jeu | **référentiel complet** : 137 produits (`wholesalePrice`, `defaultMarketPrice`, `boxSize`, quartiers où la demande existe…), 44 types de commerce (produits, compétences des employés, prérequis), 8 quartiers (répartition des classes sociales, immobilier, force du marketing), 885 bâtiments (**quartier**, trafic, surface, type), 146 commerces IA (nom, rival propriétaire), compétences (salaire horaire de base), exigences d'emploi, véhicules, objectifs | `extract_gamedata.py` → `out/gamedata/` (UnityPy, ~1 min) |
| `StreamingAssets/locale/en.json` | noms affichés + encyclopédie du jeu | copié dans `out/gamedata/locale_en.json` |
| `BigAmbitions.dll` (décompilé avec ilspycmd, **non versionné**) | **formules** de prix, d'acceptation, de satisfaction et du manager de prix | lu, puis résumé ci-dessous |
| biggerambitions.com | mêmes prix, arrondis et légèrement décalés par rapport à la version actuelle (ex. burger à Lower Manhattan : 15,6 sur le site contre 15,72 dans le jeu) | pages HTML `<table id="myTable">`, sans API |
| morluto/rea | non nécessaire : c'est un MCP générique de rétro-ingénierie (binaires, .NET…), pas un jeu de données | solution de repli si une future version du jeu devient illisible |

### Mécaniques du jeu (validées au centime sur la sauvegarde)

- **Indice de prix d'un quartier** = (1,2·%ouvrière + 1,4·%moyenne + 1,7·%aisée) / 100.
  Garment District 1,284 · Hell's Kitchen 1,424 · Murray Hill 1,342 · Midtown 1,682 · Lower Manhattan 1,258 · Industry City 1,246 · Hamptons 1,636.
- **Prix optimal** = `defaultMarketPrice` × indice du quartier, **+0,3 en cas de monopole du joueur**.
- **Prix le plus bas du marché** = le prix le plus bas pratiqué dans le quartier par un commerce ouvert (celui du joueur, ou un commerce IA qui a du stock). Si personne ne vend le produit, c'est le prix optimal.
- **Prix de référence** = min(`defaultMarketPrice`, prix le plus bas du marché).
- **Prix maximum accepté** par un client = prix de référence × max(indice de sa classe (1,2 / 1,4 / 1,7), indice de son quartier), +0,3 en cas de monopole. **Le quartier pris en compte est celui d'origine du client**, pas celui du magasin.
  → Un rival qui casse ses prix fait baisser le plafond de tout le quartier : c'est exactement le cas d'Error Affairs. Reprendre le monopole rapporte +30 %.
- **Satisfaction « prix »** = % des articles commandés la veille dont le prix était acceptable (la sauvegarde contient `priceAccceptable` pour chaque article, commande par commande). Satisfaction globale = moyenne de service client, prix, propreté et équipements.
- **Manager de prix** : il propose un prix entre le prix de référence et le plafond, et s'approche du plafond d'autant plus que sa compétence est élevée.
- **Code couleur des prix dans le jeu** : jaune au-dessus de la référence, rouge au-dessus de 2 × `defaultMarketPrice`.
- Noms des rivaux : les rivaux spéciaux sont dans les données du jeu. Les autres ont un nom généré à partir de leur identifiant ; 13 noms apparaissent déjà dans les messages de la sauvegarde. Pour le reste, on reproduira le générateur ou on gardera l'identifiant.

## Services de l'outil

### Service « référentiel du jeu » (source de vérité)
- `bigambitions/reference.py` : charge `out/gamedata` (produits, quartiers, bâtiments, types de commerce, compétences) et les noms anglais.
- `bigambitions/pricing.py` : les formules du jeu ci-dessus (indice de quartier, prix optimal, prix de référence, plafond, effet du monopole), calculées à partir de la sauvegarde. Testées contre la sauvegarde (écart attendu : 0,01 $ au maximum).
- **Détection des mises à jour du jeu** : si `BigAmbitions.dll` ou les bundles ont changé depuis `version.json`, l'outil le signale et relance l'extraction.
- **Wrapper biggerambitions** : client avec cache, utilisé uniquement pour produire un **rapport d'écarts** avec nos calculs (produit, quartier, valeur du site, valeur du jeu). Il ne sert jamais de source.

### Pilotage depuis l'outil
- Le serveur lance la surveillance en tâche de fond au démarrage (on peut l'activer ou la désactiver).
- Endpoints : `POST /api/sync` (import immédiat, avec option `force`), `POST /api/gamedata/refresh` (ré-extraction), `GET /api/status` (source actuelle, dernier import, surveillance active ou non, version des données du jeu, écarts avec biggerambitions), `GET /api/events` (SSE : import démarré / terminé / erreur).
- Interface : bandeau d'état (sauvegarde utilisée, jour de jeu, ancienneté), boutons **Sync**, **Ré-extraire les données du jeu** et interrupteur de surveillance.

## Segmentation statistique (ACP + CAH de Ward)

> **Réalisé (phase 7)**, avec trois écarts au plan, imposés par les données :
> - les variables sont centrées *par modèle économique* (bureau, boutique, service en boutique) : sans cela, l'ACP ne
>   retrouvait que la différence bureau / boutique ;
> - seuls les *leviers* forment les axes ; les résultats (marge, profits, CA, tendance) sont projetés en supplémentaires ;
> - les actions comparent chaque commerce à la meilleure moitié de ses pairs du même modèle, plutôt qu'au groupe de tête
>   (avec deux groupes proches en rentabilité, ce dernier n'est pas une bonne référence). Pas de groupe d'un seul commerce.

**Échantillon** : les commerces qui génèrent du CA (12 aujourd'hui). Le siège et les entrepôts sont des centres de coût, évalués à part, et leur coût est réparti sur les commerces qu'ils servent.

**Variables**, calculées sur une fenêtre glissante, de 14 jours par défaut :
- *rentabilité* : marge, profit par jour, profit par employé, profit par m² ;
- *structure de coûts* : poids des achats, des salaires, du loyer et du marketing dans le CA ;
- *activité* : CA par jour, clients par jour, taux d'occupation (clients / capacité × heures d'ouverture) ;
- *qualité* : satisfaction et ses 4 composantes, taux de refus sur le prix ;
- *prix* : prix pratiqué / plafond, présence d'un monopole ;
- *dynamique* : tendance du profit (pente sur la fenêtre) ;
- *emplacement* : trafic du bâtiment, indice du quartier.

**Méthode** :
1. Centrage-réduction des variables, puis ACP. On garde les axes qui expliquent 80 % de la variance, et on les interprète à partir des contributions des variables.
2. CAH de Ward sur ces axes. Le nombre de groupes est choisi par le saut d'inertie et le score de silhouette.
3. Les groupes sont nommés automatiquement d'après leurs variables distinctives (valeurs-tests).

**Des groupes aux actions** :
- pour chaque commerce, on mesure l'écart à la moyenne du groupe le plus performant sur chaque variable ;
- les plus gros écarts sur des variables *pilotables* (salaires, prix, satisfaction, horaires, stock) deviennent des actions chiffrées : par exemple « salaires à 95 % du CA contre 16 % dans le groupe performant → réduire les heures ou l'effectif de N ».
- on affiche aussi l'historique des groupes, pour voir un commerce changer de groupe après une action.

**Ce que montre le prototype sur la sauvegarde actuelle** :
- l'axe 1 (45 % de la variance) est un axe de *rentabilité* : marge et profit par employé d'un côté, poids des salaires de l'autre. L'axe 2 (20 %) oppose le *volume* (CA) au *trafic et au poids des achats*.
- k = 2 (silhouette 0,33) isole **Error Affairs et Schneidermore**, dont les salaires représentent environ 100 % du CA. Les autres commerces ont des salaires autour de 16 % du CA et une marge d'environ 62 %.
- **Angelair** se retrouve à tort dans ce groupe : ouvert au jour 202, sa « croissance » est artificielle. Il faut donc **exclure ou signaler les commerces de moins de 14 jours**, et utiliser une tendance robuste plutôt qu'une comparaison entre deux semaines.
- avec environ 12 commerces, la structure des groupes reste fragile. On affichera la silhouette et l'appartenance de chaque commerce à son groupe, et on complétera par les règles explicites (points d'attention). La segmentation sert à prioriser, pas à décider seule.

## Architecture

```
.hsg ───────────┐
gamedata ───────┼─> ingestion (sync.py) ─> SQLite
biggerambitions ┘   (wrapper + cache)      ├─ current_*  dernière sauvegarde (remplacé)
                                           ├─ hist_*     historique fusionné par jour de jeu
                                           └─ ref_*      référentiel du jeu
                          └─> moteur d'analyse et de recommandations ─> FastAPI (REST + SSE) ─> React
```

## Phases

1. ✅ **Données** (terminée) : `reference.py`, `pricing.py` (68/68 prix des managers reproduits au
   centime), tables `prices`, `market_prices` et `ref_*`, historique `hist_*` (`history.py`), wrapper
   `biggerambitions.py` + `check_biggerambitions.py`, tests (`tests/`).
   Constat : biggerambitions tronque les indices de quartier à 2 décimales (1,28 au lieu de 1,284),
   d'où des prix par quartier sous-estimés de 0,1 à 0,7 %. Prix par défaut, cartons et prix de gros :
   identiques au jeu.
   Détail initial de la phase :
   - Tables `ref_*` construites depuis `out/gamedata`.
   - Prix calculés par commerce et par produit : référence, plafond, optimal, monopole, prix le plus bas des concurrents.
   - Historique `hist_*` (P&L, ventes, prix, demande, satisfaction, employés) fusionné par jour de jeu. Si le jour de la sauvegarde recule (vieille partie rechargée), les jours suivants sont effacés.
   - Wrapper `biggerambitions` : client avec cache disque, qui sert de contrôle de cohérence avec les données du jeu.
2. ✅ **API + squelette web** (terminée) : `bigambitions/ingest.py` (import et surveillance partagés par
   la CLI et le serveur), `bigambitions/server.py` (FastAPI : statut, sync, ré-extraction, contrôle
   biggerambitions, surveillance, SSE), `bigambitions/queries.py`, `app.py` / `start.cmd` ; interface
   `web/` (React + Vite + ECharts) avec bandeau d'état, navigation vers les futurs modules et tableau de
   bord (profit sur la fenêtre et évolution, trésorerie, profit journalier, profit par commerce, tableau
   des commerces, premiers points d'attention). Thème clair/sombre, vue tableau pour les graphiques.
3. ✅ **Finances** (terminée) :
   - Centres de profit (retail, office) séparés des centres de coût (siège, entrepôts) et du logement
     (segment `home`, bâtiment résidentiel).
   - `pnl.py` : compte de résultat par jour / semaine (jour 1 = lundi) / année, pour le groupe, un segment
     ou un commerce. Il retombe sur le profit net du jeu (écart < 0,05 $). Répartition des frais de structure :
     siège + coûts de personnel communs au prorata des effectifs, chaque entrepôt au prorata du CA des
     commerces qu'il livre, le reste au prorata du CA. Commerces fermés conservés dans l'historique.
   - `insights.py` : points d'attention croisés (perte, profit après frais négatif, baisse de profit,
     poids des salaires, satisfaction décomposée — le service client vaut compétence × satisfaction de
     l'employé —, stock en jours de couverture avec l'état de l'entrepôt qui livre, prix sous ou au-dessus
     du plafond, refus, concurrent qui plafonne le prix, monopole, employés mécontents ou absents),
     chacun avec ses chiffres, une action et un impact estimé en $/jour.
   - Interface : pages P&L, Businesses et fiche commerce (KPI, CA et profit par jour, produits et prix,
     satisfaction, bâtiment, logistique, personnel) ; le tableau de bord sépare commerces et frais de structure.
   - Tests : `tests/test_pnl.py` (rapprochement, conservation de la répartition, périodes).
4. ✅ **Prix & marché** (terminée) :
   - Mécaniques ajoutées (code du jeu) : demande = 100 − fournisseurs × 100 / fournisseurs optimaux
     (plancher ≈ 30, + événements) ; fournisseurs optimaux = min(⌈√(1300 / prix de base)⌉, 7) ; monopole =
     aucun commerce **d'un rival** n'a le produit en rayon ; pénurie / rupture = prix d'achat × 1,25 / × 1,5
     (multiplicateurs repris de biggerambitions, ScriptableObject non extrait) ; loyer d'un local =
     formule Building.GetBuildingDailyMarketRent (16/16 loyers du joueur reproduits).
   - Noms des rivaux retrouvés via les ouvertures de commerces (15 sur 19).
   - Tables `competitor_prices` (+ `hist_competitor_prices`), `market_prices` enrichie (fournisseurs
     optimaux, place restante, rivaux qui bloquent le monopole, événements actifs), `market_events` lisible,
     loyer estimé des locaux libres dans `city_buildings`.
   - `market.py` + pages Prices (plafond, concurrence, gain possible, historique prix vendu / plafond /
     concurrent) et Market (opportunités par type × quartier, produits par quartier, activité des rivaux).
   - Points d'attention : nouveau concurrent, monopole perdu / gagné / à portée (regroupé par commerce),
     hype, pénurie ; stock jugé au niveau magasin (objectif logistique) puis entrepôt (imports prévus) ;
     employés débauchés mis à part.
5. ✅ **Recrutement** (terminée) — `recruitment.py`, page Recruitment :
   - Salaire du marché = base de la compétence × (1 + compétence^1,05 / 100) × difficulté : 340/340 candidats
     reproduits ; les employés en poste sont comparés à ce prix (sous / sur-payés).
   - Satisfaction : elle tend vers 60 / 80 / 100 selon la part d'exigences tenues (EmployeeInstance.UpdateSatisfaction) ;
     sans exigence elle ne bouge plus. Les 35 exigences sont évaluées avec les règles du jeu (horaires, jours,
     week-ends, objets au poste ou dans le bâtiment « remplis », mutuelle du plan RH, propreté réelle calculée
     depuis les taches, humeur du joueur) : 98/98 employés comparables au plafond calculé, les autres y remontent.
   - Candidats : évalués pour chaque commerce qui emploie leur compétence (exigence remplie / arrangeable par le
     planning / manquante + correction), compétence effective = compétence × satisfaction atteinte.
   - Point d'attention par commerce listant les exigences non tenues et leur correction ; postes à pourvoir
     (débauchés, heures de bureau en sous-effectif).
   - L'empreinte de code est figée au chargement (un ancien processus ne peut plus tamponner la base avec la
     version d'un code qu'il n'exécute pas).
6. ✅ **Recommandations** (terminée) — `recommendations.py`, page Recommendations (écarter / restaurer, stocké dans
   `user_dismissals`, conservé entre les imports). Chaque action : gain $/jour, confiance, effort, étapes, explication.
   Prix au plafond ; créneaux inutiles jour par jour ; exigences des employés (gain via service client → satisfaction
   globale → clients / panier) ; nombre de commerces de bureau par marché (fermer un doublon ou en ouvrir un de plus :
   demande cumulée n·d(n), capacité des postes, coûts fixes calqués sur l'existant) ; monopoles (commerces rivaux à
   faire disparaître, et gain débloqué par la défaite de chaque rival) ; stock ; pertes ; expansion.
   + Onglet Market « Where to buy » : importateurs (référentiel, via Building → SpecialService → ImportExportSettings,
   extraction avec `$pathId`) et grossistes (produits en vente dans la sauvegarde), contrat en cours, prix d'achat.
   Notes initiales de la phase (18/10) :
   - **Nombre cible de fournisseurs pour le joueur**, par produit / type de commerce et par quartier. Avec
     n commerces du joueur et r rivaux, chaque commerce a la demande d(n+r) = max(≈31,5 ; 100 − (n+r)·100/optimal)
     et la demande cumulée vaut n·d(n+r). Recommander le n qui maximise la marge (demande cumulée × marge
     unitaire) moins les coûts fixes (loyer + personnel) de chaque commerce. Exemple : événementiel à Garment
     District (optimal 3) → 1 agence ≈ 67, 2 agences ≈ 67 (pire rapport coût / clients), 3 agences ≈ 95.
     Distinguer bureau (clients ∝ demande, plafonnés par les postes) et détail (clients = bâtiment × promotion,
     demande = panier). Vérifier dans le code de création des commerces IA si une demande élevée attire les
     rivaux (la saturation volontaire serait alors une défense).
   - Reprendre les points d'attention « sureffectif » (staffing.py) sous forme d'actions : quels créneaux
     supprimer, quel gain hebdomadaire.
   Initialement prévu : règles qui croisent les sources, avec le gain estimé et les chiffres qui justifient chaque recommandation.
   Exemple : « Error Affairs : monopole retrouvé le jour X → le plafond est passé de A à B, tes ventes se font au prix monopole ; risque : le rival R revient dans le quartier ».
7. **Segmentation statistique** (voir la section dédiée) : ACP + Ward, carte des commerces sur les deux premiers axes, profil de chaque groupe, actions déduites des écarts au groupe performant, historique des groupes.

Le service « référentiel » et le pilotage du sync font partie des phases 1 et 2.
