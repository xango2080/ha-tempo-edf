# EDF Tempo pour Home Assistant

Intégration personnalisée qui récupère les **couleurs Tempo** (bleu, blanc, rouge), **garde tout l'historique** sur disque et expose des capteurs prêts pour tes tableaux de bord, tes automatisations et la section Énergie.

- **Aucun compte requis** : source gratuite [Jour Tempo](https://jourtempo.fr/api/) (couleurs publiées par RTE). L'API officielle RTE est facultative.
- **Historique depuis 2014** importé en une requête, conservé hors des purges du recorder.
- **Résilient** : si une source tombe, les couleurs déjà reçues restent disponibles.

## Entités

| Entité | Contenu |
|---|---|
| `sensor.edf_tempo_couleur_aujourd_hui` | Bleu / Blanc / Rouge (capteur à liste d'états : l'éditeur d'automatisations propose un menu déroulant). Attributs : `color` (blue/white/red), `emoji`, `color_hex`, `date` |
| `sensor.edf_tempo_couleur_demain` | idem ; `unknown` tant que la couleur de demain n'est pas annoncée (vers 11 h) |
| `sensor.edf_tempo_tarif_actuel` | ex. `Bleu HP` (attributs `period`, `is_hc`, `is_hp`) |
| `sensor.edf_tempo_prix_actuel` | prix €/kWh en cours (grille en vigueur aujourd'hui) |
| `sensor.edf_tempo_prix_<couleur>_<hc/hp>` | les 6 tarifs fixes (€/kWh) |
| `sensor.edf_tempo_jours_bleus_restants`, `..._blancs_...`, `..._rouges_...` | jours restants de la saison par couleur (quotas lus dans `tempo.json`, 300 / 43 / 22 par défaut). Demain est déduit dès son annonce. Attributs `quota`, `used`, `history_complete`. `unknown` si l'historique de la saison est incomplet |
| `sensor.edf_tempo_saison` | saison en cours (ex. `2026-2027`), avec jours utilisés/restants en attributs |
| `sensor.edf_tempo_enedis_derniere_donnee` | (si Enedis est configuré) dernier jour complet importé ; attributs `status`, `last_run`, `imported_days`, `unassigned_hours` |
| `calendar.edf_tempo_calendrier` | un évènement par jour Tempo, historique consultable |

Le jour Tempo change à **06:00** (de 6 h à 6 h le lendemain). Heures creuses : **22:00 à 06:00**. Les capteurs de prix et de jours restants sont des mesures (`state_class: measurement`) : leurs statistiques long terme sont conservées par Home Assistant.

## Installation

### Avec HACS (recommandé)

1. HACS → menu ⋮ → **Dépôts personnalisés** → URL `https://github.com/xango2080/ha-tempo-edf`, catégorie **Intégration**.
2. Télécharger **EDF Tempo**, puis redémarrer Home Assistant.

Le dépôt GitHub doit être **public** pour que HACS puisse le lire.

### Manuelle

Copier `custom_components/tempo_edf/` dans `/config/custom_components/`, puis redémarrer Home Assistant (avec Docker : `docker compose restart <service>`).

### Ajouter l'intégration

Paramètres → Appareils et services → Ajouter une intégration → **EDF Tempo**. Laisser les champs RTE **vides** pour utiliser la source gratuite. Puis, sur l'intégration → **Configurer**, saisir les 6 tarifs TTC.

## Mise à jour

1. Pousser la nouvelle version sur GitHub et créer une **release** (tag `vX.Y.Z`). Sans release, HACS se rabat sur le dernier commit.
2. HACS → EDF Tempo → ⋮ → **Mettre à jour les informations**, puis **Mettre à jour**.
3. Redémarrer Home Assistant.

Les réglages et l'historique sont conservés (ils sont dans `/config/.storage/`, hors du dossier de l'intégration).

## Sources des couleurs

| Source | Compte | Rôle |
|---|---|---|
| **Jour Tempo** (`jourtempo.fr/api/v1`) | non | Source par défaut : `tempo.json` (jour, demain, calendrier de la saison) et `tempo-historique.csv` (depuis 2014) |
| **API officielle RTE** « Tempo Like Supply Contract » | oui (facultatif) | Si les identifiants sont renseignés, interrogée en premier ; Jour Tempo sert de secours |

- **Quand la couleur de demain arrive** : RTE la fixe vers **10 h 30** ; Jour Tempo relève à 11:00, 11:30, 12:00 et 12:30 (heure de Paris). L'intégration vérifie à **11:05, 11:35, 12:05, 12:35 et 13:05** (et à 10:35 et 10:50 si une clé RTE est configurée), puis toutes les heures tant que la couleur manque. La couleur de demain reste donc `unknown` entre 06:00 et environ 11:05.
- **Aucun appel inutile** : avant 10 h 30, la couleur de demain ne peut pas exister, donc rien n'est demandé ; dès qu'elle est connue, plus aucun appel jusqu'au lendemain. En pratique, quelques requêtes par jour. Jour Tempo recommande un appel toutes les 30 minutes au plus, jamais moins de 10.
- **Attribution** : « Couleurs : RTE, via Jour Tempo (jourtempo.fr) ». Jour Tempo est un site indépendant, édité ni par EDF ni par RTE, sans garantie de disponibilité.
- **En cas de panne** : les couleurs stockées restent utilisées, et les capteurs restent disponibles.

### Facultatif : clé RTE officielle

1. Créer un compte sur <https://data.rte-france.com>.
2. Ouvrir l'API **Tempo Like Supply Contract** et cliquer sur **S'abonner**.
3. Créer une application et la rattacher à cet abonnement (sans abonnement, RTE répond 403).
4. Recopier l'**ID client** et l'**ID secret** (pas le bouton « Copier en base 64 »).
5. Les saisir à l'ajout de l'intégration.

## Historique des saisons passées

Dans **Configurer**, « Saisons d'historique à récupérer » (3 par défaut, 12 maximum). L'import se fait en tâche de fond : une seule requête sur le CSV Jour Tempo ; si elle échoue et qu'une clé RTE est configurée, une requête par saison. La progression est sauvegardée. Pour remonter plus loin, augmenter le nombre. Les jours importés apparaissent dans `calendar.edf_tempo_calendrier`.

## Tarifs datés

L'intégration est livrée avec l'historique des grilles Tempo (€/kWh TTC, identiques de 6 à 36 kVA) :

| En vigueur depuis | Bleu HC / HP | Blanc HC / HP | Rouge HC / HP |
|---|---|---|---|
| 1er août 2025 | 0,1232 / 0,1494 | 0,1391 / 0,1730 | 0,1460 / 0,6468 |
| 1er février 2026 | 0,1325 / 0,1612 | 0,1499 / 0,1871 | 0,1575 / 0,7060 |
| 1er août 2026 | 0,1356 / 0,1654 | 0,1536 / 0,1921 | 0,1615 / 0,7295 |

Vérifie-les sur ta facture : il n'existe pas de source ouverte lisible par machine pour la grille Tempo (le jeu de données CRE sur data.gouv.fr ne couvre que Base et HP/HC).

**Quand EDF change ses prix** : Configurer → saisir les 6 nouveaux prix **et leur date d'entrée en vigueur** (possible à l'avance). L'ancienne grille est conservée : le coût des jours passés ne change pas, et les capteurs de prix basculent seuls à minuit le jour J. Saisir la date d'une période existante la remplace (correction rétroactive : le coût est recalculé au redémarrage de l'intégration).

## Notification de la veille

```yaml
alias: Tempo - couleur de demain
triggers:
  - trigger: state
    entity_id: sensor.edf_tempo_couleur_demain
    from: unknown
actions:
  - action: notify.mobile_app_TON_TELEPHONE
    data:
      title: "Tempo demain"
      message: >-
        {{ state_attr('sensor.edf_tempo_couleur_demain', 'emoji') }}
        {{ states('sensor.edf_tempo_couleur_demain') }}.
        Jours rouges restants : {{ states('sensor.edf_tempo_jours_rouges_restants') }}
```

Pour ne recevoir l'alerte que les jours rouges, ajouter la condition `{{ is_state_attr('sensor.edf_tempo_couleur_demain', 'color', 'red') }}`.

## Widgets

Couleurs du jour et de demain (nécessite [Mushroom](https://github.com/piitaya/lovelace-mushroom) via HACS) :

```yaml
type: horizontal-stack
cards:
  - type: custom:mushroom-template-card
    primary: Aujourd'hui
    secondary: "{{ states('sensor.edf_tempo_couleur_aujourd_hui') }}"
    icon: mdi:flash
    icon_color: >
      {{ {'blue':'blue','white':'grey','red':'red'}.get(state_attr('sensor.edf_tempo_couleur_aujourd_hui','color'), 'disabled') }}
  - type: custom:mushroom-template-card
    primary: Demain
    secondary: "{{ states('sensor.edf_tempo_couleur_demain') }}"
    icon: mdi:flash
    icon_color: >
      {{ {'blue':'blue','white':'grey','red':'red'}.get(state_attr('sensor.edf_tempo_couleur_demain','color'), 'disabled') }}
```

Jours restants :

```yaml
type: entities
title: Jours Tempo restants
entities:
  - sensor.edf_tempo_jours_bleus_restants
  - sensor.edf_tempo_jours_blancs_restants
  - sensor.edf_tempo_jours_rouges_restants
```

## Données stockées

- **Calendrier des couleurs** : `/config/.storage/tempo_edf.<entry_id>` (à l'abri des purges du recorder, inclus dans les sauvegardes).
- **Prix et jours restants** : statistiques long terme du recorder.
- **Courbe de charge Enedis** : `/config/.storage/tempo_edf.enedis_<entry_id>` (une valeur par heure), à partir de laquelle les statistiques sont recalculées si les tarifs ou les couleurs changent.

## Enedis : consommation par couleur dans la section Énergie

L'intégration importe ta **courbe de charge** (30 min) via la passerelle gratuite et open-source **Conso API** (`conso.boris.sh`, qui relaie l'API Enedis « Mesure synchrone V2 »). Chaque heure est affectée à son cadran (couleur du jour × HC/HP) et publiée comme **statistiques externes** : 6 séries de consommation (kWh) et 6 séries de coût (€, avec la grille en vigueur *ce jour-là*).

### Mise en route

1. Dans ton espace Enedis, active l'enregistrement de la **courbe de charge**.
2. Sur <https://conso.boris.sh>, donne ton consentement et récupère le **token**.
3. Ton **PRM** (14 chiffres) est sur le compteur ou dans ton espace Enedis.
4. Intégration → **Configurer** : token, PRM et « Jours d'historique Enedis à importer » (30 par défaut). L'import démarre tout seul à la validation.
5. Suis `sensor.edf_tempo_enedis_derniere_donnee` : son attribut `status` indique « À jour » ou ce qui reste à importer.

### Ajouter les 6 séries dans Énergie

Paramètres → Tableaux de bord → Énergie → **Consommation du réseau** → Ajouter une source. Pour chacun des 6 cadrans :

- consommation : `Tempo Bleu HC (consommation)`, `Tempo Bleu HP (consommation)`, … `Tempo Rouge HP (consommation)` ;
- coût : « Utiliser une entité suivant le coût total » → la série `... (coût)` correspondante.

Les données sont **horaires** (c'est la finesse maximale des statistiques de Home Assistant) et arrivent avec un jour de décalage.

### Budget d'appels (Conso API : 5 requêtes/s et 10 000/h partagés, 1 requête/jour conseillée)

| Situation | Requêtes |
|---|---|
| Régime normal | **1 par jour** (la veille), à un créneau fixe mais non rond dérivé de ton PRM, entre 08:15 et 09:59 |
| Données pas encore prêtes | 1 seul réessai entre 14:00 et 14:59 |
| Rattrapage de l'historique | tranches de 6 jours, **6 requêtes maximum** par synchronisation, le reste les jours suivants |
| Erreur (token, réseau, serveur) | arrêt immédiat, aucune boucle de nouvelles tentatives |
| Garde-fou interne | 10 requêtes par heure au plus ; synchro manuelle limitée à 1 fois par 30 min |

Pour un historique de plus de quelques semaines, `conso.boris.sh` recommande son extension « Conso downloader » plutôt que l'API.

### Services (Outils de développement → Actions)

- `tempo_edf.enedis_sync` : lance une synchronisation tout de suite (utile pour tester ; compte dans le budget d'appels).
- `tempo_edf.enedis_fetch` : diagnostic qui renvoie un résumé brut d'une réponse Enedis (`kwh_par_jour` pour la courbe de charge, `index_calendriers` pour les index).

### Format validé sur données réelles

Courbe de charge : puissance moyenne en **W** par pas de 30 min, horodatage = **fin** d'intervalle (heure de Paris), `dateFin` exclue. La somme par jour tombe exactement sur `consommation_quotidienne` (34,658 kWh le 6 nov. 2026 dans le cas testé). `index_consommation` donne les 6 cadrans Tempo (`IDX_EAS_F1` à `F6`) : il pourra servir de contrôle.

## Limites connues

- **Non testé sur une instance Home Assistant réelle** : la synchronisation est validée par une simulation (faux Home Assistant + faux client Enedis), pas en production. À valider au premier lancement ; vérifie en particulier que l'écran Énergie accepte les séries de coût importées. Les logs sont filtrables avec `docker logs <conteneur> 2>&1 | grep -i tempo_edf`.
- Pas de ré-authentification guidée : si le secret RTE change, supprimer puis recréer l'intégration (l'historique est rattrapé automatiquement).
- Les quotas de saison viennent de `tempo.json` (Jour Tempo) et sont mémorisés ; sans cette source, les valeurs par défaut 300 / 43 / 22 de `const.py` (`SEASON_TOTALS`) s'appliquent.
- Les tarifs sont saisis à la main (voir plus haut).

## Crédits

Couleurs Tempo : RTE, via [Jour Tempo](https://jourtempo.fr). Consommation : Enedis, via [Conso API](https://conso.boris.sh).
