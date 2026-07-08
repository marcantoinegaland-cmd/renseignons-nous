#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Générateur statique de Renseignons-nous.
Va chercher les articles publiés sur WordPress.com (back-office) et produit :
  - index.html            (accueil, liste des articles)
  - article/<slug>/index.html  (une page par article, avec SEO complet)
  - sitemap.xml, robots.txt
Aucune dépendance externe (stdlib uniquement). Testé localement + lancé par GitHub Actions.
"""
import html
import json
import os
import re
import sys
import urllib.request

# ----------------------------------------------------------------------------
WP_SITE   = os.environ.get("WP_SITE", "renseignonsnous.wordpress.com")
BASE_URL  = os.environ.get("BASE_URL", "https://renseignonsnous.fr")   # domaine (URLs absolues SEO)
BASE_PATH = os.environ.get("BASE_PATH", "/")   # (liens internes désormais relatifs — conservé pour compat)
SITE_NAME = "Renseignons-nous"
AUTHOR    = "Marc-Antoine Galand"
BLOG_ID   = os.environ.get("BLOG_ID", "256008490")            # newsletter WordPress/Jetpack
CONTACT   = os.environ.get("CONTACT_EMAIL", "renseignousnous@gmail.com")
OUT       = os.path.dirname(os.path.abspath(__file__))

# Config optionnelle (analytics, vérification Search Console) via config.json
_cfg = {}
if os.path.exists(os.path.join(OUT, "config.json")):
    try:
        _cfg = json.load(open(os.path.join(OUT, "config.json"), encoding="utf-8"))
    except Exception:
        _cfg = {}
ANALYTICS = _cfg.get("analytics_html", "")            # snippet HTML injecté avant </body>
GSC       = _cfg.get("google_site_verification", "")  # jeton meta Google Search Console

MOIS = ["", "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
CATS = {"renseignement": "Renseignement", "defense": "Défense", "geopolitique": "Géopolitique"}

# ----------------------------------------------------------------------------
def fetch_posts():
    url = f"https://public-api.wordpress.com/wp/v2/sites/{WP_SITE}/posts?per_page=100&_embed"
    req = urllib.request.Request(url, headers={"User-Agent": "renseignons-nous-builder"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def txt(s):
    """HTML entities -> texte brut lisible."""
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()

def attr(s):
    """Échappe pour un attribut / meta."""
    return html.escape(txt(s), quote=True)

def clip(s, n=155):
    s = re.sub(r"\s+", " ", s).strip()
    return (s[: n - 1].rstrip() + "…") if len(s) > n else s

def date_fr(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{d} {MOIS[mo]} {y}"

def post_fields(p):
    emb = p.get("_embedded", {}) or {}
    fm = (emb.get("wp:featuredmedia") or [{}])
    img = fm[0].get("source_url") if fm and isinstance(fm[0], dict) else None
    if not img:
        img = p.get("jetpack_featured_media_url") or ""
    terms = [t for grp in (emb.get("wp:term") or []) for t in grp
             if isinstance(t, dict) and t.get("name") and t.get("name") != "Non classé"]
    label = terms[0]["name"] if terms else "Article"
    cat = next((t["slug"] for t in terms if t.get("slug") in CATS), "")
    return {
        "id": p.get("id"),
        "slug": p.get("slug") or f"article-{p.get('id')}",
        "title": txt(p.get("title", {}).get("rendered", "")) or "Sans titre",
        "excerpt": txt(p.get("excerpt", {}).get("rendered", "")),
        "content": p.get("content", {}).get("rendered", "") or "",
        "img": img,
        "label": label,
        "cat": cat,
        "date": p.get("date", ""),
        "modified": p.get("modified", p.get("date", "")),
        "date_fr": date_fr(p.get("date", "")),
    }

def lead_first_p(content):
    """Ajoute la classe lead au premier <p> (lettrine éditoriale)."""
    return re.sub(r"<p(?![^>]*class=)", '<p class="lead"', content, count=1)

# ----------------------------------------------------------------------------
CSS = open(os.path.join(OUT, "_style.css"), encoding="utf-8").read() \
      if os.path.exists(os.path.join(OUT, "_style.css")) else ""

def head(title, desc, canonical, img="", og_type="website", jsonld=None, published="", root=""):
    tags = [
        '<meta charset="UTF-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />',
        f'<title>{html.escape(title)}</title>',
        f'<meta name="description" content="{html.escape(desc)}" />',
        f'<link rel="canonical" href="{html.escape(canonical)}" />',
        f'<link rel="icon" href="{root}favicon.svg" type="image/svg+xml" />',
        '<meta name="robots" content="index, follow, max-image-preview:large" />',
    ]
    if GSC:
        tags.append(f'<meta name="google-site-verification" content="{html.escape(GSC)}" />')
    tags += [
        f'<meta property="og:site_name" content="{SITE_NAME}" />',
        f'<meta property="og:type" content="{og_type}" />',
        f'<meta property="og:title" content="{html.escape(title)}" />',
        f'<meta property="og:description" content="{html.escape(desc)}" />',
        f'<meta property="og:url" content="{html.escape(canonical)}" />',
        '<meta property="og:locale" content="fr_FR" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{html.escape(title)}" />',
        f'<meta name="twitter:description" content="{html.escape(desc)}" />',
    ]
    if img:
        tags.append(f'<meta property="og:image" content="{html.escape(img)}" />')
        tags.append(f'<meta name="twitter:image" content="{html.escape(img)}" />')
    if published:
        tags.append(f'<meta property="article:published_time" content="{html.escape(published)}" />')
    tags += [
        '<link rel="preconnect" href="https://fonts.googleapis.com" />',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />',
        '<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,700;1,8..60,400&display=swap" rel="stylesheet" />',
        f"<style>{CSS}</style>",
    ]
    if jsonld:
        tags.append('<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False) + "</script>")
    return "\n".join(tags)

def masthead(home, full=True):
    bar = f"""  <div class="mast-bar">
    <a href="{home if home else '#top'}" class="wordmark">Renseignons-nous</a>
    <nav class="mast-nav" aria-label="Rubriques">
      <a href="{home}#enquetes" data-cat-filter="renseignement">Renseignement</a>
      <a href="{home}#enquetes" data-cat-filter="defense">Défense</a>
      <a href="{home}#enquetes" data-cat-filter="geopolitique">Géopolitique</a>
      <a href="{home}#newsletter" class="mast-sub">S'abonner</a>
    </nav>
  </div>"""
    if not full:
        return f'<header class="masthead compact">\n{bar}\n</header>'
    return f"""<header class="masthead">
{bar}
  <div class="mast-lede">
    <p class="mast-eyebrow">Renseignement · Défense · Géopolitique</p>
    <h1 class="mast-title">Le monde du renseignement, <em>expliqué.</em></h1>
    <p class="mast-desc">Enquêtes longues, analyses sourcées et briefings — sans publicité, à partir de sources ouvertes.</p>
  </div>
