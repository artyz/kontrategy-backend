import os
import json
import base64
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
    allow_origins=["*"],  # cerrar en prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================
# MODELS
# =====================
class VisualAnalysisRequest(BaseModel):
    username: constr(min_length=1, max_length=30)

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
    }

    res = requests.get(
        "https://app.scrapingbee.com/api/v1/",
        params=params,
        timeout=120
    )

    content_type = res.headers.get("Content-Type", "")

    if res.status_code != 200 or "image" not in content_type:
        print("SCRAPINGBEE ERROR:", res.text[:500])
        raise HTTPException(
            status_code=500,
            detail="ScrapingBee did not return an image"
        )

    image_base64 = base64.b64encode(res.content).decode("utf-8")

    if len(image_base64) < 20_000:
        raise HTTPException(
            status_code=400,
            detail="Screenshot invalid or blocked"
        )

    return image_base64

def analyze_with_gpt(image_base64: str):
    prompt = """
Analiza VISUALMENTE este perfil de Instagram.
Evalúa colores, consistencia gráfica, tipografías,
estructura del feed y presencia humana.

Devuelve EXCLUSIVAMENTE un JSON válido con este formato:

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
    username = data.username.replace("@", "").strip().lower()

    url = instagram_url(username)

    image_base64 = take_screenshot(url)

    gpt_result = analyze_with_gpt(image_base64)

    try:
        parsed = json.loads(gpt_result)
    except json.JSONDecodeError:
        print("GPT RAW RESPONSE:", gpt_result)
        raise HTTPException(status_code=500, detail="GPT returned invalid JSON")

    scores = parsed["scores"]
    total_score = sum(scores.values())

    return {
        "username": username,
        "scores": scores,
        "total_score": total_score,
        "interpretation": parsed["interpretation"]
    }
