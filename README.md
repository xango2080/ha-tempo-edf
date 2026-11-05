# EDF Tempo pour Home Assistant

Récupère le calendrier Tempo depuis l'API officielle RTE, conserve **tout l'historique** sur disque et expose :

| Entité | Contenu |
|---|---|
| `sensor.edf_tempo_couleur_aujourd_hui` / `..._demain` | Bleu / Blanc / Rouge (`unknown` tant que RTE n'a pas publié J+1). Attributs : `color`, `emoji`, `color_hex`, `date` |
| `sensor.edf_tempo_tarif_actuel` | ex. `Bleu HP` (attributs `period`, `is_hc`, `is_hp`) |
| `sensor.edf_tempo_prix_actuel` | prix €/kWh en cours (statistiques long terme conservées) |
| `sensor.edf_tempo_prix_<couleur>_<hc/hp>` | les 6 tarifs fixes |
| `sensor.edf_tempo_saison` | jours bleus/blancs/rouges utilisés et restants |
| `calendar.edf_tempo_calendrier` | un évènement par jour, historique consultable |

Le jour Tempo change à 06:00, les heures creuses vont de 22:00 à 06:00.

## Obtenir la clé RTE (ID client + ID secret)

1. Créer un compte sur <https://data.rte-france.com>.
2. Dans le catalogue d'API, ouvrir **Tempo Like Supply Contract** et cliquer sur **S'abonner** (ou « Subscribe »).
3. Créer une **application** (nom et description libres) et la rattacher à cet abonnement. **Sans l'abonnement, RTE répond 403.**
4. Sur la page de l'application, recopier l'**ID client** et l'**ID secret**.
   Ne pas utiliser le bouton « Copier en base 64 » : c'est `id:secret` encodé, l'intégration veut les deux valeurs séparées.
5. Les coller dans Home Assistant à l'ajout de l'intégration. Le formulaire teste le token **et** l'accès à l'API Tempo.

## Historique des saisons passées

Dans Configurer, « Saisons d'historique à récupérer » (3 par défaut, 12 max). L'import se fait en tâche de fond, une requête par saison (1er sept. au 31 août), et sa progression est sauvegardée : après un redémarrage ou une erreur réseau, il reprend là où il s'est arrêté. Pour en récupérer davantage, augmente simplement le nombre.
Les jours importés apparaissent dans `calendar.edf_tempo_calendrier`. Les compteurs `sensor.edf_tempo_saison` ne concernent que la saison en cours.

## Installation

1. Copier `custom_components/tempo_edf/` dans `/config/custom_components/` (ou ajouter ce dépôt comme dépôt personnalisé HACS).
2. Redémarrer Home Assistant.
3. Paramètres → Appareils et services → Ajouter une intégration → **EDF Tempo**, puis saisir l'ID client et l'ID secret RTE.
4. Sur l'intégration → Configurer : saisir les 6 tarifs TTC (grille EDF) le jour où ils entrent en vigueur (le capteur change à l'enregistrement, l'historique du tableau Énergie garde l'ancien prix).
   Il n'existe pas de source ouverte lisible par machine pour la grille Tempo : le jeu de données CRE sur data.gouv.fr ne couvre que Base et HP/HC.

## Où sont stockées les données ?

- Calendrier : `/config/.storage/tempo_edf.<entry_id>` (à l'abri des purges du recorder, inclus dans les sauvegardes).
- Prix : statistiques long terme du recorder (capteurs en `state_class: measurement`).

## Notification J+1

```yaml
alias: Tempo - couleur de demain
triggers:
  - trigger: state
    entity_id: sensor.edf_tempo_couleur_demain
    from: unknown
conditions: []
actions:
  - action: notify.mobile_app_TON_TELEPHONE
    data:
      title: "Tempo demain"
      message: "{{ state_attr('sensor.edf_tempo_couleur_demain','emoji') }} {{ states('sensor.edf_tempo_couleur_demain') }}"
```

## Widget J / J+1 (Mushroom)

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

## Limites connues

- Non testé contre l'API RTE réelle ni contre une instance HA : à valider au premier lancement (voir les logs `custom_components.tempo_edf`).
- Pas de ré-authentification guidée : si le secret RTE change, supprimer puis recréer l'intégration (l'historique est lié à l'entrée et repart de la saison en cours, rattrapée automatiquement via l'API).
- Totaux de saison (300/43/22) dans `const.py`.
