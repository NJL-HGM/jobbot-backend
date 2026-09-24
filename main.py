"""
Portail Emplois Monde - Backend API v2
FastAPI + Apify + Fuzu + Scrapers africains francophones
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import httpx
import os
import re
from datetime import datetime
from bs4 import BeautifulSoup

app = FastAPI(
    title="Portail Emplois Monde - API Backend",
    description="API de scraping d'offres d'emploi africaines (Apify + Fuzu + scrapers locaux)",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CONFIGURATION
# ============================================================
def get_apify_token():
    token = os.getenv("APIFY_TOKEN", "")
    token = token.strip().replace('"', '').replace("'", "").replace("\n", "")
    return token


USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
]


def get_headers():
    import random
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }


# Mapping des pays africains francophones -> sites locaux
AFRICAN_FRANCOPHONE_SITES = {
    'ci': ['projobivoire', 'novojob', 'educarriere'],
    'sn': ['senjob', 'novojob', 'emploi_dakar'],
    'cm': ['jobartis', 'novojob'],
    'cd': ['jobartis'],
    'ao': ['jobartis'],
    'bj': ['novojob'],
    'tg': ['novojob'],
    'bf': ['novojob'],
    'ml': ['novojob'],
    'gn': ['novojob'],
    'ne': ['novojob'],
    'mr': ['novojob'],
    'cg': ['novojob'],
    'ga': ['novojob'],
    'td': ['novojob'],
    'ma': ['novojob'],
    'dz': ['novojob'],
    'tn': ['novojob'],
}


# ============================================================
# MODÈLES
# ============================================================
class JobSearchRequest(BaseModel):
    query: str
    countries: List[str] = []
    sector: Optional[str] = None
    max_results: int = 25


class JobResult(BaseModel):
    titre: str
    entreprise: str
    lieu: str
    pays: str
    salaire: str
    date_limite: str
    description: str
    url: str
    source: str


# ============================================================
# UTILITAIRES
# ============================================================
def extract_deadline(text):
    """Extrait une date limite du texte."""
    if not text:
        return ''
    patterns = [
        r'(\d{2}[/-]\d{2}[/-]\d{4})',
        r'(\d{4}[/-]\d{2}[/-]\d{2})',
        r'(\d{1,2}\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre))',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ''


# ============================================================
# 🚀 FUZU API (Kenya, Nigeria, Ouganda)
# ============================================================
async def fetch_fuzu(query: str) -> list:
    """API Fuzu ouverte et gratuite."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                "https://www.fuzu.com/api/all_jobs",
                headers=get_headers(),
                params={"query": query, "per_page": 30}
            )
            if r.status_code != 200:
                print(f"Fuzu HTTP: {r.status_code}")
                return []
            data = r.json()
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            return [{
                "title": j.get("title", ""),
                "company": j.get("company_name", "") or j.get("employer", ""),
                "location": j.get("location", ""),
                "country": j.get("country_code", "").upper(),
                "salary": j.get("salary", "Non précisé"),
                "closes_at": j.get("deadline", ""),
                "description": (j.get("description", "") or "")[:500],
                "url": j.get("url", "") or j.get("apply_url", ""),
                "_source": "Fuzu"
            } for j in jobs if j.get("title")]
    except Exception as e:
        print(f"Fuzu échoué: {e}")
        return []


