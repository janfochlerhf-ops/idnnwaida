import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import BrowserContext, Page, Request, Response, async_playwright

USER_DATA_DIR = ".mafia_profile"
BASE_URL = "https://mafiareborn.com"


class LearnSession:
    """
    PASIVNÍ REŽIM UČENÍ (GAMEPLAY OBSERVER / RECORDER):
    1. Vypne veškerou autonomní aktivitu bota (bot NEKLIKÁ, NEHRAJE, NENAKUPUJE).
    2. Otevře prohlížeč pro lidského hráče s jeho profilem.
    3. Tiše na pozadí monitoruje:
       - Kliknutí hráče (tlačítka, dialogy, sekce, obchody, rodina, gangwar).
       - Navigaci mezi herními stránkami (/game/shops, /game/godfather, /game/gangwar atd.).
       - Síťovou komunikaci a API požadavky/odpovědi (JSON data, parametry soubojů, odměny).
    4. Po ukončení vyexportuje přehledný soubor mafia_learn_export_<timestamp>.json,
       který může hráč poslat vývojáři pro analýzu a doprogramování nových funkcí.
    """

    def __init__(self, log_fn: Callable[[str], None] = print):
        self.log_fn = log_fn
        self.is_recording = False
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.session_data: Dict[str, Any] = {
            "version": "1.0",
            "type": "mafia_reborn_learning_session",
            "started_at": "",
            "ended_at": "",
            "duration_seconds": 0,
            "summary": {
                "total_api_calls": 0,
                "total_clicks": 0,
                "pages_visited": [],
            },
            "routes": [],
            "actions": [],
            "network_calls": [],
        }
        self.visited_pages_set = set()
        self.last_saved_file = ""

    async def _on_request(self, request: Request):
        if not self.is_recording:
            return

        res_type = request.resource_type
        # Ignorujeme obrázky, fonty, styly, media pro čistý a kompaktní log
        if res_type in ["image", "font", "stylesheet", "media"]:
            return

        url = request.url
        if any(ignored in url for ignored in ["google", "sentry", "cloudflare", "analytics", "doubleclick"]):
            return

        post_data = None
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                raw_post = request.post_data
                if raw_post:
                    try:
                        post_data = json.loads(raw_post)
                    except Exception:
                        post_data = raw_post[:10000]
            except Exception:
                pass

        req_entry = {
            "timestamp": datetime.now().isoformat(),
            "method": request.method,
            "url": url,
            "resource_type": res_type,
            "post_data": post_data,
            "response": None,
        }
        setattr(request, "_learn_entry", req_entry)

    async def _on_response(self, response: Response):
        if not self.is_recording:
            return

        request = response.request
        req_entry = getattr(request, "_learn_entry", None)
        if not req_entry:
            return

        url = response.url
        content_type = response.headers.get("content-type", "")
        is_game_api = any(k in url for k in ["/api/", "_server", "trpc", "mafiareborn.com/game"]) or "json" in content_type

        resp_data = None
        if is_game_api:
            try:
                resp_text = await response.text()
                try:
                    resp_data = json.loads(resp_text)
                except Exception:
                    resp_data = resp_text[:4000]
            except Exception:
                pass

        req_entry["response"] = {
            "status": response.status,
            "content_type": content_type,
            "data": resp_data,
        }

        self.session_data["network_calls"].append(req_entry)
        self.session_data["summary"]["total_api_calls"] += 1

        if any(k in url for k in ["/api/", "_server", "trpc"]):
            short_url = url.split("?")[0].replace("https://mafiareborn.com", "")
            self.log_fn(f"[🎓 UČENÍ] Zachycen API požadavek: {request.method} {short_url} (Kód: {response.status})")

    async def _on_framenavigated(self, frame):
        if frame != self.page.main_frame:
            return
        url = frame.url
        if not url.startswith(BASE_URL):
            return

        route = url.replace(BASE_URL, "")
        if not route:
            route = "/"

        self.session_data["routes"].append({
            "timestamp": datetime.now().isoformat(),
            "route": route,
            "url": url,
        })

        if route not in self.visited_pages_set:
            self.visited_pages_set.add(route)
            self.session_data["summary"]["pages_visited"].append(route)
            self.log_fn(f"[🎓 UČENÍ] Hráč vstoupil do sekce: \033[1;36m{route}\033[0m")

    def _on_player_click(self, source, click_json_str: str):
        try:
            click_data = json.loads(click_json_str)
            self.session_data["actions"].append(click_data)
            self.session_data["summary"]["total_clicks"] += 1

            elem_desc = click_data.get("ariaLabel") or click_data.get("text") or click_data.get("tag")
            elem_desc = elem_desc.strip().replace("\n", " ")[:35]
            if elem_desc:
                self.log_fn(f"[🎓 UČENÍ] Kliknutí hráče: '{elem_desc}' na {click_data.get('url', '')}")
        except Exception:
            pass

    async def start_recording(self):
        """Spustí pasivní nahrávání herní relace."""
        self.is_recording = True
        self.session_data["started_at"] = datetime.now().isoformat()

        self.log_fn("\n" + "=" * 65)
        self.log_fn(" 🎓 \033[1;35m[REŽIM UČENÍ SPUŠTĚN]\033[0m")
        self.log_fn("=" * 65)
        self.log_fn(" • Bot je v PASIVNÍM režimu — sám NIC nekliká ani neutrácí.")
        self.log_fn(" • Hraj hru úplně normálně (vyzkoušej obchody, rodinu, souboje, bossy).")
        self.log_fn(" • Veškeré herní mechaniky, kliknutí a API data se zaznamenávají na pozadí.")
        self.log_fn(" • Pro ukončení nahrávání klikni na 'Ukončit záznam a exportovat'.")
        self.log_fn("=" * 65 + "\n")

        async with async_playwright() as p:
            try:
                self.context = await p.chromium.launch_persistent_context(
                    user_data_dir=USER_DATA_DIR,
                    channel="chrome",
                    headless=False,
                    viewport={"width": 1280, "height": 850},
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception:
                self.context = await p.chromium.launch_persistent_context(
                    user_data_dir=USER_DATA_DIR,
                    headless=False,
                    viewport={"width": 1280, "height": 850},
                )

            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

            # Zaregistrujeme posluchače událostí
            self.page.on("request", lambda req: asyncio.create_task(self._on_request(req)))
            self.page.on("response", lambda resp: asyncio.create_task(self._on_response(resp)))
            self.page.on("framenavigated", lambda frame: asyncio.create_task(self._on_framenavigated(frame)))

            # Propojíme JavaScriptový klikací tracker z prohlížeče do Pythonu
            await self.page.expose_binding("__recordPlayerClick", self._on_player_click)

            # Injektujeme posluchač kliknutí do každé načtené stránky
            await self.page.add_init_script("""
                document.addEventListener('click', (e) => {
                    try {
                        let el = e.target;
                        let clickable = el.closest("button, a, [role='button'], img.clickable, div.clickable, div[class*='Button']") || el;
                        const data = {
                            timestamp: new Date().toISOString(),
                            url: window.location.pathname,
                            tag: clickable.tagName.toLowerCase(),
                            id: clickable.id || "",
                            className: (clickable.className || "").toString().slice(0, 50),
                            text: (clickable.innerText || clickable.textContent || "").trim().slice(0, 60),
                            ariaLabel: clickable.getAttribute("aria-label") || "",
                            href: clickable.getAttribute("href") || ""
                        };
                        if (window.__recordPlayerClick) {
                            window.__recordPlayerClick(JSON.stringify(data));
                        }
                    } catch (err) {}
                }, true);
            """)

            # Otevřeme hru
            if BASE_URL not in self.page.url:
                await self.page.goto(BASE_URL)

            # Čekáme dokud hráč neukončí nahrávání
            while self.is_recording:
                await asyncio.sleep(1)

            # Uložíme export
            self.last_saved_file = self.save_export()
            await self.context.close()

    def stop_recording(self) -> str:
        """Zastaví nahrávání a vrátí cestu k vygenerovanému exportnímu souboru."""
        self.is_recording = False
        return self.last_saved_file

    def save_export(self) -> str:
        """Uloží nashromážděná data do JSON souboru."""
        self.session_data["ended_at"] = datetime.now().isoformat()
        try:
            start_dt = datetime.fromisoformat(self.session_data["started_at"])
            end_dt = datetime.fromisoformat(self.session_data["ended_at"])
            self.session_data["duration_seconds"] = int((end_dt - start_dt).total_seconds())
        except Exception:
            pass

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mafia_learn_export_{timestamp_str}.json"
        filepath = os.path.abspath(filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.session_data, f, indent=2, ensure_ascii=False)

        mins = self.session_data["duration_seconds"] // 60
        secs = self.session_data["duration_seconds"] % 60
        self.log_fn("\n" + "=" * 65)
        self.log_fn(" 💾 \033[1;32m[ZÁZNAM UČENÍ BYL ÚSPĚŠNĚ ULOŽEN]\033[0m")
        self.log_fn("=" * 65)
        self.log_fn(f" • Soubor        : \033[1;33m{filename}\033[0m")
        self.log_fn(f" • Doba hraní    : {mins} min {secs} s")
        self.log_fn(f" • Navštíveno    : {len(self.session_data['summary']['pages_visited'])} herních sekcí")
        self.log_fn(f" • Akcí hráče    : {self.session_data['summary']['total_clicks']} kliknutí")
        self.log_fn(f" • API odpovědí  : {self.session_data['summary']['total_api_calls']} zachycených volání")
        self.log_fn("=" * 65)
        self.log_fn(f"👉 Pošli soubor '{filename}' tvůrci bota pro přidání nových funkcí!\n")

        self.last_saved_file = filepath
        return filepath


async def run_standalone_learning():
    """Spustí režim učení přímo z příkazové řádky."""
    session = LearnSession(log_fn=print)
    try:
        await session.start_recording()
    except KeyboardInterrupt:
        session.is_recording = False
        filepath = session.save_export()
        print(f"\n[✓] Záznam ukončen a uložen: {filepath}")


if __name__ == "__main__":
    asyncio.run(run_standalone_learning())
