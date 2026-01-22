import os
import base64
import requests
import json
from fastapi import FastAPI
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
    username: constr(min_length=1, max_length=200)

# =====================
# HELPERS
# =====================
def instagram_url(username: str) -> str:
    return f"https://www.instagram.com/{username}/"

def take_screenshot(url: str) -> str | None:
    """
    Intenta obtener screenshot.
    Si falla, devuelve None (NO rompe el flujo).
    """
    if not SCRAPINGBEE_API_KEY:
        return None

    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": url,
        "render_js": "true",
        "screenshot": "true",
        "screenshot_format": "png",
        "premium_proxy": "true",
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        )
    }

    try:
        response = requests.get(
            "https://app.scrapingbee.com/api/v1/",
            params=params,
            timeout=90
        )

        if response.status_code != 200:
            return None

        if not response.content or len(response.content) < 1500:
            return None

        return base64.b64encode(response.content).decode("utf-8")

    except Exception:
        return None

def analyze_with_gpt(image_base64: str) -> dict:
    """
    Análisis visual puro.
    GARANTIZA JSON válido.
    """
    prompt = """
Analiza VISUALMENTE esta imagen.

Evalúa:
- Paleta de colores
- Ruido visual
- Consistencia gráfica
- Calidad visual
- Presencia humana (caras/personas)

Devuelve SOLO JSON válido con este formato EXACTO:

{
  "scores": {
    "paleta_colores": 1,
    "ruido_visual": 1,
    "consistencia_grafica": 1,
    "calidad_visual": 1,
    "presencia_humana": 1
  },
  "interpretation": "Texto breve profesional"
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

    # 🔒 GPT devuelve string JSON → lo parseamos
    return json.loads(response.choices[0].message.content)

# =====================
# ROUTES
# =====================
@app.get("/")
def root():
    return {"status": "Kontrategy backend alive"}

@app.post("/analysis/visual")
def visual_analysis(data: VisualAnalysisRequest):
    raw = data.username.strip()

    if raw.startswith("http"):
        url = raw
        username = raw
    else:
        username = raw.replace("@", "").replace("/", "").lower()
        url = instagram_url(username)

    screenshot_base64 = take_screenshot(url)

    # 🚨 SI NO HAY IMAGEN → NO ROMPE
    if not screenshot_base64:
        return {
            "status": "no_image",
            "username": username,
            "message": "No se pudo generar screenshot visual",
            "scores": None,
            "total_score": None,
            "interpretation": None
        }

    analysis = analyze_with_gpt(screenshot_base64)

    scores = analysis["scores"]
    total_score = sum(scores.values())

    return {
        "status": "ok",
        "username": username,
        "scores": scores,
        "total_score": total_score,
        "interpretation": analysis["interpretation"]
    }
