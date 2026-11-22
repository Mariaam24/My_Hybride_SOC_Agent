# Enquête sur les attaques par pulvérisation de mots de passe (Password Spray)

Ce guide fait partie du cadre d'adoption de la sécurité Microsoft (**Microsoft Security Adoption Framework - SAF**) pour les équipes **SecOps** (Security Operations). Il détaille comment identifier, analyser et contrer une attaque par pulvérisation de mots de passe.

---

## 1. Prérequis

Avant de lancer une investigation, assurez-vous que la journalisation et les alertes sont correctement configurées :

* **Journalisation AD FS (Active Directory Federation Services) :**
  * Passez le niveau d'audit en mode détaillé (`Verbose`) via PowerShell :
    ```powershell
    Set-AdfsProperties -AuditLevel Verbose
    ```
  * Activez les audits de sécurité locaux (*Local Security Policy* > *Generate security audits* pour le compte de service AD FS) et activez la sous-catégorie `"Application Generated"` via `auditpol.exe`.
  * Cochez les audits de réussite (*Success audits*) et d'échec (*Failure audits*) dans les propriétés du service de fédération.
* **Microsoft Entra Connect Health pour AD FS :** Installez l'agent pour obtenir une visibilité sur l'utilisation, les performances et les rapports d'adresses IP à risque (*Risky IP*).
* **Alertes et intégration SIEM :**
  * Configurez le classeur *ADFS Risky IP Report* dans Azure Monitor pour détecter les seuils d'échecs de connexion.
  * Intégrez vos journaux dans un SIEM (Microsoft Sentinel, Splunk ou via l'API Microsoft Graph Security et Microsoft Defender for Cloud Apps).

---

## 2. Déclencheurs et indicateurs d'attaque

Une investigation débute généralement suite à l'un des événements suivants :

* Alerte provenant de **Microsoft Entra ID Protection** (détection de Password Spray ou IP à risque).
* Pic anormal d'échecs de connexion dans les journaux (notamment les **Event ID 411** ou **342** pour des identifiants incorrects, et **516** pour un verrouillage extranet).
* Connexion depuis un emplacement inhabituel ou notifications d'authentification multifacteur (MFA) inattendues signalées par un utilisateur.
* **Attaques lentes ("Low and slow") :** Tentatives sous les seuils d'alerte classiques, repérables par des échecs suivant l'ordre de la liste d'adresses globale (GAL), des intervalles de temps très réguliers ou des attributs répétitifs (User-Agent, bloc IP).

---

## 3. Étapes d'investigation

### A. Découverte de l'environnement
1. **Identifier le type d'authentification du domaine** (fédérée ou gérée) via PowerShell :
   ```powershell
   Connect-MgGraph -Scopes "Domain.Read.All"
   Get-MgDomain -DomainId "contoso.com"
