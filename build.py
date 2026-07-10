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
import urllib.parse

# ----------------------------------------------------------------------------
WP_SITE   = os.environ.get("WP_SITE", "renseignonsnous.wordpress.com")
BASE_URL  = os.environ.get("BASE_URL", "https://renseignonsnous.fr")   # domaine (URLs absolues SEO)
BASE_PATH = os.environ.get("BASE_PATH", "/")   # (liens internes désormais relatifs — conservé pour compat)
SITE_NAME = "Renseignons-nous"
AUTHOR    = "Marc-Antoine Galand"
BLOG_ID   = os.environ.get("BLOG_ID", "256008490")            # newsletter WordPress/Jetpack
CONTACT   = os.environ.get("CONTACT_EMAIL", "redaction@renseignonsnous.fr")
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
# ---- Markdown : front-matter + conversion en HTML (pur stdlib) --------------
def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    return v

def parse_frontmatter(raw):
    """Sépare le bloc YAML --- ... --- (clés simples + listes) du corps Markdown."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    meta, body = {}, raw
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            fm = raw[4:end]
            body = raw[end + 4:].lstrip("\n")
            listbuf = None
            for ln in fm.split("\n"):
                if not ln.strip():
                    continue
                m = re.match(r"^([\w-]+):\s*(.*)$", ln)
                if m and not ln[:1].isspace():
                    key, val = m.group(1), m.group(2).strip()
                    if val == "":
                        meta[key] = []
                        listbuf = meta[key]
                    else:
                        meta[key] = _unquote(val)
                        listbuf = None
                elif re.match(r"^\s*-\s+", ln) and listbuf is not None:
                    listbuf.append(_unquote(re.sub(r"^\s*-\s+", "", ln)))
    return meta, body

def _inline(s):
    s = html.escape(s)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1" loading="lazy"/>', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s

def md_to_html(md):
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, para, i = [], [], 0
    def flush():
        if para:
            t = " ".join(x.strip() for x in para).strip()
            if t:
                out.append("<p>" + _inline(t) + "</p>")
            para.clear()
    while i < len(lines):
        ln = lines[i]; s = ln.strip()
        if not s:
            flush(); i += 1; continue
        m = re.match(r"(#{1,6})\s+(.*)", s)
        if m:
            flush(); lvl = 2 if len(m.group(1)) <= 2 else 3
            out.append(f"<h{lvl}>" + _inline(m.group(2).strip()) + f"</h{lvl}>"); i += 1; continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            flush(); out.append("<hr/>"); i += 1; continue
        if s.startswith(">"):
            flush(); q = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(re.sub(r"^\s*>\s?", "", lines[i])); i += 1
            out.append("<blockquote>" + _inline(" ".join(x.strip() for x in q)) + "</blockquote>"); continue
        if re.match(r"^[-*+]\s+", s):
            flush(); items = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i]).strip()); i += 1
            out.append("<ul>" + "".join("<li>" + _inline(x) + "</li>" for x in items) + "</ul>"); continue
        if re.match(r"^\d+\.\s+", s):
            flush(); items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]).strip()); i += 1
            out.append("<ol>" + "".join("<li>" + _inline(x) + "</li>" for x in items) + "</ol>"); continue
        para.append(ln); i += 1
    flush()
    return "\n".join(out)

def txt(s):
    """HTML entities -> texte brut lisible."""
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()

def attr(s):
    """Échappe pour un attribut / meta."""
    return html.escape(txt(s), quote=True)

def img_src(p):
    """Chemin d'image encodé pour une URL (gère espaces/parenthèses des noms de fichiers)."""
    if not p:
        return ""
    if p.startswith("http"):
        return p
    return urllib.parse.quote(p, safe="/")

def abs_img(p):
    """URL absolue d'image (pour og:image, twitter:image, JSON-LD)."""
    p = img_src(p)
    if p and p.startswith("/"):
        return BASE_URL + p
    return p

def clip(s, n=155):
    s = re.sub(r"\s+", " ", s).strip()
    return (s[: n - 1].rstrip() + "…") if len(s) > n else s