# ============================================================
# 🇨🇮 PROJOBIVOIRE (Côte d'Ivoire)
# ============================================================
async def scrape_projobivoire(query: str) -> list:
    """Scrape Projobivoire.com pour la Côte d'Ivoire."""
    try:
        url = f"https://www.projobivoire.com/recherche-jobs?q={query}"
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url, headers=get_headers())
            if r.status_code != 200:
                print(f"Projobivoire HTTP: {r.status_code}")
                return []
            soup = BeautifulSoup(r.text, 'lxml')
            jobs = []
            
            # Chercher les cartes d'offres (plusieurs sélecteurs possibles)
            selectors = [
                'div.card-job', 'div.job-item', 'article.job',
                'div[class*="job"]', 'li.job-listing', 'div.media'
            ]
            cards = []
            for sel in selectors:
                cards = soup.select(sel)
                if cards:
                    break
            
            for card in cards[:20]:
                try:
                    title_tag = card.find(['h3', 'h2', 'h4', 'a'], class_=re.compile(r'title|job'))
                    if not title_tag:
                        title_tag = card.find('a')
                    title = title_tag.get_text(strip=True) if title_tag else ''
                    if not title or len(title) < 5:
                        continue
                    
                    link_tag = card.find('a', href=True)
                    job_url = link_tag['href'] if link_tag else ''
                    if job_url and not job_url.startswith('http'):
                        job_url = f"https://www.projobivoire.com{job_url}"
                    
                    company_tag = card.find(['span', 'div'], class_=re.compile(r'company|employer|entreprise'))
                    company = company_tag.get_text(strip=True) if company_tag else ''
                    
                    text = card.get_text(' ', strip=True)
                    deadline = extract_deadline(text)
                    
                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": "Côte d'Ivoire",
                        "country": "CI",
                        "salary": "Non précisé",
                        "closes_at": deadline or "Voir l'offre",
                        "description": text[:400],
                        "url": job_url,
                        "_source": "Projobivoire"
                    })
                except Exception:
                    continue
            return jobs
    except Exception as e:
        print(f"Projobivoire échoué: {e}")
        return []


# ============================================================
# 🌍 NOVOJOB (Afrique de l'Ouest)
# ============================================================
async def scrape_novojob(query: str, country_code: str = "ci") -> list:
    """Scrape Novojob.com pour les pays d'Afrique francophone."""
    domains = {
        'ci': 'www.novojob.com/emploi-cote-divoire',
        'sn': 'www.novojob.com/emploi-senegal',
        'cm': 'www.novojob.com/emploi-cameroun',
        'ma': 'www.novojob.com/emploi-maroc',
        'bf': 'www.novojob.com/emploi-burkina-faso',
        'ml': 'www.novojob.com/emploi-mali',
        'tg': 'www.novojob.com/emploi-togo',
        'bj': 'www.novojob.com/emploi-benin',
    }
    base = domains.get(country_code)
    if not base:
        return []
    
    try:
        url = f"https://{base}?q={query}"
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url, headers=get_headers())
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, 'lxml')
            jobs = []
            cards = soup.select('div.card-job, div.job-item, article.job, div[class*="job"]')
            
            for card in cards[:20]:
                try:
                    title_tag = card.find(['h3', 'h2', 'a'])
                    title = title_tag.get_text(strip=True) if title_tag else ''
                    if not title or len(title) < 5:
                        continue
                    
                    link_tag = card.find('a', href=True)
                    job_url = link_tag['href'] if link_tag else ''
                    if job_url and not job_url.startswith('http'):
                        job_url = f"https://www.novojob.com{job_url}"
                    
                    text = card.get_text(' ', strip=True)
                    deadline = extract_deadline(text)
                    
                    jobs.append({
                        "title": title,
                        "company": "",
                        "location": country_code.upper(),
                        "country": country_code.upper(),
                        "salary": "Non précisé",
                        "closes_at": deadline or "Voir l'offre",
                        "description": text[:400],
                        "url": job_url,
                        "_source": "Novojob"
                    })
                except Exception:
                    continue
            return jobs
    except Exception as e:
        print(f"Novojob échoué: {e}")
        return []


# ============================================================
# 🇸🇳 EMPLOI DAKAR (Sénégal)
# ============================================================
async def scrape_emploi_dakar(query: str) -> list:
    try:
        url = f"https://www.emploi-dakar.com/recherche-jobs?q={query}"
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url, headers=get_headers())
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, 'lxml')
            jobs = []
            cards = soup.select('div.card-job, div.job-item, article, div[class*="job"]')
            
            for card in cards[:20]:
                try:
                    title_tag = card.find(['h3', 'h2', 'a'])
                    title = title_tag.get_text(strip=True) if title_tag else ''
                    if not title or len(title) < 5:
                        continue
                    
                    link_tag = card.find('a', href=True)
                    job_url = link_tag['href'] if link_tag else ''
                    if job_url and not job_url.startswith('http'):
                        job_url = f"https://www.emploi-dakar.com{job_url}"
                    
                    text = card.get_text(' ', strip=True)
                    jobs.append({
                        "title": title,
                        "company": "",
                        "location": "Sénégal",
                        "country": "SN",
                        "salary": "Non précisé",
                        "closes_at": extract_deadline(text) or "Voir l'offre",
                        "description": text[:400],
                        "url": job_url,
                        "_source": "Emploi Dakar"
                    })
                except Exception:
                    continue
            return jobs
    except Exception as e:
        print(f"Emploi Dakar échoué: {e}")
        return []