</header>"""

def footer(home):
    return f"""<footer>
  <div class="ft">
    <div class="ft-inner">
      <div>
        <p class="ft-word">Renseignons-nous</p>
        <p class="ft-tag">Renseignement · Défense · Géopolitique</p>
      </div>
      <nav class="ft-links" aria-label="Pied de page">
        <a href="{home}#enquetes" data-cat-filter="renseignement">Renseignement</a>
        <a href="{home}#enquetes" data-cat-filter="defense">Défense</a>
        <a href="{home}#enquetes" data-cat-filter="geopolitique">Géopolitique</a>
        <a href="{home}a-propos/">À propos</a>
        <a href="{home}mentions-legales/">Mentions légales</a>
      </nav>
    </div>
  </div>
  <div class="ft-legal">© 2026 Renseignons-nous · Marc-Antoine Galand · Analyses à partir de sources ouvertes.</div>
</footer>"""

HOME_JS = """<script>
(function(){
  var btns = document.querySelectorAll('.filter-btn');
  btns.forEach(function(b){ b.addEventListener('click', function(){
    btns.forEach(function(x){ x.classList.remove('is-active'); });
    b.classList.add('is-active');
    var f = b.dataset.filter;
    document.querySelectorAll('.article-card').forEach(function(c){
      c.classList.toggle('is-hidden', !(f==='all' || c.dataset.cat===f));
    });
  }); });
})();
</script>"""

def card(f, root=""):
    href = f"{root}article/{f['slug']}/"
    media = (f'<div class="card-media"><img src="{attr(f["img"])}" alt="{attr(f["title"])}" loading="lazy"/></div>'
             if f["img"] else "")
    dek = f'<p class="card-dek">{html.escape(clip(f["excerpt"], 130))}</p>' if f["excerpt"] else ""
    return f"""      <a class="article-card" data-cat="{f['cat']}" href="{href}">
        {media}
        <div class="card-body">
          <div class="card-meta"><span class="tag">{html.escape(f['label'])}</span><p class="card-date">{f['date_fr']}</p></div>
          <h3 class="card-title">{html.escape(f['title'])}</h3>{dek}
        </div>
      </a>"""

# ----------------------------------------------------------------------------
def render_home(posts):
    cards = "\n\n".join(card(f) for f in posts)
    empty = "" if posts else '<p class="empty-state">Les premières enquêtes seront publiées prochainement.</p>'
    jsonld = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME,
              "url": BASE_URL + "/",
              "description": "Renseignement, défense et géopolitique — enquêtes et analyses sourcées."}
    h = head("Renseignons-nous — Renseignement, défense, géopolitique",
             "Le média de référence sur le renseignement, la défense et la géopolitique. Enquêtes longues et analyses sourcées, à partir de sources ouvertes.",
             BASE_URL + "/", og_type="website", jsonld=jsonld)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
{h}
</head>
<body id="top">
{masthead('')}
<main id="enquetes" class="wrap">
  <div class="sec-head">
    <h2 class="sec-title">Dernières enquêtes</h2>
    <div class="filters">
      <button class="filter-btn is-active" data-filter="all">Tous</button>
      <button class="filter-btn" data-filter="renseignement">Renseignement</button>
      <button class="filter-btn" data-filter="defense">Défense</button>
      <button class="filter-btn" data-filter="geopolitique">Géopolitique</button>
    </div>
  </div>
  <div id="grid">
{cards}
  </div>
  {empty}
</main>
<section id="newsletter" class="nl">
  <div class="nl-inner">
    <div>
      <p class="nl-eyebrow">Newsletter</p>
      <h2 class="nl-title">Chaque enquête, dans votre boîte mail.</h2>
      <p class="nl-desc">Une alerte par publication. Pas de spam, désabonnement en un clic.</p>
    </div>
    <form class="nl-form" action="https://subscribe.wordpress.com/" method="post" accept-charset="utf-8" target="_blank">
      <input type="email" name="email" required placeholder="votre@email.com" aria-label="Adresse e-mail" />
      <input type="hidden" name="action" value="subscribe" />
      <input type="hidden" name="blog_id" value="{BLOG_ID}" />
      <input type="hidden" name="source" value="{BASE_URL}/" />
      <input type="hidden" name="sub-type" value="renseignons-nous-site" />
      <input type="hidden" name="redirect_fragment" value="subscribe-blog" />
      <button type="submit">S'abonner</button>
    </form>
  </div>
</section>
{footer('')}
{HOME_JS}
{ANALYTICS}
</body>
</html>"""

