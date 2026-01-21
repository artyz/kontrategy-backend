import os
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr
from openai import OpenAI

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

if not SCRAPINGBEE_API_KEY:
    raise RuntimeError("SCRAPINGBEE_API_KEY missing")

client = OpenAI(api_key=OPENAI_API_KEY)

# =====================
# APP
# =====================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================
# MODELS
# =====================
class VisualAnalysisRequest(BaseModel):
    username: constr(min_length=1, max_length=100)

# =====================
# HELPERS
# =====================
def instagram_url(username: str) -> str:
    return f"https://www.instagram.com/{username}/"

def take_screenshot(url: str) -> str:
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": url,
        "render_js": "true",
        "premium_proxy": "true",
        "screenshot": "true",
        "screenshot_format": "png",
        "country_code": "us",
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        )
    }

    response = requests.get(
        "https://app.scrapingbee.com/api/v1/screenshot",
        params=params,
        timeout=120
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail="ScrapingBee screenshot failed"
        )

    data = response.json()

    if "screenshot" not in data:
        raise HTTPException(
            status_code=500,
            detail="ScrapingBee response missing screenshot"
        )

    return data["screenshot"]  # 🔴 YA ES BASE64

def analyze_with_gpt(image_base64: str) -> dict:
    prompt = """
Analiza VISUALMENTE esta página.
Evalúa paleta de colores, estructura, tipografías,
consistencia gráfica y jerarquía visual.

Devuelve SOLO un JSON válido con este formato:

{
  "scores": {
    "paleta_colores": 1,
    "ruido_visual": 1,
    "consistencia_grafica": 1,
    "calidad_visual": 1,
    "presencia_humana": 1
  },
  "interpretation": "análisis visual profesional breve"
}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        max_tokens=300
    )

    return response.choices[0].message.content

# =====================
# ROUTES
# =====================
@app.get("/")
def root():
    return {"status": "Kontrategy backend alive"}

@app.post("/analysis/visual")
def visual_analysis(data: VisualAnalysisRequest):
    username = data.username.replace("@", "").replace("/", "").strip().lower()

    url = (
        data.username
        if data.username.startswith("http")
        else instagram_url(username)
    )

    screenshot_base64 = take_screenshot(url)

    analysis = analyze_with_gpt(screenshot_base64)

    scores = analysis["scores"]
    total_score = sum(scores.values())

    return {
        "username": username,
        "scores": scores,
        "total_score": total_score,
        "interpretation": analysis["interpretation"]
    }
