"""Alerte logement : un cycle de vérification (lancé toutes les 15 min par GitHub Actions)."""

import argparse
import json
import logging
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

import notifier
import scraper

DOSSIER = Path(__file__).resolve().parent
FICHIER_ETAT = DOSSIER / "seen.json"
RETENTION_JOURS = 90

log = logging.getLogger("alerte")


def maintenant() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def charger_etat() -> dict:
    if FICHIER_ETAT.exists():
        try:
            etat = json.loads(FICHIER_ETAT.read_text(encoding="utf-8"))
            etat.setdefault("vues", {})
            etat.setdefault("derniere_alerte_technique", None)
            return etat
        except (json.JSONDecodeError, OSError):
            log.warning("seen.json illisible, on repart d'un état vide")
    return {"vues": {}, "derniere_alerte_technique": None}


def sauver_etat(etat: dict) -> None:
    limite = maintenant() - timedelta(days=RETENTION_JOURS)
    etat["vues"] = {
        cle: date for cle, date in etat["vues"].items() if datetime.fromisoformat(date) >= limite
    }
    tmp = FICHIER_ETAT.with_suffix(".tmp")
    tmp.write_text(json.dumps(etat, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, FICHIER_ETAT)


def alerte_technique(etat: dict, message: str, dry_run: bool) -> None:
    """Mail d'alerte technique, au maximum une fois par 24 h."""
    derniere = etat.get("derniere_alerte_technique")
    if derniere and maintenant() - datetime.fromisoformat(derniere) < timedelta(hours=24):
        return
    if dry_run:
        log.info("[dry-run] Alerte technique : %s", message)
        return
    try:
        notifier.envoyer("⚠️ AlerteLogement : problème de récupération", message)
        etat["derniere_alerte_technique"] = maintenant().isoformat()
        sauver_etat(etat)
    except (smtplib.SMTPException, OSError) as e:
        log.error("Échec d'envoi de l'alerte technique : %s", e)


def cycle(prix_min: float, prix_max: float, dry_run: bool, init_silencieux: bool) -> int:
    etat = charger_etat()

    try:
        annonces, pages = scraper.recuperer_annonces()
    except requests.RequestException as e:
        # Site injoignable : on ne fait pas échouer le workflow, on retentera au prochain cycle
        log.warning("Site injoignable : %s", e)
        return 0

    if not annonces:
        log.warning("0 annonce trouvée sur %d page(s) : structure du site modifiée ou blocage ?", pages)
        alerte_technique(
            etat,
            "Le script n'a trouvé aucune annonce sur Frances Immobilier.\n"
            "Le site a peut-être changé de structure ou bloque les requêtes de GitHub Actions.\n"
            "Consulte les logs dans l'onglet Actions du dépôt.",
            dry_run,
        )
        return 0

    dans_fourchette = [
        a for a in annonces if a.est_logement and a.prix is not None and prix_min <= a.prix <= prix_max and not a.louee
    ]
    nouvelles = sorted(
        (a for a in dans_fourchette if a.cle not in etat["vues"]), key=lambda a: a.prix
    )
    log.info(
        "%d page(s), %d annonce(s), %d entre %g et %g €, %d nouvelle(s)",
        pages, len(annonces), len(dans_fourchette), prix_min, prix_max, len(nouvelles),
    )

    if init_silencieux:
        a_marquer = annonces
    elif nouvelles:
        for a in nouvelles:
            log.info("  NOUVEAU %s € | %s %s | %s", a.prix, a.type_bien, a.ville, a.url)
        if dry_run:
            log.info("[dry-run] Mail non envoyé, seen.json non modifié")
            return 0
        notifier.envoyer_annonces(nouvelles)
        log.info("Mail envoyé pour %d annonce(s)", len(nouvelles))
        a_marquer = nouvelles
    else:
        return 0

    if dry_run:
        return 0
    horodatage = maintenant().isoformat()
    for a in a_marquer:
        etat["vues"].setdefault(a.cle, horodatage)
    sauver_etat(etat)
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    load_dotenv(DOSSIER / ".env")

    parser = argparse.ArgumentParser(description="Alerte logement Frances Immobilier")
    parser.add_argument("--dry-run", action="store_true", help="affiche sans envoyer ni sauvegarder")
    parser.add_argument("--test-mail", action="store_true", help="envoie un mail de test")
    parser.add_argument("--init-silencieux", action="store_true", help="marque tout comme vu sans mail")
    args = parser.parse_args()

    prix_min = float(os.environ.get("PRIX_MIN") or 300)
    prix_max = float(os.environ.get("PRIX_MAX") or 520)

    try:
        if args.test_mail:
            notifier.envoyer("✅ AlerteLogement : mail de test", "La configuration SMTP fonctionne.")
            log.info("Mail de test envoyé")
            return 0
        return cycle(prix_min, prix_max, args.dry_run, args.init_silencieux)
    except notifier.ConfigManquante as e:
        log.error("%s", e)
        return 2
    except smtplib.SMTPAuthenticationError:
        log.error("Authentification SMTP refusée : vérifie SMTP_USER / SMTP_PASSWORD (mot de passe d'application)")
        return 3
    except (smtplib.SMTPException, OSError) as e:
        log.error("Échec d'envoi du mail : %s", e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