# ============================================================
# 🇸🇳 SENJOB (Sénégal)
# ============================================================
async def scrape_senjob(query: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get("https://senjob.com/offres-d-emploi.php", headers=get_headers())
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, 'lxml')
            jobs = []
            # Senjob utilise des liens avec "offre-d-emploi"
            links = soup.find_all('a', href=re.compile(r'offre-d-emploi'))
            q_lower = query.lower().split(' ')[0]
            
            for link in links[:20]:
                title = link.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                # Filtrer par mot-clé
                if q_lower and q_lower not in title.lower():
                    continue
                
                href = link.get('href', '')
                url = href if href.startswith('http') else f"https://senjob.com/{href}"
                
                jobs.append({
                    "title": title,
                    "company": "",
                    "location": "Sénégal",
                    "country": "SN",
                    "salary": "Non précisé",
                    "closes_at": "Voir l'offre",
                    "description": title,
                    "url": url,
                    "_source": "Senjob"
                })
            return jobs
    except Exception as e:
        print(f"Senjob échoué: {e}")
        return []


# ============================================================
# 🇨🇲 JOBARTIS (Cameroun, RDC, Angola)
# ============================================================
async def scrape_jobartis(query: str, country_code: str = "cm") -> list:
    domains = {
        'cm': 'www.jobartis.com',
        'cd': 'www.jobartis.com',
        'ao': 'www.jobartis.com',
    }
    domain = domains.get(country_code, 'www.jobartis.com')
    
    try:
        url = f"https://{domain}/jobs?q={query}"
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url, headers=get_headers())
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, 'lxml')
            jobs = []
            cards = soup.select('div.job, article.job, div[class*="job"]')
            
            for card in cards[:20]:
                try:
                    title_tag = card.find(['h3', 'h2', 'a'])
                    title = title_tag.get_text(strip=True) if title_tag else ''
                    if not title or len(title) < 5:
                        continue
                    
                    link_tag = card.find('a', href=True)
                    job_url = link_tag['href'] if link_tag else ''
                    if job_url and not job_url.startswith('http'):
                        job_url = f"https://{domain}{job_url}"
                    
                    text = card.get_text(' ', strip=True)
                    jobs.append({
                        "title": title,
                        "company": "",
                        "location": country_code.upper(),
                        "country": country_code.upper(),
                        "salary": "Non précisé",
                        "closes_at": extract_deadline(text) or "Voir l'offre",
                        "description": text[:400],
                        "url": job_url,
                        "_source": "Jobartis"
                    })
                except Exception:
                    continue
            return jobs
    except Exception as e:
        print(f"Jobartis échoué: {e}")
        return []


# ============================================================
# 🚀 APIFY (Jobberman, Pnet, Africa Jobs)
# ============================================================
APIFY_ACTORS = {
    "jobberman": {"id": "blackfalcondata/jobberman-scraper", "name": "Jobberman", "countries": ["ng"]},
    "pnet": {"id": "blackfalcondata/pnet-scraper", "name": "Pnet", "countries": ["za"]},
}


async def run_apify_actor(actor_id: str, input_data: dict) -> list:
    token = get_apify_token()
    if not token:
        return []
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    params = {"token": token, "timeout": 120}
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(url, params=params, json=input_data)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Apify {actor_id} échoué: {e}")
            return []


