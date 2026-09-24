"""
Portail Emplois Monde - Backend API
FastAPI + Apify pour scraper les sites d'emploi africains en temps réel.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import httpx
import os
from datetime import datetime

app = FastAPI(
    title="Portail Emplois Monde - API Backend",
    description="API de scraping d'offres d'emploi africaines via Apify",
    version="1.0.0"
)

# CORS : autorise votre site (Netlify, GitHub Pages, etc.) à appeler cette API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# CONFIGURATION APIFY
# ============================================================
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")

APIFY_ACTORS = {
    "jobberman": {
        "id": "blackfalcondata/jobberman-scraper",
        "name": "Jobberman (Nigeria)",
        "countries": ["ng"]
    },
    "pnet": {
        "id": "blackfalcondata/pnet-scraper",
        "name": "Pnet (Afrique du Sud)",
        "countries": ["za"]
    },
    "africa_jobs": {
        "id": "jungle_synthesizer/africa-jobs-aggregator-scraper",
        "name": "Africa Jobs (Jobberman + BrighterMonday + Careers24 + MyJobMag)",
        "countries": ["ng", "ke", "za"]
    }
}


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
async def run_apify_actor(actor_id: str, input_data: dict) -> list:
    """Lance un acteur Apify et attend les résultats."""
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    params = {"token": APIFY_TOKEN, "timeout": 120}

    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(url, params=params, json=input_data)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            print(f"Timeout sur {actor_id}")
            return []
        except httpx.HTTPStatusError as e:
            print(f"Erreur HTTP {e.response.status_code} sur {actor_id}: {e.response.text}")
            return []
        except Exception as e:
            print(f"Erreur inattendue sur {actor_id}: {e}")
            return []


def normalize_job(raw: dict, source: str, country_code: str) -> JobResult:
    """Normalise les données d'un acteur Apify vers notre format standard."""
    return JobResult(
        titre=raw.get("title") or raw.get("job_title") or "Poste",
        entreprise=raw.get("company") or raw.get("company_name") or "Non précisé",
        lieu=raw.get("location") or raw.get("location_city") or raw.get("location_country") or country_code.upper(),
        pays=country_code.upper(),
        salaire=raw.get("salary_range") or raw.get("salary") or "Non précisé",
        date_limite=raw.get("closes_at") or raw.get("posted_at") or "Voir l'offre",
        description=(raw.get("description") or "")[:500],
        url=raw.get("apply_url") or raw.get("url") or "#",
        source=source
    )


# ============================================================
# ENDPOINTS  (avec GET et HEAD pour le health check Render)
# ============================================================
@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {
        "status": "online",
        "service": "Portail Emplois Monde - Backend",
        "apify_configured": bool(APIFY_TOKEN),
        "timestamp": datetime.now().isoformat()
    }


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "healthy", "apify_token_present": bool(APIFY_TOKEN)}


@app.api_route("/test", methods=["GET", "HEAD"])
def test():
    return {"message": "Le backend fonctionne !"}


@app.get("/api/actors")
def list_actors():
    """Liste les acteurs Apify disponibles."""
    return {
        "actors": [
            {"key": k, "name": v["name"], "countries": v["countries"]}
            for k, v in APIFY_ACTORS.items()
        ]
    }


@app.post("/api/search", response_model=List[JobResult])
async def search_jobs(request: JobSearchRequest):
    """
    Recherche d'offres d'emploi via les scrapers Apify.
    Filtre STRICTEMENT par pays.
    """
    if not APIFY_TOKEN:
        raise HTTPException(status_code=500, detail="APIFY_TOKEN non configuré")

    if not request.query or len(request.query.strip()) < 2:
        raise HTTPException(status_code=400, detail="Mot-clé trop court")

    if not request.countries:
        raise HTTPException(status_code=400, detail="Sélectionnez au moins un pays")

    all_results = []

    for actor_key, actor_config in APIFY_ACTORS.items():
        matching_countries = [c for c in request.countries if c in actor_config["countries"]]
        if not matching_countries:
            continue

        input_data = build_actor_input(actor_key, actor_config, request, matching_countries)

        print(f"Lancement de {actor_config['name']} pour {matching_countries}")
        raw_results = await run_apify_actor(actor_config["id"], input_data)

        for raw in raw_results:
            job_country = (raw.get("location_country") or "").lower()
            if job_country and job_country not in request.countries:
                continue
            normalized = normalize_job(raw, actor_config["name"], job_country or matching_countries[0])
            all_results.append(normalized)

    seen = set()
    unique = []
    for job in all_results:
        key = f"{job.titre.lower()}|{job.entreprise.lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(job)

    return unique[:request.max_results]


def build_actor_input(actor_key: str, actor_config: dict, request: JobSearchRequest, countries: list) -> dict:
    """Construit les paramètres d'entrée selon l'acteur Apify."""
    if actor_key == "jobberman":
        return {
            "query": request.query,
            "country": "NG",
            "maxResults": request.max_results,
            "includeDetails": True
        }
    elif actor_key == "pnet":
        return {
            "query": request.query,
            "maxResults": request.max_results,
            "includeDetails": True
        }
    elif actor_key == "africa_jobs":
        return {
            "query": request.query,
            "maxResults": request.max_results,
            "platforms": ["jobberman", "brightermonday", "careers24", "myjobmag"]
        }
    return {"query": request.query, "maxResults": request.max_results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