def render_article(f):
    url = f"{BASE_URL}/article/{f['slug']}/"
    desc = clip(f["excerpt"] or txt(f["content"]), 155)
    jsonld = {
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": f["title"], "description": desc, "mainEntityOfPage": url,
        "datePublished": f["date"], "dateModified": f["modified"],
        "author": {"@type": "Person", "name": AUTHOR},
        "publisher": {"@type": "Organization", "name": SITE_NAME},
    }
    if f["img"]:
        jsonld["image"] = [f["img"]]
    h = head(f'{f["title"]} — {SITE_NAME}', desc, url, img=f["img"],
             og_type="article", jsonld=jsonld, published=f["date"], root="../../")
    hero = (f'<div class="article-hero"><img src="{attr(f["img"])}" alt="{attr(f["title"])}"/></div>'
            if f["img"] else "")
    dek = f'<p class="article-dek">{html.escape(f["excerpt"])}</p>' if f["excerpt"] else ""
    body = lead_first_p(f["content"])
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
{h}
</head>
<body>
{masthead("../../", full=False)}
<main class="article-page">
  <a class="article-back" href="../../">← Toutes les enquêtes</a>
  <div class="article-meta-top"><span class="tag">{html.escape(f['label'])}</span><span class="article-date">{f['date_fr']}</span></div>
  <h1 class="article-title">{html.escape(f['title'])}</h1>
  {dek}
  {hero}
  <div class="article-body">
{body}
    <div class="article-signature"><span class="sig-rule"></span><p class="sig-name">{AUTHOR}</p><p class="sig-pub">Renseignons-nous</p></div>
  </div>
</main>
{footer("../../")}
{ANALYTICS}
</body>
</html>"""

def render_page(slug, title, desc, body_html):
    url = f"{BASE_URL}/{slug}/"
    h = head(f"{title} — {SITE_NAME}", desc, url, og_type="website", root="../")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
{h}
</head>
<body>
{masthead("../", full=False)}
<main class="page">
  <h1 class="page-title">{html.escape(title)}</h1>
  <div class="page-body">
{body_html}
  </div>
</main>
{footer("../")}
{ANALYTICS}
</body>
</html>"""

ABOUT_HTML = f"""<p class="lead"><strong>Renseignons-nous</strong> est un média indépendant consacré au renseignement, à la défense et à la géopolitique.</p>
<p>La ligne est simple : prendre le temps d'expliquer. Là où l'actualité va vite et se contente souvent de l'écume, ce site publie des enquêtes longues et des analyses de fond, construites uniquement à partir de <strong>sources ouvertes</strong> — documents officiels, rapports parlementaires, données AIS et satellitaires, presse spécialisée, archives. Aucune information n'y est affirmée sans être sourcée et recoupée.</p>
<h2>Une exigence, pas une course</h2>
<p>Chaque enquête suit le rythme du fact-checking, non celui du flux. On préfère un dossier solide et documenté à dix brèves invérifiables. Pas de publicité, pas de contenu sponsorisé : la seule fidélité du site va au lecteur qui veut <em>comprendre</em>.</p>
<h2>Qui écrit</h2>
<p>Le site est édité et rédigé par <strong>{AUTHOR}</strong>, basé à Lyon. Pour toute question, contact ou signalement : <a href="mailto:{CONTACT}">{CONTACT}</a>.</p>"""