def date_fr(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{d} {MOIS[mo]} {y}"

def slugify(s):
    """URL propre : sans accent, minuscule, tirets (é->e, espaces/ponctuation->-)."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "article"

def load_articles():
    """Lit content/articles/*.md et renvoie les articles (triés plus loin)."""
    d = os.path.join(OUT, "content", "articles")
    posts = []
    if not os.path.isdir(d):
        return posts
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        raw = open(os.path.join(d, fn), encoding="utf-8").read()
        meta, body = parse_frontmatter(raw)
        slug = slugify(meta.get("slug") or re.sub(r"\.md$", "", fn))
        cat = (meta.get("category") or "").strip()
        date = (meta.get("date") or "").strip()
        posts.append({
            "slug": slug,
            "title": (meta.get("title") or "Sans titre").strip(),
            "excerpt": (meta.get("excerpt") or "").strip(),
            "content": md_to_html(body),
            "img": (meta.get("image") or "").strip(),
            "label": CATS.get(cat, "Article"),
            "cat": cat if cat in CATS else "",
            "date": date,
            "modified": (meta.get("modified") or date).strip(),
            "date_fr": date_fr(date),
            "tags": meta.get("tags") or [],
        })
    return posts

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
        f'<link rel="icon" type="image/png" href="{root}favicon.png?v=2" />',
        f'<link rel="apple-touch-icon" href="{root}favicon.png?v=2" />',
        f'<link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="{root}rss.xml" />',
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
        oimg = abs_img(img)
        tags.append(f'<meta property="og:image" content="{html.escape(oimg)}" />')
        tags.append(f'<meta name="twitter:image" content="{html.escape(oimg)}" />')
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
      <a href="{home}renseignement/">Renseignement</a>
      <a href="{home}defense/">Défense</a>
      <a href="{home}geopolitique/">Géopolitique</a>
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
    <p class="mast-desc">Les profondeurs plutôt que l'écume.</p>
  </div>
</header>"""

def footer(home):
    return f"""<footer>
  <div class="ft">
    <div class="ft-inner">
      <div>
        <p class="ft-word">Renseignons-nous</p>
        <p class="ft-tag">Renseignement · Défense · Géopolitique</p>
        <div class="ft-social">
          <a href="https://www.instagram.com/renseignonsnous/" target="_blank" rel="noopener" aria-label="Instagram">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="2.5" width="19" height="19" rx="5.5"/><circle cx="12" cy="12" r="4.1"/><circle cx="17.4" cy="6.6" r="1.15" fill="currentColor" stroke="none"/></svg>
          </a>
          <a href="https://www.tiktok.com/@renseignonsnous" target="_blank" rel="noopener" aria-label="TikTok">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 3c.31 2.06 1.46 3.29 3.46 3.42v2.32c-1.16.11-2.17-.27-3.35-.99v4.86c0 6.18-6.74 8.11-9.45 3.68-1.74-2.85-.67-7.85 4.92-8.05v2.44c-.43.07-.88.18-1.3.32-1.24.42-1.95 1.21-1.75 2.6.37 2.66 5.25 3.45 4.84-1.77V3.01h2.63Z"/></svg>
          </a>
        </div>
      </div>
      <nav class="ft-links" aria-label="Pied de page">
        <a href="{home}renseignement/">Renseignement</a>
        <a href="{home}defense/">Défense</a>
        <a href="{home}geopolitique/">Géopolitique</a>
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
    media = (f'<div class="card-media"><img src="{img_src(f["img"])}" alt="{attr(f["title"])}" loading="lazy"/></div>'
             if f["img"] else "")
    return f"""      <a class="article-card" data-cat="{f['cat']}" href="{href}">
        {media}
        <div class="card-body">
          <div class="card-meta"><span class="tag">{html.escape(f['label'])}</span><p class="card-date">{f['date_fr']}</p></div>
          <h3 class="card-title">{html.escape(f['title'])}</h3>
        </div>
      </a>"""

def related_posts(cur, posts, n=3):
    """Autres articles : même rubrique d'abord, puis les plus récents."""
    same = [p for p in posts if p["slug"] != cur["slug"] and p["cat"] == cur["cat"]]
    other = [p for p in posts if p["slug"] != cur["slug"] and p["cat"] != cur["cat"]]
    return (same + other)[:n]

# ----------------------------------------------------------------------------
def render_home(posts):
    cards = "\n\n".join(card(f) for f in posts)
    og_img = posts[0]["img"] if posts and posts[0].get("img") else ""
    empty = "" if posts else '<p class="empty-state">Les premiers articles seront publiés prochainement.</p>'
    jsonld = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME,
              "url": BASE_URL + "/",
              "description": "Renseignement, défense et géopolitique — articles et analyses sourcées."}
    h = head("Renseignons-nous — Renseignement, défense, géopolitique",
             "Le média de référence sur le renseignement, la défense et la géopolitique. Articles longs et analyses sourcées, à partir de sources ouvertes.",
             BASE_URL + "/", img=og_img, og_type="website", jsonld=jsonld)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
{h}
</head>
<body id="top">
{masthead('')}
<main id="enquetes" class="wrap">
  <div class="sec-head">
    <h2 class="sec-title">Derniers articles</h2>
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
      <h2 class="nl-title">Chaque article, dans votre boîte mail.</h2>
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

def render_article(f, posts=()):
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
        jsonld["image"] = [abs_img(f["img"])]
    h = head(f'{f["title"]} — {SITE_NAME}', desc, url, img=f["img"],
             og_type="article", jsonld=jsonld, published=f["date"], root="../../")
    hero = (f'<div class="article-hero"><img src="{img_src(f["img"])}" alt="{attr(f["title"])}"/></div>'
            if f["img"] else "")
    dek = f'<p class="article-dek">{html.escape(f["excerpt"])}</p>' if f["excerpt"] else ""
    body = lead_first_p(f["content"])
    rel = related_posts(f, posts)
    related_html = ""
    if rel:
        rel_cards = "\n".join(card(p, root="../../") for p in rel)
        related_html = f"""<section class="related">
  <h2 class="related-title">À lire aussi</h2>
  <div class="related-grid">
{rel_cards}
  </div>
</section>"""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
{h}
</head>
<body>
{masthead("../../", full=False)}
<main class="article-page">
  <a class="article-back" href="../../">← Tous les articles</a>
  <div class="article-meta-top"><span class="tag">{html.escape(f['label'])}</span><span class="article-date">{f['date_fr']}</span></div>
  <h1 class="article-title">{html.escape(f['title'])}</h1>
  {dek}
  {hero}
  <div class="article-body">
{body}
    <div class="article-signature"><span class="sig-rule"></span><p class="sig-name">{AUTHOR}</p><p class="sig-pub">Renseignons-nous</p></div>
  </div>
</main>
{related_html}
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
<p>La ligne est simple : prendre le temps d'expliquer. Là où l'actualité va vite et se contente souvent de l'écume, ce site publie des articles longs et des analyses de fond, construits uniquement à partir de <strong>sources ouvertes</strong> — documents officiels, rapports parlementaires, données AIS et satellitaires, presse spécialisée, archives. Aucune information n'y est affirmée sans être sourcée et recoupée.</p>
<h2>Une exigence, pas une course</h2>
<p>Chaque article suit le rythme du fact-checking, non celui du flux. On préfère un dossier solide et documenté à dix brèves invérifiables. Pas de publicité, pas de contenu sponsorisé : la seule fidélité du site va au lecteur qui veut <em>comprendre</em>.</p>
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

def render_category(cat, label, posts):
    items = [p for p in posts if p["cat"] == cat]
    url = f"{BASE_URL}/{cat}/"
    cards = "\n\n".join(card(p, root="../") for p in items)
    empty = "" if items else '<p class="empty-state">Aucun article dans cette rubrique pour le moment.</p>'
    h = head(f"{label} — {SITE_NAME}",
             f"Tous les articles de la rubrique {label} sur Renseignons-nous, à partir de sources ouvertes.",
             url, og_type="website", root="../")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
{h}
</head>
<body>
{masthead("../", full=False)}
<main class="wrap">
  <div class="sec-head">
    <h2 class="sec-title">{html.escape(label)}</h2>
  </div>
  <div id="grid">
{cards}
  </div>
  {empty}
</main>
{footer("../")}
{ANALYTICS}
</body>
</html>"""

def render_404():
    root = BASE_URL + "/"
    h = head(f"Page introuvable — {SITE_NAME}", "La page demandée n'existe pas ou a été déplacée.",
             BASE_URL + "/404", og_type="website", root=root)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
{h}
</head>
<body>
{masthead(root, full=False)}
<main class="page">
  <h1 class="page-title">Page introuvable</h1>
  <div class="page-body">
    <p class="lead">La page que vous cherchez n'existe pas, ou a été déplacée.</p>
    <p><a href="{root}">← Retour à l'accueil</a></p>
  </div>
</main>
{footer(root)}
{ANALYTICS}
</body>
</html>"""

def rss(posts):
    from email.utils import format_datetime
    from datetime import datetime, timezone
    items = ""
    for f in posts[:20]:
        link = f"{BASE_URL}/article/{f['slug']}/"
        try:
            dt = datetime.strptime((f["date"] or "")[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            pub = f"      <pubDate>{format_datetime(dt)}</pubDate>\n"
        except Exception:
            pub = ""
        desc = clip(f["excerpt"] or txt(f["content"]), 300)
        items += ("    <item>\n"
                  f"      <title>{html.escape(f['title'])}</title>\n"
                  f"      <link>{link}</link>\n"
                  f"      <guid>{link}</guid>\n"
                  f"{pub}"
                  f"      <description>{html.escape(desc)}</description>\n"
                  "    </item>\n")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0"><channel>\n'
            f"  <title>{SITE_NAME}</title>\n"
            f"  <link>{BASE_URL}/</link>\n"
            "  <description>Renseignement, défense et géopolitique — articles et analyses sourcées.</description>\n"
            "  <language>fr</language>\n"
            f"{items}</channel></rss>\n")

def sitemap(posts):
    urls = [(BASE_URL + "/", None),
            (BASE_URL + "/a-propos/", None),
            (BASE_URL + "/mentions-legales/", None)]
    for cat in CATS:
        urls.append((f"{BASE_URL}/{cat}/", None))
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
    posts = load_articles()
    posts.sort(key=lambda f: (f["date"], f["slug"]), reverse=True)
    print(f"{len(posts)} article(s) chargé(s) depuis content/articles/.")

    # purge des anciennes pages d'articles
    art_dir = os.path.join(OUT, "article")
    if os.path.isdir(art_dir):
        import shutil
        shutil.rmtree(art_dir)

    write("index.html", render_home(posts))
    for f in posts:
        write(f"article/{f['slug']}/index.html", render_article(f, posts))
    for cat, label in CATS.items():
        write(f"{cat}/index.html", render_category(cat, label, posts))
    write("404.html", render_404())
    write("rss.xml", rss(posts))
    write("a-propos/index.html", render_page(
        "a-propos", "À propos",
        "Renseignons-nous, média indépendant sur le renseignement, la défense et la géopolitique, à partir de sources ouvertes.",
        ABOUT_HTML))
    write("mentions-legales/index.html", render_page(
        "mentions-legales", "Mentions légales",
        "Mentions légales du site Renseignons-nous : éditeur, hébergement, propriété intellectuelle et données personnelles.",
        LEGAL_HTML))
    write(".nojekyll", "")   # GitHub Pages : servir les fichiers tels quels (ne pas traiter les .md)
    write("sitemap.xml", sitemap(posts))
    write("robots.txt", f"User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: {BASE_URL}/sitemap.xml\n")
    print("Terminé.")

if __name__ == "__main__":
    main()