# ============================================================
# NORMALISATION
# ============================================================
def normalize(raw: dict, country_code: str) -> JobResult:
    return JobResult(
        titre=raw.get("title") or raw.get("job_title") or "Poste",
        entreprise=raw.get("company") or raw.get("company_name") or "Non précisé",
        lieu=raw.get("location") or country_code.upper(),
        pays=country_code.upper(),
        salaire=raw.get("salary") or "Non précisé",
        date_limite=raw.get("closes_at") or "Voir l'offre",
        description=(raw.get("description") or "")[:500],
        url=raw.get("url") or "#",
        source=raw.get("_source", "Inconnu")
    )


# ============================================================
# ENDPOINTS
# ============================================================
@app.api_route("/", methods=["GET", "HEAD"])
def root():
    token = get_apify_token()
    return {
        "status": "online",
        "service": "Portail Emplois Monde - Backend v2",
        "version": "2.0.0",
        "sources": ["Apify", "Fuzu", "Projobivoire", "Novojob", "Emploi Dakar", "Senjob", "Jobartis"],
        "apify_configured": bool(token),
        "timestamp": datetime.now().isoformat()
    }


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    token = get_apify_token()
    return {"status": "healthy", "apify_token_present": bool(token)}


@app.get("/api/sources")
def list_sources():
    """Liste toutes les sources disponibles."""
    return {
        "african_scrapers": [
            "Projobivoire (CI)",
            "Novojob (Afrique de l'Ouest)",
            "Emploi Dakar (SN)",
            "Senjob (SN)",
            "Jobartis (CM, RDC, AO)",
        ],
        "african_apis": ["Fuzu (KE, NG, UG)"],
        "apify_scrapers": ["Jobberman (NG)", "Pnet (ZA)"],
    }


@app.post("/api/search", response_model=List[JobResult])
async def search_jobs(request: JobSearchRequest):
    """Recherche multi-sources avec filtre STRICT par pays."""
    if not request.query or len(request.query.strip()) < 2:
        raise HTTPException(status_code=400, detail="Mot-clé trop court")
    if not request.countries:
        raise HTTPException(status_code=400, detail="Sélectionnez au moins un pays")

    all_results = []
    query = request.query.strip()

    # Pour chaque pays
    for country in request.countries:
        # 🇨🇮 Projobivoire (Côte d'Ivoire uniquement)
        if country == 'ci':
            results = await scrape_projobivoire(query)
            all_results.extend([normalize(r, 'ci') for r in results])
        
        # 🌍 Novojob (pays francophones)
        if country in AFRICAN_FRANCOPHONE_SITES:
            if 'novojob' in AFRICAN_FRANCOPHONE_SITES[country]:
                results = await scrape_novojob(query, country)
                all_results.extend([normalize(r, country) for r in results])
        
        # 🇸🇳 Emploi Dakar
        if country == 'sn':
            results = await scrape_emploi_dakar(query)
            all_results.extend([normalize(r, 'sn') for r in results])
            results = await scrape_senjob(query)
            all_results.extend([normalize(r, 'sn') for r in results])
        
        # 🇨🇲🇨🇩 Jobartis
        if country in ['cm', 'cd', 'ao']:
            results = await scrape_jobartis(query, country)
            all_results.extend([normalize(r, country) for r in results])
        
        # 🌍 Fuzu (Kenya, Nigeria, Ouganda)
        if country in ['ke', 'ng', 'ug']:
            results = await fetch_fuzu(query)
            # Filtrer par pays
            for r in results:
                if r.get('country', '').lower() == country:
                    all_results.append(normalize(r, country))
        
        # 🚀 Apify (Jobberman pour NG, Pnet pour ZA)
        if country == 'ng':
            results = await run_apify_actor(APIFY_ACTORS["jobberman"]["id"], {"query": query, "maxResults": 15})
            for r in results:
                r['_source'] = 'Jobberman (Apify)'
                all_results.append(normalize(r, 'ng'))
        
        if country == 'za':
            results = await run_apify_actor(APIFY_ACTORS["pnet"]["id"], {"query": query, "maxResults": 15})
            for r in results:
                r['_source'] = 'Pnet (Apify)'
                all_results.append(normalize(r, 'za'))

    # Déduplication
    seen = set()
    unique = []
    for job in all_results:
        key = f"{job.titre.lower()}|{job.entreprise.lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(job)

    return unique[:request.max_results]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
