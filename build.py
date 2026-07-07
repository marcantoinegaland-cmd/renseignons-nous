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
BASE_URL  = os.environ.get("BASE_URL", "https://marcantoinegaland-cmd.github.io/renseignons-nous")
BASE_PATH = os.environ.get("BASE_PATH", "/renseignons-nous/")   # préfixe des liens internes
SITE_NAME = "Renseignons-nous"
AUTHOR    = "Marc-Antoine Galand"
OUT       = os.path.dirname(os.path.abspath(__file__))

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

def head(title, desc, canonical, img="", og_type="website", jsonld=None, published=""):
    tags = [
        '<meta charset="UTF-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />',
        f'<title>{html.escape(title)}</title>',
        f'<meta name="description" content="{html.escape(desc)}" />',
        f'<link rel="canonical" href="{html.escape(canonical)}" />',
        '<meta name="robots" content="index, follow, max-image-preview:large" />',
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
  window.subscribe = function(form){
    var i=form.querySelector('input[type=email]'), btn=form.querySelector('button'), o=btn.textContent;
    btn.textContent='Inscription confirmée'; i.value=''; i.placeholder='Merci — surveillez votre boîte.';
    setTimeout(function(){ btn.textContent=o; i.placeholder='votre@email.com'; }, 4000);
  };
})();
</script>"""

def card(f):
    href = f"{BASE_PATH}article/{f['slug']}/"
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
    <form class="nl-form" onsubmit="event.preventDefault(); subscribe(this);">
      <input type="email" required placeholder="votre@email.com" aria-label="Adresse e-mail" />
      <button type="submit">S'abonner</button>
    </form>
  </div>
</section>
{footer('')}
{HOME_JS}
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
             og_type="article", jsonld=jsonld, published=f["date"])
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
{masthead(BASE_PATH, full=False)}
<main class="article-page">
  <a class="article-back" href="{BASE_PATH}">← Toutes les enquêtes</a>
  <div class="article-meta-top"><span class="tag">{html.escape(f['label'])}</span><span class="article-date">{f['date_fr']}</span></div>
  <h1 class="article-title">{html.escape(f['title'])}</h1>
  {dek}
  {hero}
  <div class="article-body">
{body}
    <div class="article-signature"><span class="sig-rule"></span><p class="sig-name">{AUTHOR}</p><p class="sig-pub">Renseignons-nous</p></div>
  </div>
</main>
{footer(BASE_PATH)}
</body>
</html>"""

def sitemap(posts):
    urls = [(BASE_URL + "/", None)]
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
    write("sitemap.xml", sitemap(posts))
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n")
    print("Terminé.")

if __name__ == "__main__":
    main()
