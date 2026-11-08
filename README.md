# EDF Tempo pour Home Assistant

Intégration personnalisée qui récupère les **couleurs Tempo** (bleu, blanc, rouge), **garde tout l'historique** sur disque et expose des capteurs prêts pour tes tableaux de bord, tes automatisations et la section Énergie.

- **Aucun compte requis** : source gratuite [Jour Tempo](https://jourtempo.fr/api/) (couleurs publiées par RTE). L'API officielle RTE est facultative.
- **Historique depuis 2014** importé en une requête, conservé hors des purges du recorder.
- **Résilient** : si une source tombe, les couleurs déjà reçues restent disponibles.

## Entités

| Entité | Contenu |
|---|---|
| `sensor.edf_tempo_couleur_aujourd_hui` | Bleu / Blanc / Rouge. Attributs : `color` (blue/white/red), `emoji`, `color_hex`, `date` |
| `sensor.edf_tempo_couleur_demain` | idem ; `unknown` tant que la couleur de demain n'est pas annoncée (vers 11 h) |
| `sensor.edf_tempo_tarif_actuel` | ex. `Bleu HP` (attributs `period`, `is_hc`, `is_hp`) |
| `sensor.edf_tempo_prix_actuel` | prix €/kWh en cours |
| `sensor.edf_tempo_prix_<couleur>_<hc/hp>` | les 6 tarifs fixes (€/kWh) |
| `sensor.edf_tempo_jours_bleus_restants`, `..._blancs_...`, `..._rouges_...` | jours restants de la saison par couleur (quotas lus dans `tempo.json`, 300 / 43 / 22 par défaut). Demain est déduit dès son annonce. Attributs `quota`, `used`, `history_complete`. `unknown` si l'historique de la saison est incomplet |
| `sensor.edf_tempo_saison` | saison en cours (ex. `2026-2027`), avec jours utilisés/restants en attributs |
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

- **Fréquence** : au plus **une requête par heure**, et seulement tant qu'une couleur du jour ou de demain manque. Jour Tempo recommande un appel toutes les 30 minutes, jamais moins de 10.
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

## Tarifs

Il n'existe pas de source ouverte lisible par machine pour la grille Tempo (le jeu de données de la CRE sur data.gouv.fr ne couvre que Base et HP/HC). Les 6 prix sont donc saisis à la main dans **Configurer**.

Saisis-les **le jour où un nouveau tarif entre en vigueur** : les capteurs changent à l'enregistrement, et dans la section Énergie, avec « Utiliser une entité avec le prix actuel », l'historique garde l'ancien prix.

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

## Enedis (consommation) : étape 1, expérimental

Cette partie ne fait que lire les données ; elle n'alimente pas encore la section Énergie, et une panne d'Enedis n'affecte pas les couleurs.

Enedis n'ouvre son API qu'aux entreprises. On passe par la passerelle gratuite et open-source **Conso API** (`conso.boris.sh`), qui expose l'API Enedis « Mesure synchrone V2 ». L'ancienne API (V5) a été coupée mi-octobre 2026 : seuls les nouveaux types sont utilisés.

1. Dans ton espace Enedis, active l'enregistrement de la **courbe de charge** (sans elle, pas de ventilation par couleur et HP/HC).
2. Sur <https://conso.boris.sh>, donne ton consentement et récupère le **token**.
3. Ton **PRM** (14 chiffres) est sur le compteur ou dans ton espace Enedis.
4. Intégration → **Configurer** : renseigner le token et le PRM.

Les données du jour J ne sont disponibles que le lendemain, vers 8 h. Ne fais pas d'appels répétés : un abus peut mener à un blocage d'IP.

### Valider le format réel (important)

Le format de réponse est celui de la documentation, sans données réelles observées. Utilise **Outils de développement → Actions → `tempo_edf.enedis_fetch`** (type `courbe_de_charge_consommation`, 2 jours) et vérifie : l'unité (`meta`), et si le point `d` est le début ou la fin de l'intervalle (`first`). Teste aussi `index_consommation` : s'il contient un index par tarif Tempo, la ventilation sera plus simple et plus fiable.

Hypothèses à confirmer dans `enedis_parse.py` : `v` en W pour la courbe de charge et en Wh pour le quotidien, `d` = fin d'intervalle (`LOAD_CURVE_TS_IS_END`).

## Limites connues

- **Non testé sur une instance Home Assistant réelle ni contre les API en production** : à valider au premier lancement. Les logs sont filtrables avec `docker logs <conteneur> 2>&1 | grep -i tempo_edf`.
- Pas de ré-authentification guidée : si le secret RTE change, supprimer puis recréer l'intégration (l'historique est rattrapé automatiquement).
- Les quotas de saison viennent de `tempo.json` (Jour Tempo) et sont mémorisés ; sans cette source, les valeurs par défaut 300 / 43 / 22 de `const.py` (`SEASON_TOTALS`) s'appliquent.
- Les tarifs sont saisis à la main (voir plus haut).

## Crédits

Couleurs Tempo : RTE, via [Jour Tempo](https://jourtempo.fr). Consommation : Enedis, via [Conso API](https://conso.boris.sh).
