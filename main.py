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
BROWSERLESS_API_KEY = os.getenv("BROWSERLESS_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

if not BROWSERLESS_API_KEY:
    raise RuntimeError("BROWSERLESS_API_KEY missing")

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
    response = requests.post(
        "https://chrome.browserless.io/screenshot",
        params={"token": BROWSERLESS_API_KEY},
        json={
            "url": url,
            "waitUntil": "networkidle2",
            "viewport": {"width": 1280, "height": 2000},
            "options": {
                "fullPage": False,
                "type": "png"
            }
        },
        timeout=60
    )

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Screenshot failed")

    image_base64 = base64.b64encode(response.content).decode("utf-8")

    if len(image_base64) < 20_000:
        raise HTTPException(
            status_code=400,
            detail="Instagram profile not accessible"
        )

    return image_base64

def analyze_with_gpt(image_base64: str):
    prompt = """
Devuelve EXCLUSIVAMENTE un JSON válido (sin texto adicional, sin markdown)
con este formato exacto:

{
  "scores": {
    "paleta_colores": 1,
    "ruido_visual": 1,
    "consistencia_grafica": 1,
    "calidad_visual": 1,
    "presencia_humana": 1
  },
  "interpretation": "texto breve profesional"
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
