"""Récupération et parsing des annonces de location Frances Immobilier."""

import logging
import re
import time
from dataclasses import dataclass, asdict

import requests
from bs4 import BeautifulSoup

URL_LISTE = "https://www.frances-immobilier.com/fr/annonces/louer-p-r70-5-{page}.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}
PAGES_MAX = 20
# Types de biens ignorés (on ne veut que des logements)
TYPES_EXCLUS = ("parking", "garage", "box", "cave", "bureau", "local", "terrain", "entrepôt")
PAUSE_SECONDES = 1.5

log = logging.getLogger(__name__)

RE_CLE = re.compile(r"cle=(\d+)")
RE_PRIX = re.compile(r"[\d.,]+")
# Dans le <script> du bloc : if(JsConfig.Bandeau.Vendu && '1'=='1') => bien loué/vendu
RE_LOUE = re.compile(r"JsConfig\.Bandeau\.Vendu\s*&&\s*'(\d)'\s*==\s*'1'")


@dataclass
class Annonce:
    cle: str
    prix: float | None
    titre: str
    ville: str
    type_bien: str
    url: str
    louee: bool

    @property
    def est_logement(self) -> bool:
        t = self.type_bien.lower()
        return not any(mot in t for mot in TYPES_EXCLUS)

    def to_dict(self):
        return asdict(self)


def parse_prix(texte: str) -> float | None:
    """'Loyer : 2,474.00 €* CC' -> 2474.0 (virgule = séparateur de milliers)."""
    m = RE_PRIX.search(texte.split(":", 1)[-1])
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _texte(bloc, selecteur: str) -> str:
    el = bloc.select_one(selecteur)
    return el.get_text(" ", strip=True) if el else ""


def parse_page(html: bytes | str) -> list[Annonce]:
    if isinstance(html, bytes):
        # Page en Windows-1252 : la détection auto de BeautifulSoup se trompe (cp1250)
        html = html.decode("cp1252", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    annonces = []
    for bloc in soup.select("div.liste-bien-container"):
        lien = bloc.select_one('a[href*="detail.htm?cle="]')
        if not lien:
            continue
        m = RE_CLE.search(lien["href"])
        if not m:
            continue
        cle = m.group(1)

        desc = bloc.select_one("div.extrait-desc")
        titre = ""
        if desc:
            # Le titre est la première ligne, avant le premier <br>
            titre = next(iter(desc.stripped_strings), "")

        scripts = " ".join(s.get_text() for s in bloc.find_all("script"))
        m_loue = RE_LOUE.search(scripts)

        annonces.append(
            Annonce(
                cle=cle,
                prix=parse_prix(_texte(bloc, "div.liste-bien-price")),
                titre=titre,
                ville=_texte(bloc, ".liste-bien-ville").title(),
                type_bien=_texte(bloc, ".liste-bien-type"),
                url=f"https://www.frances-immobilier.com/fr/detail.htm?cle={cle}",
                louee=bool(m_loue and m_loue.group(1) == "1"),
            )
        )
    return annonces


def recuperer_annonces(session: requests.Session | None = None) -> tuple[list[Annonce], int]:
    """Parcourt les pages jusqu'à ce qu'une page n'apporte plus rien de nouveau.

    Retourne (annonces, nombre de pages lues). Lève requests.RequestException si le site est injoignable.
    """
    session = session or requests.Session()
    session.headers.update(HEADERS)
    toutes: dict[str, Annonce] = {}
    pages_lues = 0

    for page in range(1, PAGES_MAX + 1):
        if page > 1:
            time.sleep(PAUSE_SECONDES)
        resp = session.get(URL_LISTE.format(page=page), timeout=20)
        resp.raise_for_status()
        pages_lues += 1

        nouvelles = [a for a in parse_page(resp.content) if a.cle not in toutes]
        log.debug("Page %d : %d annonce(s) nouvelle(s)", page, len(nouvelles))
        if not nouvelles:
            break
        for a in nouvelles:
            toutes[a.cle] = a

    return list(toutes.values()), pages_lues