LEGAL_HTML = f"""<p class="lead">Conformément à la loi n° 2004-575 du 21 juin 2004 pour la confiance dans l'économie numérique, voici les informations légales relatives au site <strong>Renseignons-nous</strong>.</p>
<h2>Éditeur</h2>
<p>Le site Renseignons-nous est édité par <strong>{AUTHOR}</strong>, à titre individuel et non commercial (Lyon, France).<br/>
Directeur de la publication : {AUTHOR}.<br/>
Contact : <a href="mailto:{CONTACT}">{CONTACT}</a>.</p>
<h2>Hébergement</h2>
<p>Le site est hébergé par <strong>GitHub, Inc.</strong> (service GitHub Pages), 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, États-Unis.<br/>
Le back-office éditorial est fourni par <strong>Automattic Inc.</strong> (WordPress.com), 60 29th Street #343, San Francisco, CA 94110, États-Unis.</p>
<h2>Propriété intellectuelle</h2>
<p>Sauf mention contraire, l'ensemble des contenus (textes, analyses, mises en forme) est la propriété de l'éditeur. Toute reproduction intégrale sans autorisation est interdite ; les citations courtes sont autorisées sous réserve d'indiquer clairement la source et un lien vers l'article original. Les images proviennent de leurs auteurs ou ayants droit respectifs, créditées le cas échéant.</p>
<h2>Données personnelles</h2>
<p>Le site ne collecte aucune donnée personnelle à votre insu. Si vous vous inscrivez à la newsletter, votre adresse e-mail est traitée par WordPress.com / Automattic aux seules fins d'envoi des nouvelles publications. Vous pouvez vous désinscrire à tout moment via le lien présent dans chaque e-mail. Conformément au RGPD, vous disposez d'un droit d'accès, de rectification et de suppression de vos données en écrivant à <a href="mailto:{CONTACT}">{CONTACT}</a>.</p>"""

FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           '<rect width="64" height="64" rx="14" fill="#1e3ac9"/>'
           '<text x="32" y="45" font-family="Georgia, \'Source Serif 4\', serif" '
           'font-size="40" font-weight="700" fill="#fff" text-anchor="middle">R</text></svg>\n')

def sitemap(posts):
    urls = [(BASE_URL + "/", None),
            (BASE_URL + "/a-propos/", None),
            (BASE_URL + "/mentions-legales/", None)]
    for f in posts:
        lm = (f["modified"] or f["date"] or "")[:10]
        urls.append((f"{BASE_URL}/article/{f['slug']}/", lm or None))
    items = ""
    for loc, lm in urls:
        items += f"  <url><loc>{html.escape(loc)}</loc>" + (f"<lastmod>{lm}</lastmod>" if lm else "") + "</url>\n"
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + items + "</urlset>\n"

def write(path, content):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True) if os.path.dirname(path) else None
    with open(full, "w", encoding="utf-8") as fp:
        fp.write(content)
    print("écrit:", path)

# ----------------------------------------------------------------------------
def main():
    try:
        raw = fetch_posts()
    except Exception as e:
        print("ERREUR récupération WordPress :", e, file=sys.stderr)
        sys.exit(1)   # on n'écrase rien si l'API échoue
    posts = [post_fields(p) for p in raw]
    posts.sort(key=lambda f: f["date"], reverse=True)
    print(f"{len(posts)} article(s) récupéré(s).")

    # purge des anciennes pages d'articles
    art_dir = os.path.join(OUT, "article")
    if os.path.isdir(art_dir):
        import shutil
        shutil.rmtree(art_dir)

    write("index.html", render_home(posts))
    for f in posts:
        write(f"article/{f['slug']}/index.html", render_article(f))
    write("a-propos/index.html", render_page(
        "a-propos", "À propos",
        "Renseignons-nous, média indépendant sur le renseignement, la défense et la géopolitique, à partir de sources ouvertes.",
        ABOUT_HTML))
    write("mentions-legales/index.html", render_page(
        "mentions-legales", "Mentions légales",
        "Mentions légales du site Renseignons-nous : éditeur, hébergement, propriété intellectuelle et données personnelles.",
        LEGAL_HTML))
    write("favicon.svg", FAVICON)
    write("sitemap.xml", sitemap(posts))
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n")
    print("Terminé.")

if __name__ == "__main__":
    main()
