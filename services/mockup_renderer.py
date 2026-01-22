import os
import uuid

MOCKUP_DIR = "/tmp/kontrategy_mockups"
os.makedirs(MOCKUP_DIR, exist_ok=True)

def render_instagram_mockup(image_urls: list[str]) -> str:
    """
    Genera un HTML tipo Instagram grid (3x5)
    Devuelve la ruta al archivo HTML
    """

    if len(image_urls) == 0:
        raise ValueError("No images provided for mockup")

    images_html = ""
    for url in image_urls[:15]:
        images_html += f"""
        <div class="post">
            <img src="{url}" loading="lazy" />
        </div>
        """

    html = f"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8" />
<title>Instagram Mockup</title>
<style>
    body {{
        background: #fafafa;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial;
        margin: 0;
        padding: 40px;
        display: flex;
        justify-content: center;
    }}

    .container {{
        width: 390px;
        background: #fff;
        border: 1px solid #ddd;
    }}

    .header {{
        padding: 16px;
        font-weight: 600;
        border-bottom: 1px solid #eee;
    }}

    .grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 2px;
    }}

    .post {{
        width: 100%;
        aspect-ratio: 1 / 1;
        overflow: hidden;
        background: #eee;
    }}

    .post img {{
        width: 100%;
        height: 100%;
        object-fit: cover;
    }}
</style>
</head>
<body>
    <div class="container">
        <div class="header">Perfil analizado</div>
        <div class="grid">
            {images_html}
        </div>
    </div>
</body>
</html>
"""

    filename = f"mockup_{uuid.uuid4().hex}.html"
    path = os.path.join(MOCKUP_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return path
