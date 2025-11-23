from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, Response, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import os
import re
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

app = FastAPI()

# Static & templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Config SEO ---
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://ssstikvid.com").rstrip("/")

# --- Scraper config ---
PRUEBA_URL = "https://ssstik.io"
PRUEBA_API = f"{PRUEBA_URL}/abc"
TIKTOK_URL_REGEX = re.compile(
    r'https://(vt\.tiktok\.com/[\w-]+|vm\.tiktok\.com/[\w-]+|www\.tiktok\.com/@([\w.-]+)/(photo|video)/\d+)'
)


# =========================
# Infra: Proxy de video
# =========================
@app.get("/video_proxy")
def video_proxy(video_url: str = Query(..., description="URL directa del video MP4 de TikTok")):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    r = requests.get(video_url, headers=headers, stream=True, timeout=20)
    content_length = r.headers.get("Content-Length")

    return StreamingResponse(
        r.raw,
        media_type="video/mp4",
        headers={
            "Content-Disposition": "inline",
            "Content-Length": content_length or "",
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=31536000",
        },
    )

@app.get("/image_proxy")
def image_proxy(image_url: str = Query(..., description="URL directa de la imagen de TikTok")):
    """
    Proxy robusto para imágenes de TikTok con manejo de errores y cabeceras correctas.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.tiktok.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    try:
        r = requests.get(image_url, headers=headers, stream=True, timeout=15)
        r.raise_for_status()

        # Determinar tipo MIME
        media_type = r.headers.get("Content-Type", "image/jpeg")
        content_length = r.headers.get("Content-Length")

        # En algunos casos TikTok devuelve HTML en vez de imagen
        if "text/html" in media_type:
            raise ValueError(f"Respuesta no válida desde TikTok ({media_type})")

        # Responder la imagen correctamente
        return StreamingResponse(
            r.iter_content(chunk_size=8192),
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Length": content_length or "",
            },
        )
    except Exception as e:
        print(f"❌ Error en /image_proxy: {e}")
        return Response(content=f"Error al cargar imagen: {e}", status_code=502)


# =========================
# SEO: sitemap.xml & robots.txt
# =========================
@app.get("/sitemap.xml", response_class=Response)
async def sitemap() -> Response:
    """Sitemap sencillo pero SEO-friendly."""
    today = datetime.now(timezone.utc).date().isoformat()

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{PUBLIC_BASE_URL}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""
    return Response(content=xml_content.strip(), media_type="application/xml")


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> PlainTextResponse:
    """Robots.txt para permitir indexación y anunciar el sitemap."""
    content = f"""User-agent: *
Allow: /

Sitemap: {PUBLIC_BASE_URL}/sitemap.xml
"""
    return PlainTextResponse(content.strip())


# =========================
# Utilidades de scraping
# =========================
def fetch_token() -> str | None:
    try:
        r = requests.get(PRUEBA_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        match = re.search(r's_tt\s*=\s*["\']([^"\']+)["\']', r.text)
        return match.group(1) if match else None
    except Exception:
        return None


def obtener_avatar_hd(usuario: str) -> str | None:
    try:
        perfil_url = f"https://www.tiktok.com/@{usuario}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(perfil_url, headers=headers, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            img_tag = soup.find("img", {"alt": re.compile(rf"@{usuario}")})
            if img_tag and img_tag.get("src"):
                return img_tag["src"]
    except Exception:
        pass
    return None


def prueba_scrape(url: str) -> dict:
    match = TIKTOK_URL_REGEX.match(url)
    if not match:
        return {"error": "Enlace de TikTok inválido. Asegúrate de copiar el enlace completo desde la app."}

    usuario = match.group(2)
    token = fetch_token()
    if not token:
        return {"error": "No se pudo obtener token. Intenta de nuevo en unos segundos."}

    try:
        r = requests.post(
            PRUEBA_API,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": PRUEBA_URL,
                "Referer": f"{PRUEBA_URL}/en",
                "User-Agent": "Mozilla/5.0",
            },
            data={
                "id": url,
                "locale": "en",
                "tt": token,
            },
            timeout=20,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        if soup.select_one("div.panel.notification"):
            return {"error": "No hay contenido disponible para este enlace de TikTok."}

        desc = soup.select_one("p.maintext").text.strip() if soup.select_one("p.maintext") else ""
        avatar = soup.select_one("img.result_author")["src"] if soup.select_one("img.result_author") else ""
        nickname = soup.select_one("h2").text.strip() if soup.select_one("h2") else ""
        music = soup.select_one("a.music")["href"] if soup.select_one("a.music") else ""
        # Extraer imágenes (maneja varios formatos)
        images = []
        for li in soup.select("ul.splide__list > li"):
            # Intentar con enlace <a href>
            a_tag = li.find("a")
            if a_tag and a_tag.get("href"):
                images.append(a_tag["href"])
                continue

            # Intentar con <img src> o data-src
            img_tag = li.find("img")
            if img_tag:
                if img_tag.get("src"):
                    images.append(img_tag["src"])
                elif img_tag.get("data-src"):
                    images.append(img_tag["data-src"])

        video = soup.select_one("a.without_watermark")["href"] if soup.select_one("a.without_watermark") else ""

        if usuario:
            avatar_hd = obtener_avatar_hd(usuario)
            if avatar_hd:
                avatar = avatar_hd

        if not video and not images:
            return {
                "error": "Estás descargando demasiado rápido. Espera unos segundos antes de volver a intentarlo."
            }

        if not nickname or not avatar:
            return {"error": "No se pudo obtener información del perfil de TikTok."}

        return {
            "desc": desc,
            "avatar": avatar,
            "nickname": nickname,
            "music": music,
            "images": images,
            "video": video,
        }

    except Exception as e:
        return {"error": f"Falló la descarga: {str(e)}"}


# =========================
# Página principal
# =========================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, url: str = "") -> HTMLResponse:
    result: dict | None = None
    error: str | None = None

    if url:
        response = prueba_scrape(url.strip())
        if "error" in response:
            error = response["error"]
        else:
            result = response

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "result": result,
            "error": error,
        },
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
