from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests, re, time
from bs4 import BeautifulSoup
import re
import os  

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

PRUEBA_URL = "https://ssstik.io"
PRUEBA_API = f"{PRUEBA_URL}/abc"
TIKTOK_URL_REGEX = re.compile(r'https://(vm\.tiktok\.com/[\w-]+|www\.tiktok\.com/@[\w.-]+/(photo|video)/\d+)')


def fetch_token():
    try:
        r = requests.get(PRUEBA_URL, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        match = re.search(r's_tt\s*=\s*["\']([^"\']+)["\']', r.text)
        return match.group(1) if match else None
    except:
        return None


def prueba_scrape(url: str):
    if not TIKTOK_URL_REGEX.match(url):
        return {"error": "URL inválida"}

    token = fetch_token()
    if not token:
        return {"error": "No se pudo obtener token"}

    while True:
        try:
            r = requests.post(PRUEBA_API, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": PRUEBA_URL,
                "Referer": f"{PRUEBA_URL}/en",
                "User-Agent": "Mozilla/5.0"
            }, data={
                "id": url,
                "locale": "en",
                "tt": token
            })
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            if soup.select_one("div.panel.notification"):
                return {"error": "No hay contenido disponible"}

            desc = soup.select_one("p.maintext").text.strip() if soup.select_one("p.maintext") else ""
            avatar = soup.select_one("img.result_author")["src"] if soup.select_one("img.result_author") else ""

            if avatar:
                avatar = re.sub(r'/\d+x\d+/', '/720x720/', avatar)

            nickname = soup.select_one("h2").text.strip() if soup.select_one("h2") else ""
            music = soup.select_one("a.music")["href"] if soup.select_one("a.music") else ""

            images = [a["href"] for a in soup.select("ul.splide__list > li a")]
            video = soup.select_one("a.without_watermark")["href"] if soup.select_one("a.without_watermark") else ""

            return {
                "desc": desc,
                "avatar": avatar,
                "nickname": nickname,
                "music": music,
                "images": images,
                "video": video
            }

        except:
            return {"error": "Falló la descarga"}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, url: str = ""):
    result = None
    error = None
    if url:
        response = prueba_scrape(url)
        if "error" in response:
            error = response["error"]
        else:
            result = response
    return templates.TemplateResponse("index.html", {"request": request, "result": result, "error": error})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)