# backend/app/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import os
import json
from typing import List, Dict, Any, Optional
from fastapi.middleware.cors import CORSMiddleware
from .settings import settings

MISTRAL_API_KEY = settings.MISTRAL_API_KEY
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev mode
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class PromptRequest(BaseModel):
    prompt: str

@app.post("/generate")
async def generate(req: PromptRequest):
    # print(MISTRAL_API_URL)
    # print(MISTRAL_API_KEY)
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "mistral-small-latest",   # or your chosen model
        "messages": [
            {"role": "user", "content": req.prompt}
        ]
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(MISTRAL_API_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    # extract the text
    answer = data["choices"][0]["message"]["content"]
    return {"answer": answer}


# config: can set ROUTER_URL env var to a valhalla/graphhopper/osrm-like service
# e.g. export ROUTER_URL="http://router.project-osrm.org"
ROUTER_URL = os.getenv("ROUTER_URL")  # optional

class PlanRequest(BaseModel):
    city: str
    duration_minutes: Optional[int] = 120
    preferences: Optional[str] = ""

async def geocode_city(city: str) -> Dict[str, Any]:
    # Nominatim public endpoint
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city, "format": "json", "limit": 1}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params, headers={"User-Agent": "marcheroute/0.0.1"})
    if r.status_code != 200 or not r.json():
        raise HTTPException(404, detail="City not found")
    data = r.json()[0]
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return {"lat": float(data["lat"]), "lon": float(data["lon"]), "bbox": data.get("boundingbox")}

async def query_overpass(bbox: List[float]) -> List[Dict[str, Any]]:
    # bbox: [south, north, west, east] from Nominatim returned boundingbox (south, north)
    # We'll query some basic POI tags: cafe, restaurant, museum, park, bookstore
    south, north, west, east = bbox[0], bbox[1], bbox[2], bbox[3]
    # Overpass bbox format is: south,west,north,east
    overpass_bbox = f"{south},{west},{north},{east}"
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="cafe"]({overpass_bbox});
      node["amenity"="restaurant"]({overpass_bbox});
      node["tourism"="museum"]({overpass_bbox});
      node["shop"="books"]({overpass_bbox});
      node["leisure"="park"]({overpass_bbox});
    );
    out center 200;
    """
    url = "https://overpass-api.de/api/interpreter"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, data=query, headers={"User-Agent": "marcheroute/0.0.1"})
    if r.status_code != 200:
        return []
    resp = r.json()
    elements = resp.get("elements", [])
    pois = []
    for el in elements:
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        pois.append({
            "id": el.get("id"),
            "type": el.get("type"),
            "lat": lat,
            "lon": lon,
            "tags": el.get("tags", {}),
            "name": (el.get("tags") or {}).get("name", "(no name)")
        })
    return pois

async def route_between_points(points: List[Dict[str, float]]) -> Dict[str, Any]:
    """
    Try to call an external router if ROUTER_URL set.
    Fallback: return straight-line polyline of the points.
    Expected points: [{"lat":..., "lon":...}, ...]
    """
    if not ROUTER_URL:
        # fallback polyline: just return lat/lon sequence
        return {"type": "fallback", "polyline": [(p["lat"], p["lon"]) for p in points]}
    # Try OSRM-like simple route (project OSRM server API assumed)
    # Build coordinates string lon,lat;lon,lat;...
    coords = ";".join([f"{p['lon']},{p['lat']}" for p in points])
    # Try OSRM /route/v1/foot/... as an example compatibility
    # We'll attempt OSRM first
    osrm_url = f"{ROUTER_URL}/route/v1/foot/{coords}"
    params = {"geometries": "geojson", "overview": "full"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            r = await client.get(osrm_url, params=params)
            if r.status_code == 200:
                js = r.json()
                routes = js.get("routes")
                if routes:
                    return {"type": "osrm", "geojson": routes[0]["geometry"]}
        except Exception:
            pass
    # If OSRM attempt failed, try GraphHopper-like API (if available)
    gh_url = f"{ROUTER_URL}/route"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(gh_url, json={"points": [{"lat":p["lat"], "lng":p["lon"]} for p in points]})
            if r.status_code == 200:
                return {"type": "graphhopper", "json": r.json()}
    except Exception:
        pass
    # if everything fails, fallback:
    return {"type": "fallback", "polyline": [(p["lat"], p["lon"]) for p in points]}

@app.get("/plan/{city}/{duration_minutes}")
async def plan_path(city: str, duration_minutes: int = 120):
    req = PlanRequest(city=city, duration_minutes=duration_minutes)
    return await plan(req)

@app.post("/plan")
async def plan(req: PlanRequest):
    # 1) geocode
    ge = await geocode_city(req.city)
    # mistral key
    bbox = ge["bbox"]  # [south, north, west, east] strings
    # Sometimes Nominatim returns bbox as [south, north, west, east] strings, ensure floats and correct order
    # Overpass expects south,west,north,east; Nominatim returns [south, north, west, east]
    south = float(bbox[0])
    north = float(bbox[1])
    west = float(bbox[2])
    east = float(bbox[3])
    pois = await query_overpass([south, north, west, east])
    if not pois:
        # return city center at least
        return {"city": req.city, "center": {"lat": ge["lat"], "lon": ge["lon"]}, "stops": [], "route": None}
    # pick up to 6 POIs - simple heuristic: first ones (we can sort later)
    selected = pois[:6]
    # build points: start at city center -> POIs -> back to center
    points = [{"lat": ge["lat"], "lon": ge["lon"]}] + [{"lat": p["lat"], "lon": p["lon"]} for p in selected]
    # route
    routing = await route_between_points(points)
    return {
        "city": req.city,
        "center": {"lat": ge["lat"], "lon": ge["lon"]},
        "stops": selected,
        "route": routing
    }
