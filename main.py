import os
import json
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_TASK_ID = os.getenv("APIFY_TASK_ID")  # Oru7yUFMpZ1PxSzC

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

if not APIFY_TOKEN or not APIFY_TASK_ID:
    raise RuntimeError("APIFY_TOKEN or APIFY_TASK_ID missing")

client = OpenAI(api_key=OPENAI_API_KEY)

# =====================
# APP
# =====================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================
# MODELS
# =====================
class AnalyzeRequest(BaseModel):
    username: str

# =====================
# APIFY
# =====================
def run_apify_profile(instagram_url: str) -> dict:
    url = f"https://api.apify.com/v2/actor-tasks/{APIFY_TASK_ID}/run-sync-get-dataset-items"
    res = requests.post(
        f"{url}?token={APIFY_TOKEN}",
        json={"instagramUrls": [instagram_url]},
        timeout=120
    )

    if res.status_code != 200:
        raise RuntimeError("Apify request failed")

    data = res.json()
    if not data:
        raise RuntimeError("No data from Apify")

    return data[0]

# =====================
# ROUTES
# =====================
@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/analysis/visual")
def analyze(data: AnalyzeRequest):
    raw = data.username.strip().replace("@", "").replace("/", "")
    instagram_url = f"https://www.instagram.com/{raw}/"

    profile = run_apify_profile(instagram_url)

    followers = profile.get("followersCount", 0)
    posts = profile.get("postsCount", 0)

    # SCORE SIMPLE (por ahora)
    score = min(10, round((followers / 10000) + 5, 1))

    return {
        "status": "ok",
        "profile": {
            "username": raw,
            "icon": profile.get("profilePicUrl"),
            "category": profile.get("businessCategoryName"),
            "description": profile.get("biography"),
            "followers": followers,
            "following": profile.get("followsCount"),
            "posts": posts,
        },
        "total_score": score,
        "dominant_content_type": "perfil",
        "interpretation": "Perfil analizado correctamente. Datos obtenidos desde Instagram."
    }
