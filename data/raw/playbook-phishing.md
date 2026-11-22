# Guide d'investigation des attaques par hameçonnage (Phishing)

Ce document résume les bonnes pratiques et les étapes opérationnelles issues du cadre de sécurité **Microsoft Security Adoption Framework (SAF)** pour mener à bien une enquête suite à une attaque par phishing.

---

## 1. Prérequis et préparation initiale
Avant qu'un incident ne survienne, les équipes de sécurité doivent s'assurer que les éléments suivants sont configurés :
* **Informations de compte :** Disposer d'au moins un identifiant (nom d'utilisateur, UPN ou e-mail) pour corréler les connexions et l'activité de messagerie.
* **Audit Microsoft 365 :** Activer l'audit des boîtes aux lettres à l'échelle de l'organisation et s'assurer que les journaux de suivi des messages (*Message trace*) ainsi que les journaux d'audit unifiés sont accessibles.
* **Journaux d'identité :** Mettre en place l'exportation des journaux de connexion et d'audit Microsoft Entra vers un stockage à long terme (comme Microsoft Sentinel ou un SIEM tiers), car leur durée de conservation native est limitée.
* **Rôles et autorisations :** Attribuer aux enquêteurs des accès en lecture seule adaptés (rôle *Security Reader* minimum) pour préserver la sécurité des données.
* **Visibilité des terminaux :** Utiliser des solutions comme *Microsoft Defender for Endpoint* pour valider l'interaction des utilisateurs avec les charges malveillantes.
* **Outils :** Disposer d'un environnement d'administration prêt à exécuter les modules PowerShell nécessaires (Microsoft Graph, Exchange Online, etc.).

---

## 2. Flux de travail de l'enquête
L'investigation suit une progression structurée en cinq étapes majeures :
1. **Identification :** Repérer et confirmer l'e-mail de phishing concerné.
2. **Périmètre :** Définir la portée de l'attaque et recenser les utilisateurs touchés.
3. **Interaction :** Analyser le comportement des utilisateurs ciblés et l'éventuelle exposition de leurs identifiants.
4. **Conséquences :** Examiner les activités secondaires ou en aval (mouvements latéraux, exfiltration).
5. **Remédiation :** Neutraliser la menace et mettre en place des mesures de prévention contre la récidive.

---

## 3. Étapes clés de l'investigation

* **Étape 1 - Caractérisation du message :** Récupérer l'e-mail suspect, extraire son identifiant unique (*Message-ID*) depuis les en-têtes, et utiliser les outils de traçage pour connaître le volume de réception et le statut de distribution.
* **Étape 2 - Cartographie des destinataires :** Identifier l'ensemble des utilisateurs ayant reçu le message et vérifier si les filtres de sécurité ont été contournés ou si d'autres variantes de la campagne circulent.
* **Étape 3 - Analyse des actions utilisateur :** Vérifier si les cibles ont ouvert le message, cliqué sur des liens, téléchargé des pièces jointes ou renseigné des informations sensibles. Croiser ces observations avec les journaux de connexion.
* **Étape 4 - Recherche d'activités post-compromission :** En cas de vol d'identifiants, auditer les connexions suspectes, les attributions de consentements OAuth anormaux ou les modifications de règles de messagerie. Si une pièce jointe a été exécutée, analyser l'activité sur les terminaux.
* **Étape 5 - Confinement et remédiation :** Purger les e-mails malveillants des boîtes aux lettres, réinitialiser les comptes compromis, révoquer les sessions actives et bloquer les indicateurs de compromission (expéditeurs, domaines, liens).
* **Étape 6 - Rétablissement et amélioration :** Imposer l'authentification multifacteur (MFA), contrôler les paramètres de transfert de courrier et actualiser les règles de détection ainsi que les playbooks internes.
