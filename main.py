import base64
from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import json

client = OpenAI()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# ANALYSIS ENDPOINT
# =========================
@app.post("/analysis")
async def analyze(
    profile_name: str = Form(...),
    images: list[UploadFile] = Form(...)
):
    vision_inputs = []

    for img in images[:5]:
        content = await img.read()
        b64 = base64.b64encode(content).decode("utf-8")

        vision_inputs.append({
            "type": "input_image",
            "image_base64": b64
        })

    prompt = f"""
Eres un analista experto en estrategia de contenido para redes sociales.

Analiza visualmente el perfil de Instagram llamado "{profile_name}".

Devuelve SOLO JSON válido con esta estructura exacta:

{{
  "profile_detected": {{
    "username": string | null,
    "followers_visible": boolean,
    "followers_estimated": number | null,
    "posts_visible": boolean
  }},
  "content_distribution": {{
    "educativo": number,
    "entretenimiento": number,
    "inspiracional": number,
    "ventas": number
  }},
  "visual_consistency": number,
  "human_presence": number,
  "branding_strength": number,
  "interpretation": string
}}

Las proporciones deben sumar 1.
Si no puedes ver seguidores con claridad, estima o deja null.
"""

    response = client.responses.create(
        model="gpt-4o",
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                *vision_inputs
            ]
        }],
        max_output_tokens=600
    )

    output_text = response.output_text

    return json.loads(output_text)
