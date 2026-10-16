"""Envoi des e-mails via SMTP."""

import os
import smtplib
import ssl
from email.message import EmailMessage
from html import escape


class ConfigManquante(Exception):
    pass


def _config():
    manquantes = [v for v in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO") if not os.environ.get(v)]
    if manquantes:
        raise ConfigManquante(f"Variable(s) d'environnement manquante(s) : {', '.join(manquantes)}")
    return {
        "host": os.environ.get("SMTP_HOST") or "smtp.gmail.com",
        "port": int(os.environ.get("SMTP_PORT") or 587),
        "user": os.environ["SMTP_USER"],
        # Google affiche le mot de passe d'application par blocs de 4 : on retire les espaces
        "password": "".join(os.environ["SMTP_PASSWORD"].split()),
        # Plusieurs destinataires possibles, séparés par des virgules
        "to": [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()],
    }


def envoyer(sujet: str, texte: str, html: str | None = None) -> None:
    cfg = _config()
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = cfg["user"]
    msg["To"] = ", ".join(cfg["to"])
    msg.set_content(texte)
    if html:
        msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)


def _prix(p: float) -> str:
    return f"{p:,.0f} €".replace(",", " ")


def envoyer_annonces(annonces) -> None:
    n = len(annonces)
    prix = sorted(a.prix for a in annonces)
    fourchette = _prix(prix[0]) if prix[0] == prix[-1] else f"{_prix(prix[0])} – {_prix(prix[-1])}"
    sujet = f"🏠 {n} nouveau{'x' if n > 1 else ''} logement{'s' if n > 1 else ''} à {fourchette}"

    lignes = [f"- {_prix(a.prix)} | {a.type_bien} {a.ville} | {a.titre}\n  {a.url}" for a in annonces]
    texte = "Nouvelles annonces Frances Immobilier :\n\n" + "\n\n".join(lignes)

    items = "".join(
        f'<li style="margin-bottom:12px"><b>{escape(_prix(a.prix))}</b> — '
        f"{escape(a.type_bien)} {escape(a.ville)}<br>{escape(a.titre)}<br>"
        f'<a href="{escape(a.url)}">Voir l\'annonce</a></li>'
        for a in annonces
    )
    html = f"<p>Nouvelles annonces Frances Immobilier :</p><ul>{items}</ul>"
    envoyer(sujet, texte, html)
