import asyncio
import json
import os
import random
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from playwright.async_api import BrowserContext, Page, async_playwright

USER_DATA_DIR = ".mafia_profile"
CONFIG_FILE = "config.json"
BASE_URL = "https://mafiareborn.com"
GODFATHER_URL = "https://mafiareborn.com/game/godfather"
SURVIVAL_URL = "https://mafiareborn.com/game/duel/survival"
DUEL_URL = "https://mafiareborn.com/game/duel"
CHARACTER_URL = "https://mafiareborn.com/game/character"
POLICE_URL = "https://mafiareborn.com/game/police"

BANNER = r"""
  __  __       __ _         ____       _                      
 |  \/  | __ _/ _(_) __ _  |  _ \  ___| |__   ___  _ __ _ __  
 | |\/| |/ _` | |_| |/ _` | | |_) |/ _ \ '_ \ / _ \| '__| '_ \ 
 | |  | | (_| |  _| | (_| | |  _ <|  __/ |_) | (_) | |  | | | |
 |_|  |_|\__,_|_| |_|\__,_| |_| \_\\___|_.__/ \___/|_|  |_| |_|
                                                               
             BETA v0.9 — Police Encounter & Smart Skill System
             • 100% spolehlivá detekce Zlaťáků, Hotovosti, Energie a Levelu
             • Automatický souboj s policií a SWAT po misích i aktivitách
             • Inteligentní Auto-Skill s přísnou finanční rezervou
             • Chytrý výběr misí (Max XP a předměty)
             • Aréna Survival, PvP Duely a Discord Webhook
"""

QUEST_GIVERS = [
    # New York
    {"id": "velvet", "name": "Velvet Kiss", "selector": "img.clickable[src*='velvet']"},
    {"id": "vincenzo", "name": "Vincenzo", "selector": "img.clickable[src*='vincenzo']"},
    {"id": "sean", "name": "Sean", "selector": "img.clickable[src*='sean']"},
    # Miami
    {"id": "isabel", "name": "Isabel", "selector": "img.clickable[src*='isabel']"},
    {"id": "dwayne", "name": "Dwayne", "selector": "img.clickable[src*='dwayne']"},
    {"id": "jose", "name": "José", "selector": "img.clickable[src*='jose']"},
    # Chinatown / Hong Kong
    {"id": "mei", "name": "Amaya (Mei)", "selector": "img.clickable[src*='mei']"},
    {"id": "chow", "name": "Mihn (Madam Chow)", "selector": "img.clickable[src*='chow']"},
    {"id": "wing", "name": "Akuma (Wing)", "selector": "img.clickable[src*='wing']"},
]

NON_QUEST_NPCS = ["cookie", "agatha", "carlos", "little_joe", "ah_keung", "suki"]


def load_config() -> Dict[str, Any]:
    """Načte konfiguraci ze souboru config.json."""
    default_config = {
        "discord_webhook_url": "",
        "auto_survival": True,
        "auto_duels": True,
        "auto_police": True,
        "quest_strategy": "max_xp",
        "update_url": "",
        "auto_update": True,
        "version": "1.0.0",
        "smart_skills": {
            "enabled": True,
            "mode": "smart_budget",  # 'smart_budget', 'free_only', nebo false
            "min_cash_reserve": 2000,  # Finanční rezerva, pod kterou bot NIKDY nejde
            "max_spend_percent": 25,  # Maximálně 25% hotovosti za cyklus
            "max_points_per_cycle": 1,  # Max 1 placený bod za cyklus
        },
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_config.update(loaded)
        except Exception:
            pass
    else:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
    return default_config


def save_config(config: Dict[str, Any]) -> None:
    """Uloží aktuální konfiguraci do souboru config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print("💾 \033[1;32m[Nastavení bylo úspěšně uloženo do config.json]\033[0m")
    except Exception as e:
        print(f"[⚠️] Nepodařilo se uložit config.json: {e}")


def configure_smart_skills_menu(config: Dict[str, Any]) -> Dict[str, Any]:
    """Podmenu pro konfiguraci Smart-Skill systému s bezpečnostním varováním."""
    if "smart_skills" not in config:
        config["smart_skills"] = {
            "enabled": True,
            "mode": "smart_budget",
            "min_cash_reserve": 2000,
            "max_spend_percent": 25,
            "max_points_per_cycle": 1,
        }

    skill_cfg = config["smart_skills"]

    while True:
        print("\n" + "-" * 65)
        print(" ⚠️   \033[1;33mVAROVÁNÍ K FUNKCI SMART-SKILL (VYLEPŠOVÁNÍ ATRIBUTŮ):\033[0m")
        print("-" * 65)
        print(" V beta verzi Mafia Reborn stojí nákup atributového bodu $1,500.")
        print(" Pokud bot nakupuje body příliš často, může rychle utratit hotovost.")
        print(" Doporučené možnosti:")
        print("  • [1] Chytrý rozpočet: Bot drží rezervu (např. $2,000) a utratí max 25 %.")
        print("  • [2] Pouze body ZDARMA: Utrácí $0! Bere pouze volné body z Level Upu.")
        print("  • [3] Úplně vypnuto: Bot na atributy vůbec nesáhne, trénuješ sám.")
        print("-" * 65)

        cur_mode = "Chytrý rozpočet" if skill_cfg.get("mode") == "smart_budget" else "Pouze zdarma"
        status_str = f"ZAPNUTO ({cur_mode})" if skill_cfg.get("enabled", True) else "VYPNUTO"
        print(f" Aktuální stav: \033[1;32m{status_str}\033[0m")
        print(" [1] ZAPNOUT Chytrý rozpočet (drží bezpečnou finanční rezervu)")
        print(" [2] POUZE BODY ZDARMA z Level Upu ($0 útrata)")
        print(" [3] ÚPLNĚ VYPNUT (žádné automatické trénování)")
        print(" [4] Změnit % limit útraty za cyklus (aktuálně: {} %)".format(skill_cfg.get("max_spend_percent", 25)))
        print(" [0] Zpět do hlavního menu")
        print("-" * 65)

        sub = input("Tvá volba [1-4, nebo 0]: ").strip()
        if sub == "1":
            skill_cfg["enabled"] = True
            skill_cfg["mode"] = "smart_budget"
            print("✓ Nastaven Chytrý rozpočet.")
            break
        elif sub == "2":
            skill_cfg["enabled"] = True
            skill_cfg["mode"] = "free_only"
            print("✓ Nastaveno utrácení pouze bodů ZDARMA ($0).")
            break
        elif sub == "3":
            skill_cfg["enabled"] = False
            print("✓ Smart-Skill systém byl VYPNUT.")
            break
        elif sub == "4":
            p = input("Zadej max % útraty z hotovosti za cyklus (1-50): ").strip()
            if p.isdigit() and 1 <= int(p) <= 50:
                skill_cfg["max_spend_percent"] = int(p)
                print(f"✓ Nastaven limit útraty na {p} %.")
        elif sub == "0" or sub == "":
            break

    config["smart_skills"] = skill_cfg
    return config


def terminal_settings_menu(config: Dict[str, Any]) -> Dict[str, Any]:
    """Interaktivní nastavení bota přímo v terminálu před spuštěním."""
    # Pokud není terminál interaktivní nebo je předán flag pro okamžitý start
    if not sys.stdin.isatty() or "--now" in sys.argv or "-y" in sys.argv or "--auto" in sys.argv:
        return config

    while True:
        print("\n" + "=" * 65)
        print(" ⚙️   \033[1;36mINTERAKTIVNÍ NASTAVENÍ BOTA (Terminal Control Panel)\033[0m")
        print("=" * 65)

        # 1. Survival
        surv_status = "\033[1;32m[✓] ZAPNUTO\033[0m" if config.get("auto_survival", True) else "\033[1;31m[✗] VYPNUTO\033[0m"
        print(f" [1] Aréna Survival       : {surv_status}")

        # 2. Duely
        duel_status = "\033[1;32m[✓] ZAPNUTO\033[0m" if config.get("auto_duels", True) else "\033[1;31m[✗] VYPNUTO\033[0m"
        print(f" [2] PvP Duely            : {duel_status}")

        # 3. Policie
        police_status = "\033[1;32m[✓] ZAPNUTO (Boj o odznaky)\033[0m" if config.get("auto_police", True) else "\033[1;31m[✗] VYPNUTO\033[0m"
        print(f" [3] Policie & SWAT       : {police_status}")

        # 4. Smart Skills
        skill_cfg = config.get("smart_skills", {})
        enabled = skill_cfg.get("enabled", True)
        mode = skill_cfg.get("mode", "smart_budget")
        reserve = skill_cfg.get("min_cash_reserve", 2000)
        pct = skill_cfg.get("max_spend_percent", 25)

        if not enabled:
            skill_status = "\033[1;31m[✗] VYPNUTO (Žádné vylepšování)\033[0m"
        elif mode == "free_only":
            skill_status = "\033[1;33m[⚡] POUZE BODY ZDARMA ($0 útrata)\033[0m"
        else:
            skill_status = f"\033[1;32m[✓] CHYTRÝ ROZPOČET\033[0m (Rezerva ${reserve:,}, max {pct}%)"
        print(f" [4] Smart-Skill systém   : {skill_status}")

        # 5. Quest strategie
        strat = config.get("quest_strategy", "max_xp")
        strat_names = {
            "max_xp": "Maximální XP (nejrychlejší postup)",
            "max_cash": "Maximální peníze ($$$)",
            "balanced": "Vyvážená (XP + peníze)",
        }
        print(f" [5] Strategie výběru misí: \033[1;36m{strat_names.get(strat, strat)}\033[0m")

        # 6. Discord Webhook
        webhook = config.get("discord_webhook_url", "").strip()
        wh_status = f"\033[1;32m[✓] Nastaven ({webhook[:35]}...)\033[0m" if webhook else "\033[1;33m[✗] Nenastaven\033[0m"
        print(f" [6] Discord Webhook      : {wh_status}")

        # 7. Finanční rezerva
        print(f" [7] Minimální rezerva $  : \033[1;32m${reserve:,}\033[0m")

        # 8. Režim učení
        print(" [8] 🎓 Režim učení       : \033[1;35mSpustit pasivní záznam hraní pro analýzu\033[0m")

        # 9. Aktualizace
        update_url = config.get("update_url", "")
        up_status = f"\033[1;32m[✓] Nastavena\033[0m" if update_url else "\033[1;33m[✗] Nenastavena\033[0m"
        print(f" [9] 🔄 Auto-Update URL   : {up_status}")

        print("=" * 65)
        print(" 🚀 Stiskni \033[1;32m[ENTER]\033[0m pro okamžité spuštění bota")
        print(" 🔧 Zadej číslo volby \033[1;33m[1-9]\033[0m pro změnu (nebo \033[1;31m'q'\033[0m pro ukončení)")
        print("=" * 65)

        try:
            choice = input("\n👉 Tvá volba [ENTER pro start]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nUkončeno uživatelem.")
            sys.exit(0)

        if choice == "" or choice == "s" or choice == "start":
            print("\n🚀 Spouštím bota...")
            break
        elif choice == "q" or choice == "exit":
            print("\nNashledanou!")
            sys.exit(0)
        elif choice == "1":
            config["auto_survival"] = not config.get("auto_survival", True)
            save_config(config)
        elif choice == "2":
            config["auto_duels"] = not config.get("auto_duels", True)
            save_config(config)
        elif choice == "3":
            config["auto_police"] = not config.get("auto_police", True)
            save_config(config)
        elif choice == "4":
            config = configure_smart_skills_menu(config)
            save_config(config)
        elif choice == "5":
            print("\nVýběr strategie pro mise:")
            print(" [1] Maximální XP (nejrychlejší levelování)")
            print(" [2] Maximální hotovost (pro získání peněz)")
            print(" [3] Vyvážená strategie (XP + peníze)")
            sub = input("Zvol strategii [1-3]: ").strip()
            if sub == "1":
                config["quest_strategy"] = "max_xp"
            elif sub == "2":
                config["quest_strategy"] = "max_cash"
            elif sub == "3":
                config["quest_strategy"] = "balanced"
            save_config(config)
        elif choice == "6":
            print(f"\nAktuální Discord Webhook: {config.get('discord_webhook_url', 'Nenastaven')}")
            new_url = input("Zadej novou Webhook URL (stiskni ENTER pro zachování / mezeru pro smazání): ").strip()
            if new_url == " ":
                config["discord_webhook_url"] = ""
            elif new_url:
                config["discord_webhook_url"] = new_url
            save_config(config)
        elif choice == "7":
            cur_reserve = config.get("smart_skills", {}).get("min_cash_reserve", 2000)
            print(f"\nAktuální finanční rezerva: ${cur_reserve:,}")
            val = input("Zadej novou minimální částku rezervy v $ (např. 2000): ").strip()
            if val.isdigit():
                if "smart_skills" not in config:
                    config["smart_skills"] = {}
                config["smart_skills"]["min_cash_reserve"] = int(val)
                save_config(config)
        elif choice == "8":
            from learn_mode import run_standalone_learning
            asyncio.run(run_standalone_learning())
            break
        elif choice == "9":
            from updater import check_for_updates, apply_update
            cur_url = config.get("update_url", "")
            print(f"\nAktuální Update URL: {cur_url or 'Nenastavena'}")
            new_u = input("Zadej novou Update URL (stiskni ENTER pro zachování / mezeru pro smazání): ").strip()
            if new_u == " ":
                config["update_url"] = ""
            elif new_u:
                config["update_url"] = new_u
            save_config(config)

            if config.get("update_url"):
                print("Kontroluji aktualizace...")
                has_up, msg, manifest = check_for_updates(config)
                print(msg)
                if has_up and manifest:
                    ans = input("Chcete aktualizaci nyní nainstalovat? [A/n]: ").strip().lower()
                    if ans in ["a", "ano", "y", "yes", ""]:
                        ok, r_msg = apply_update(manifest, config)
                        print(r_msg)

    return config


def clear_line():
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def format_progress_bar(current: int, total: int, width: int = 16) -> str:
    if total <= 0:
        return "[" + "█" * width + "]"
    progress = max(0.0, min(1.0, current / total))
    filled = int(progress * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {int(progress * 100)}%"


async def send_discord_webhook(
    webhook_url: str,
    title: str,
    description: str,
    color: int = 0x2ECC71,
    fields: Optional[List[Dict[str, Any]]] = None,
):
    """Odešle asynchronní embed notifikaci na Discord webhook."""
    if not webhook_url or not webhook_url.startswith("http"):
        return
    try:
        payload = {
            "username": "Mafia Reborn Bot",
            "avatar_url": "https://mafiareborn.com/assets/logo_banner-YLljPq5Q.svg",
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                    "fields": fields or [],
                    "footer": {"text": "Mafia Reborn Bot • v0.8"},
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            ],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ):
                pass
    except Exception:
        pass


class MafiaBot:
    def __init__(self, page: Page, context: BrowserContext, config: Dict[str, Any]):
        self.page = page
        self.context = context
        self.config = config
        self.webhook_url = config.get("discord_webhook_url", "").strip()

        # Přesné časy dalších povolených kontrol vedlejších aktivit
        # Při startu počkáme pár vteřin, ať bot nejprve zkontroluje stav a vezme quest
        now = time.time()
        self.next_survival_available = now + 25.0
        self.next_duel_available = now + 15.0
        self.next_skill_available = now + 45.0
        self.last_known_level = 0
        self.last_known_cash = 0
        self.last_known_energy = 100.0
        self.is_running = True

    def stop(self):
        """Zastaví hlavní smyčku bota."""
        self.is_running = False

    async def ensure_on_main_game(self):
        """Ověří, že jsme na platné herní obrazovce a odstraní případné 404 nebo dialogy."""
        try:
            content = await self.page.content()
            if "page you are looking for does not exist" in content.lower():
                print("-> Nalezena chybová stránka (404). Vracím se do hry...")
                start_over_btn = self.page.locator(
                    "button:has-text('START OVER'), button:has-text('GO BACK'), a:has-text('START OVER')"
                ).first
                if await start_over_btn.is_visible():
                    await start_over_btn.click()
                else:
                    await self.page.goto(GODFATHER_URL)
                await self.page.wait_for_timeout(2000)

            await self.close_community_notice()
        except Exception:
            pass

    async def close_community_notice(self):
        """Zavře dialogy jako Community Notice nebo Level Up pokud se objeví na obrazovce."""
        try:
            modal_close = self.page.locator(
                "div[role='dialog'] button[aria-label='Close'], div[role='dialog'] button:has-text('Close'), div[role='dialog'] button:has-text('Okay'), div[class*='Modal'] button[aria-label='Close'], div[class*='Modal'] button:has-text('Okay')"
            ).first
            if await modal_close.is_visible():
                await modal_close.click()
                await self.page.wait_for_timeout(600)
        except Exception:
            pass

    async def wait_for_login(self):
        """Zkontroluje stav přihlášení a v případě potřeby počká na uživatele."""
        print("-> Kontroluji stav relace hráče...")
        await self.page.goto(BASE_URL)
        await self.page.wait_for_timeout(3000)

        await self.ensure_on_main_game()

        if "/onboard" in self.page.url:
            print("\n" + "=" * 65)
            print(" [KROK 1] PŘIHLÁŠENÍ DO HRY V PROHLÍŽEČI")
            print("=" * 65)
            print("-> V otevřeném okně Chrome se přihlas ke svému účtu.")
            print("-> Jakmile tě hra pustí do hry, bot okamžitě převezme řízení!\n")

            while "/onboard" in self.page.url:
                sys.stdout.write("\r  💤 Čekám na dokončení přihlášení v prohlížeči...")
                sys.stdout.flush()
                await asyncio.sleep(2)

            clear_line()

        print("\n[✓] ÚSPĚCH! Relace Mafia Reborn je aktivní.")
        if "/game/godfather" not in self.page.url:
            await self.page.goto(GODFATHER_URL)
        await self.page.wait_for_timeout(2500)
        await self.ensure_on_main_game()

        stats = await self.get_player_stats()
        print(
            f"-> Gangster: \033[1;32mLevel {stats['level']}\033[0m | Energie: \033[1;33m{stats['energy']}\033[0m | Hotovost: \033[1;32m${stats['cash']:,}\033[0m | Zlaťáky: \033[1;33m{stats['gold']:,}\033[0m"
        )
        if self.webhook_url:
            print("[🔔 DISCORD] Webhook notifikace jsou aktivní!")
            await send_discord_webhook(
                self.webhook_url,
                "🚀 Mafia Reborn Bot spuštěn",
                "Bot úspěšně zahájil autonomní hraní.",
                color=0x3498DB,
                fields=[
                    {"name": "Level", "value": str(stats["level"]), "inline": True},
                    {"name": "Energie", "value": str(stats["energy"]), "inline": True},
                    {"name": "Hotovost", "value": f"${stats['cash']:,}", "inline": True},
                    {"name": "Zlaťáky", "value": f"{stats['gold']:,}", "inline": True},
                ],
            )

    async def get_player_stats(self) -> Dict[str, Any]:
        """
        Přečte 100% PŘESNÉ statistiky hráče (Level, Energie, Zlaťáky, Hotovost)
        přímo z DOM prvků horní lišty (HUD) Mafia Reborn.
        """
        stats = {
            "level": self.last_known_level or 1,
            "energy": 100.0,
            "gold": 0,
            "cash": 0,
            "rank": "—",
        }
        try:
            dom_data = await self.page.evaluate(
                """() => {
                const res = {
                    level: null,
                    energy: null,
                    gold: null,
                    cash: null,
                    rank: null
                };

                // 1. LEVEL: Avatar box v levém horním rohu
                const links = Array.from(document.querySelectorAll("a[href*='/character'], a[href*='character']"));
                const avatarBox = links.find(el => {
                    const r = el.getBoundingClientRect();
                    return r.top < 120 && r.left < 250 && r.width > 20;
                });
                if (avatarBox) {
                    const text = (avatarBox.innerText || "").trim();
                    const digits = text.split(/\\s+/).filter(t => /^\\d+$/.test(t));
                    if (digits.length > 0) {
                        res.level = parseInt(digits[digits.length - 1], 10);
                    }
                }

                // 2. ENERGIE: Hledáme "Energy: X" v textu
                const bodyText = document.body.innerText || "";
                const mEnergy = bodyText.match(/Energy:\\s*([\\d\\.]+)/i);
                if (mEnergy) {
                    res.energy = parseFloat(mEnergy[1]);
                }

                // 3. HOTOVOST, ZLAŤÁKY A RANK V HORNÍ LIŠTĚ (HUD)
                const rankingLink = document.querySelector("a[href*='/ranking'], a[aria-label*='ranking']");
                if (rankingLink) {
                    let parent = rankingLink.parentElement;
                    while (parent && parent !== document.body) {
                        const children = Array.from(parent.children);
                        if (children.length === 3) {
                            // Box 0: Gold (např. 1,530)
                            const gText = children[0].innerText.replace(/[^\\d]/g, '');
                            if (gText) res.gold = parseInt(gText, 10);

                            // Box 1: Cash (např. 1,423)
                            const cText = children[1].innerText.replace(/[^\\d]/g, '');
                            if (cText) res.cash = parseInt(cText, 10);

                            // Box 2: Rank (např. 7,454)
                            const rText = children[2].innerText.replace(/[^\\d]/g, '');
                            if (rText) res.rank = rText;

                            break;
                        }
                        parent = parent.parentElement;
                    }
                }

                // Robustní záložní detekce přes obrázek cash
                if (res.cash === null) {
                    const cashImgs = Array.from(document.querySelectorAll("img[src*='cash']"));
                    const topCashImg = cashImgs.find(img => img.getBoundingClientRect().top < 120);
                    if (topCashImg) {
                        let el = topCashImg;
                        while (el && el !== document.body) {
                            if (el.parentElement && el.parentElement.children.length === 3) {
                                const boxes = Array.from(el.parentElement.children);
                                const gText = boxes[0].innerText.replace(/[^\\d]/g, '');
                                if (gText && res.gold === null) res.gold = parseInt(gText, 10);
                                const cText = boxes[1].innerText.replace(/[^\\d]/g, '');
                                if (cText) res.cash = parseInt(cText, 10);
                                const rText = boxes[2].innerText.replace(/[^\\d]/g, '');
                                if (rText && res.rank === null) res.rank = rText;
                                break;
                            }
                            el = el.parentElement;
                        }
                    }
                }

                // Fallback pro Zlaťáky (Gold) přes tlačítko '+' v horní liště
                if (res.gold === null) {
                    const plusImgs = Array.from(document.querySelectorAll("img.clickable, [class*='clickable']"));
                    const topPlus = plusImgs.find(el => {
                        const rect = el.getBoundingClientRect();
                        return rect.top < 120 && rect.width > 0;
                    });
                    if (topPlus) {
                        let el = topPlus;
                        while (el && el !== document.body) {
                            const text = el.innerText ? el.innerText.replace(/[^\\d]/g, '') : '';
                            if (text.length > 0) {
                                const num = parseInt(text, 10);
                                if (!isNaN(num) && num > 0) {
                                    res.gold = num;
                                    break;
                                }
                            }
                            el = el.parentElement;
                        }
                    }
                }

                return res;
            }"""
            )

            if dom_data.get("level") is not None and dom_data["level"] > 0:
                stats["level"] = max(stats["level"], int(dom_data["level"]))
            if dom_data.get("energy") is not None:
                stats["energy"] = float(dom_data["energy"])
            if dom_data.get("gold") is not None:
                stats["gold"] = int(dom_data["gold"])
            if dom_data.get("cash") is not None:
                stats["cash"] = int(dom_data["cash"])
            if dom_data.get("rank") is not None:
                stats["rank"] = dom_data["rank"]

            # Uložíme hotovost pro finanční kalkulace
            self.last_known_cash = stats["cash"]

            # Detekce Level Upu - striktně jednorázová!
            curr_lvl = stats["level"]
            if self.last_known_level > 0 and curr_lvl > self.last_known_level:
                print(f"\n🎉 \033[1;32m[LEVEL UP] Gratulace! Postoupil jsi na úroveň {curr_lvl}!\033[0m")
                self.last_known_level = curr_lvl  # Okamžitě aktualizujeme last_known_level!
                if self.webhook_url:
                    await send_discord_webhook(
                        self.webhook_url,
                        "🆙 Postup na nový Level!",
                        f"Tvůj gangster postoupil na **Level {curr_lvl}**! 🍾",
                        color=0xF1C40F,
                    )
                # Naplánujeme kontrolu skillů na další tah (žádné rekurzivní volání!)
                self.next_skill_available = 0.0
            elif self.last_known_level == 0 and curr_lvl > 0:
                self.last_known_level = curr_lvl

        except Exception:
            pass
        return stats

    async def handle_duel_screen(self, context_name: str = "mise") -> bool:
        """Zpracuje soubojovou obrazovku (Skip -> Okay)."""
        print(f"\n[⚔️ SOUBOJ] Probíhá vyhodnocení souboje ({context_name})...")
        await asyncio.sleep(0.5)

        # Čekáme na Skip (může chvíli trvat, např. animace round banneru v Survivalu trvá 2-3s)
        skip_btn = self.page.locator("button:has-text('Skip')").first
        for _ in range(25):  # Až 12.5 sekundy
            if await skip_btn.is_visible():
                print("-> Klikám na 'Skip' pro okamžité přeskočení animace...")
                await asyncio.sleep(random.uniform(0.3, 0.6))
                try:
                    await skip_btn.click()
                except Exception:
                    pass
                await self.page.wait_for_timeout(1000)
                break
            # Kontrola, zda už se neobjevil Okay (pokud byl souboj okamžitý)
            if await self.page.locator("button:has-text('Okay')").first.is_visible():
                break
            await asyncio.sleep(0.5)

        okay_btn = self.page.locator("button:has-text('Okay')").first
        for _ in range(20):  # Až 10 sekund
            if await okay_btn.is_visible():
                print("[🏆] Souboj dokončen! Vyzvedávám odměnu (tlačítko 'Okay')...")
                await asyncio.sleep(random.uniform(0.4, 0.8))
                try:
                    await okay_btn.click()
                except Exception:
                    pass
                print("[✓] Odměna byla úspěšně připsána!")
                await self.page.wait_for_timeout(2000)

                # Kontrola, zda se po potvrzení odměny neobjevilo policejní přepadení (/game/police)
                if "/police" in self.page.url or await self.is_police_encounter_visible():
                    print("\n[🚨] Po souboji se objevilo policejní přepadení!")
                    await self.handle_police_encounter()

                return True
            await asyncio.sleep(0.5)

        return False

    async def is_police_encounter_visible(self) -> bool:
        """Zkontroluje, zda se na obrazovce nachází policejní přepadení nebo souboj s policií."""
        try:
            return await self.page.evaluate(
                """() => {
                if (window.location.pathname.includes('/police')) return true;
                const encounter = document.querySelector("section[aria-label*='Police encounter'], section[aria-label*='Police fight result']");
                if (encounter) return true;
                const text = document.body ? document.body.innerText : "";
                return text.includes("WATCH OUT! POLICE!") || text.includes("WATCH OUT! SWAT!");
            }"""
            )
        except Exception:
            return False

    async def handle_police_encounter(self) -> bool:
        """
        AUTOMATICKÝ SOUBOJ S POLICIÍ (POLICE ENCOUNTER):
        1. Detekuje policejní přepadení (běžný policista nebo SWAT).
        2. Vždy zvolí 'Attack' (zahájí souboj o bonusy a policejní odznaky).
        3. Přeskočí animaci souboje ('Skip').
        4. Vyzvedne a potvrdí odměnu / výsledek ('Okay').
        5. Případně uzavře dialog kauce ('Post bail') při prohře.
        6. Vrátí se čistě zpět ke Kmotrovi (/game/godfather).
        """
        if not self.config.get("auto_police", True):
            print("\n[ℹ️] Policejní přepadení ignorováno (v configu je 'auto_police' vypnuto).")
            return False

        print("\n" + "=" * 65)
        print(" 🚨 \033[1;31m[POLICEJNÍ PŘEPADENÍ DETEKOVÁNO]\033[0m")
        print("=" * 65)

        try:
            # 1. Zjistíme podrobnosti o nepříteli a odměně
            encounter_data = await self.page.evaluate(
                """() => {
                const info = {
                    title: "Policie",
                    is_swat: false,
                    details: ""
                };
                const bodyText = document.body ? document.body.innerText : "";
                if (bodyText.includes("SWAT")) {
                    info.is_swat = true;
                    info.title = "Zásahová jednotka SWAT";
                } else if (bodyText.includes("POLICE")) {
                    info.title = "Policejní hlídka";
                }
                const encSection = document.querySelector("section[aria-label*='Police encounter']");
                if (encSection) {
                    const lines = Array.from(encSection.querySelectorAll("p, div, h1, h2, h3"))
                        .map(el => el.innerText.trim())
                        .filter(Boolean);
                    info.details = lines.slice(0, 4).join(" | ");
                }
                return info;
            }"""
            )

            enemy_title = encounter_data.get("title", "Policie")
            print(f"-> 👮 Typ přepadení: \033[1;33m{enemy_title}\033[0m")
            print("-> Gangster se nevzdává! Jdeme do souboje (klikám na 'Attack')...")

            if self.webhook_url:
                await send_discord_webhook(
                    self.webhook_url,
                    f"🚨 Policejní přepadení: {enemy_title}!",
                    "Po dokončení aktivity vyskočila policie. Bot automaticky zahajuje souboj!",
                    color=0xE74C3C,
                    fields=[
                        {"name": "Nepřítel", "value": enemy_title, "inline": True},
                        {"name": "Reakce", "value": "⚔️ Útok (Attack)", "inline": True},
                    ],
                )

            # 2. Klikneme na tlačítko 'Attack' (pokud jsme ve fázi výběru)
            attack_clicked = await self.page.evaluate(
                """() => {
                const btn = Array.from(document.querySelectorAll("button")).find(b => {
                    const txt = b.innerText.trim().toLowerCase();
                    return txt === "attack";
                });
                if (btn && !btn.disabled) {
                    btn.click();
                    return true;
                }
                return false;
            }"""
            )

            if attack_clicked:
                print("-> [⚔️] Tlačítko 'Attack' stisknuto! Čekám na zahájení souboje...")
                await self.page.wait_for_timeout(2000)
            else:
                # Možná už souboj běží nebo je načten
                print("-> Tlačítko 'Attack' nebylo potřeba (souboj už probíhá).")

            # 3. Přeskočíme animaci souboje (Skip)
            skip_btn = self.page.locator("button:has-text('Skip')").first
            for _ in range(25):  # Až 12.5 s
                if await skip_btn.is_visible():
                    print("-> Klikám na 'Skip' pro okamžité přeskočení animace policejního souboje...")
                    await asyncio.sleep(random.uniform(0.3, 0.6))
                    try:
                        await skip_btn.click()
                    except Exception:
                        pass
                    await self.page.wait_for_timeout(1000)
                    break
                if await self.page.locator("button:has-text('Okay')").first.is_visible():
                    break
                await asyncio.sleep(0.5)

            # 4. Potvrdíme výsledek souboje (tlačítko 'Okay')
            okay_btn = self.page.locator(
                "section[aria-label*='Police fight result'] button:has-text('Okay'), button:has-text('Okay')"
            ).first

            fight_finished = False
            for _ in range(20):  # Až 10 s
                if await okay_btn.is_visible():
                    outcome_info = await self.page.evaluate(
                        """() => {
                        const sec = document.querySelector("section[aria-label*='Police fight result']");
                        if (!sec) return "Souboj dokončen.";
                        return sec.innerText.trim();
                    }"""
                    )
                    print(f"[🏆] Policejní souboj dokončen! Výsledek:\n{outcome_info}")
                    print("-> Vyzvedávám odměnu a potvrzuji ('Okay')...")
                    await asyncio.sleep(random.uniform(0.5, 0.9))
                    try:
                        await okay_btn.click()
                    except Exception:
                        pass
                    await self.page.wait_for_timeout(2000)
                    fight_finished = True

                    if self.webhook_url:
                        await send_discord_webhook(
                            self.webhook_url,
                            "👮 Policejní souboj dokončen!",
                            f"Výsledek souboje:\n```{outcome_info[:300]}```",
                            color=0x2ECC71,
                        )
                    break
                await asyncio.sleep(0.5)

            # 5. Pokud se při prohře objevil dialog kauce (Post bail), zavřeme ho křížkem
            await self.page.evaluate(
                """() => {
                const closeBtn = document.querySelector("section button[aria-label='Close'], div[role='dialog'] button[aria-label='Close']");
                if (closeBtn) closeBtn.click();
            }"""
            )
            await asyncio.sleep(0.5)

            return fight_finished

        except Exception as e:
            print(f"[⚠️] Chyba při zpracování policejního přepadení: {e}")
            return False
        finally:
            # Vždy zajistíme bezpečný návrat do místnosti Kmotra
            if "/game/godfather" not in self.page.url:
                print("-> Návrat zpět ke Kmotrovi (/game/godfather)...")
                await self.page.goto(GODFATHER_URL)
                await self.page.wait_for_timeout(2000)
                await self.ensure_on_main_game()

    async def get_exact_notebook_timer(self) -> Optional[int]:
        """Přečte PŘESNÝ čas přímo z ikony hodin v zápisníku."""
        try:
            timer_img = self.page.locator("img[src*='timer']").first
            if await timer_img.is_visible():
                parent_text = await timer_img.locator("xpath=..").inner_text()
                m = re.search(r"(\d{1,2}):(\d{2})", parent_text)
                if m:
                    return int(m.group(1)) * 60 + int(m.group(2))

            cancel_btn = self.page.locator("button:has-text('Cancel')").first
            if await cancel_btn.is_visible():
                box_text = await cancel_btn.locator("xpath=../..").inner_text()
                m = re.search(r"\b(\d{1,2}):(\d{2})\b", box_text)
                if m:
                    return int(m.group(1)) * 60 + int(m.group(2))
        except Exception:
            pass
        return None

    async def wait_for_quest_completion(self, quest_title: str = "Neznámý úkol"):
        """DYNAMICKÉ REAKTIVNÍ SLEDOVÁNÍ MISE sekundu po sekundě."""
        print("-> Sleduji průběh mise v reálném čase...")
        initial_seconds = await self.get_exact_notebook_timer() or 60
        max_seen = initial_seconds

        while True:
            if "/police" in self.page.url or await self.is_police_encounter_visible():
                clear_line()
                print("\n[🚨] Detekováno policejní přepadení!")
                await self.handle_police_encounter()
                return True

            okay_btn = self.page.locator("button:has-text('Okay')").first
            if await okay_btn.is_visible():
                clear_line()
                print("\n[🎯] Úkol je dokončen! Připraveno tlačítko 'Okay'.")
                return True

            if "/duel" in self.page.url or "/fight" in self.page.url:
                clear_line()
                print("\n[⚔️] Detekován souboj mise!")
                return True

            current_sec = await self.get_exact_notebook_timer()
            cancel_btn = self.page.locator("button:has-text('Cancel')").first
            cancel_visible = await cancel_btn.is_visible()

            if not cancel_visible and current_sec is None:
                await asyncio.sleep(1)
                if await okay_btn.is_visible() or "/duel" in self.page.url:
                    return True
                return False

            if current_sec is not None:
                max_seen = max(max_seen, current_sec)
                elapsed = max_seen - current_sec
                bar = format_progress_bar(elapsed, max_seen, width=14)
                m, s = divmod(current_sec, 60)
                sys.stdout.write(f"\r  ⏱️  Zbývá do dokončení mise: {m:02d}m {s:02d}s {bar} ")
                sys.stdout.flush()

                if current_sec <= 0:
                    await asyncio.sleep(1)
                    continue
            else:
                sys.stdout.write("\r  ⏱️  Mise probíhá... ")
                sys.stdout.flush()

            await asyncio.sleep(1)

    async def read_quest_card(self) -> Dict[str, Any]:
        """Přečte parametry mise z otevřeného zápisníku."""
        try:
            return await self.page.evaluate(
                """() => {
                const card = {
                    title: "Neznámý úkol",
                    seconds: 60,
                    energy: 1.0,
                    xp: 10,
                    cash: 100,
                    ap: 0,
                    has_item: false,
                    is_disabled: false
                };

                const titleEls = Array.from(document.querySelectorAll("*")).filter(el => {
                    const s = window.getComputedStyle(el);
                    const ff = (s.fontFamily || "").toLowerCase();
                    const c = s.color || "";
                    return ff.includes("impact") && (c.includes("238, 93, 88") || c.includes("ee5d58"));
                });
                if (titleEls.length > 0) {
                    card.title = titleEls[0].innerText.trim();
                } else {
                    const fallback = document.querySelector("[style*='Impact'], [class*='Title']");
                    if (fallback) card.title = fallback.innerText.trim();
                }

                const startBtn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim() === "Start");
                if (startBtn) {
                    card.is_disabled = startBtn.disabled;
                }

                const itemImg = document.querySelector("img[src*='item'], [class*='ItemImg']");
                if (itemImg) {
                    card.has_item = true;
                }

                const cashImgs = Array.from(document.querySelectorAll("img[src*='cash']"));
                const notebookCash = cashImgs.find(img => img.getBoundingClientRect().top > 120);
                if (notebookCash) {
                    const cashRow = notebookCash.closest("div[class*='Group'], div[class*='Flex'], div");
                    if (cashRow && cashRow.parentElement) {
                        const container = cashRow.parentElement;
                        const rows = Array.from(container.children);
                        if (rows.length >= 4) {
                            const timerText = rows[0].innerText.trim();
                            const mTime = timerText.match(/(\\d{1,2}):(\\d{2})/);
                            if (mTime) {
                                card.seconds = Math.max(5, parseInt(mTime[1], 10) * 60 + parseInt(mTime[2], 10));
                            }

                            const energyText = rows[1].innerText.replace(/[^\\d\\.]/g, '');
                            if (energyText) card.energy = parseFloat(energyText);

                            const xpText = rows[2].innerText.replace(/[^\\d]/g, '');
                            if (xpText) card.xp = parseInt(xpText, 10);

                            const cashText = rows[3].innerText.replace(/[^\\d]/g, '');
                            if (cashText) card.cash = parseInt(cashText, 10);

                            if (rows.length >= 5) {
                                const apText = rows[4].innerText.replace(/[^\\d]/g, '');
                                if (apText) card.ap = parseInt(apText, 10);
                            }
                        }
                    }
                }

                return card;
            }"""
            )
        except Exception:
            return {
                "title": "Neznámý úkol",
                "seconds": 60,
                "xp": 10,
                "cash": 100,
                "energy": 1.0,
                "has_item": False,
                "is_disabled": False,
            }

    async def pick_and_start_optimal_quest(self) -> bool:
        """CHYTRÝ VÝBĚR ÚKOLŮ s ohodnocením XP/min a prioritou na zbraně/výbavu."""
        # 0. Kontrola policejního přepadení
        if "/police" in self.page.url or await self.is_police_encounter_visible():
            await self.handle_police_encounter()
            return True

        # Vždy držíme okno zafixované nahoře (žádný Playwright scroll)
        await self.page.evaluate("window.scrollTo(0, 0)")

        # 1. Zkontrolujeme, zda mise už nedoběhla a nečeká na potvrzení (Okay)
        okay_btn = self.page.locator("a[href*='godfather/duel'] button:has-text('Okay'), button:has-text('Okay')").first
        if await okay_btn.is_visible():
            print("-> Úkol je dokončen! Klikám na 'Okay' pro přechod do souboje...")
            await okay_btn.click(force=True)
            await self.page.wait_for_timeout(1800)
            if "/police" in self.page.url or await self.is_police_encounter_visible():
                await self.handle_police_encounter()
            elif "/duel" in self.page.url or "/fight" in self.page.url:
                await self.handle_duel_screen()
            return True

        # Zkontrolujeme, zda v zápisníku již aktivně neběží mise
        cancel_btn = self.page.locator("button:has-text('Cancel')").first
        complete_btn = self.page.locator("button:has-text('Complete Now')").first

        if await cancel_btn.is_visible() or await complete_btn.is_visible():
            card = await self.read_quest_card()
            print(f"\n[⏳ BĚŽÍ MISE] Zápisník zobrazuje aktivní probíhající úkol: \"{card['title']}\"!")
            print("-> Přepínám na reaktivní sledování dokončení mise...")
            await self.wait_for_quest_completion(card["title"])
            return True

        # Pokud je jakýkoliv zápisník otevřený, zavřeme ho přes JS (bez scrollování)
        await self.page.evaluate("""() => {
            const backBtn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim() === "Back");
            if (backBtn) backBtn.click();
        }""")
        await asyncio.sleep(0.4)

        # Najdeme zadavatele přítomné v DOMu
        available_npcs = []
        for giver in QUEST_GIVERS:
            is_present = await self.page.evaluate("""(sel) => {
                const el = document.querySelector(sel);
                return !!(el && el.getBoundingClientRect().width > 0);
            }""", giver["selector"])
            if is_present:
                available_npcs.append(giver)

        if not available_npcs:
            print("[⚠️] V místnosti nebyl nalezen žádný zadavatel úkolů.")
            return False

        # 2. Žádná mise neběží! Zkoumáme skutečné nabídky všech zadavatelů v místnosti
        print("\n" + "-" * 55)
        print(" [🧠 CHYTRÝ VÝBĚR MISÍ] Analyzuji nabídky zadavatelů...")
        print("-" * 55)
        print(f"-> Nalezeno {len(available_npcs)} zadavatelů v místnosti. Zkoumám nabídky...")

        scored_offers = []

        for giver in available_npcs:
            try:
                # Zavřeme předchozí zápisník a klikneme na zadavatele PŘÍMO přes JS (žádný Playwright auto-scroll!)
                clicked = await self.page.evaluate("""(sel) => {
                    const backBtn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim() === "Back");
                    if (backBtn) backBtn.click();
                    const el = document.querySelector(sel);
                    if (el) {
                        el.click();
                        return true;
                    }
                    return false;
                }""", giver["selector"])

                if not clicked:
                    continue

                await asyncio.sleep(0.6)

                # Pokud se po kliknutí objeví Cancel nebo Complete Now, znamená to, že běží mise!
                if await cancel_btn.is_visible() or await complete_btn.is_visible():
                    card = await self.read_quest_card()
                    print(f"\n[⏳ BĚŽÍ MISE] Zápisník zobrazuje aktivní probíhající úkol: \"{card['title']}\"!")
                    await self.wait_for_quest_completion(card["title"])
                    return True

                start_btn = self.page.locator("button:has-text('Start')").first
                for _ in range(6):
                    if await start_btn.is_visible():
                        break
                    await asyncio.sleep(0.2)

                if not await start_btn.is_visible():
                    continue

                # Přečteme data z právě otevřeného zápisníku
                card = await self.read_quest_card()

                xp_per_min = (card["xp"] / max(5, card["seconds"])) * 60.0
                cash_per_min = (card["cash"] / max(5, card["seconds"])) * 60.0

                strategy = self.config.get("quest_strategy", "max_xp")
                if strategy == "max_cash":
                    score = cash_per_min
                elif strategy == "balanced":
                    score = xp_per_min + (cash_per_min / 10.0)
                else:  # max_xp
                    score = xp_per_min

                if card["has_item"]:
                    score += 500.0

                if card["is_disabled"]:
                    score = -100.0

                m, s = divmod(card["seconds"], 60)
                item_str = " | 🎁 VZÁCNÝ PŘEDMĚT!" if card["has_item"] else ""
                print(
                    f"   • {giver['name']:<12}: \"{card['title']}\" ({m:02d}:{s:02d} | +{card['xp']} XP | ${card['cash']:,} | {xp_per_min:.1f} XP/min | ${cash_per_min:.0f}/min{item_str})"
                )

                scored_offers.append(
                    {
                        "giver": giver,
                        "card": card,
                        "score": score,
                        "xp_per_min": xp_per_min,
                    }
                )

                # ZAVŘEME ZÁPISNÍK klikem na 'Back' pro čistou místnost před další postavou
                await self.page.evaluate("""() => {
                    const backBtn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim() === "Back");
                    if (backBtn) backBtn.click();
                }""")
                await asyncio.sleep(0.3)

            except Exception:
                pass

        if not scored_offers:
            print("[⚠️] Nepodařilo se načíst žádnou nabídku.")
            return False

        scored_offers.sort(key=lambda x: x["score"], reverse=True)
        best = scored_offers[0]

        if best["score"] < 0:
            print("[⚠️] Žádný z nabízených úkolů nelze spustit (nedostatek energie).")
            print("💤 Čekám na dobití energie (15s)...")
            await asyncio.sleep(15)
            return False

        chosen_giver = best["giver"]
        chosen_card = best["card"]
        print(
            f"\n👉 \033[1;32mZvolena nejvýhodnější mise:\033[0m \"{chosen_card['title']}\" od {chosen_giver['name']}"
        )
        print(
            f"   -> Očekávaný zisk: +{chosen_card['xp']} XP | +${chosen_card['cash']:,} (Efektivita: {best['xp_per_min']:.1f} XP/min)"
        )

        # Otevřeme zápisník zvoleného zadavatele přímo přes JS
        await self.page.evaluate("""(sel) => {
            const backBtn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim() === "Back");
            if (backBtn) backBtn.click();
            const el = document.querySelector(sel);
            if (el) el.click();
        }""", chosen_giver["selector"])
        await asyncio.sleep(0.6)

        # Spustíme misi klikem na Start přes JS
        started = await self.page.evaluate("""() => {
            const startBtn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim() === "Start");
            if (startBtn && !startBtn.disabled) {
                startBtn.click();
                return true;
            }
            return false;
        }""")

        if started:
            print("[🚀] \033[1;32mMise úspěšně zahájena!\033[0m")
            await self.page.wait_for_timeout(1200)

            if self.webhook_url:
                fields = [
                    {"name": "Trvání", "value": f"{chosen_card['seconds']} s", "inline": True},
                    {"name": "XP zisk", "value": f"+{chosen_card['xp']} XP", "inline": True},
                    {"name": "Peníze", "value": f"+${chosen_card['cash']:,}", "inline": True},
                    {"name": "Zadavatel", "value": chosen_giver["name"], "inline": True},
                ]
                if chosen_card["has_item"]:
                    fields.append({"name": "Předmět", "value": "🎁 Zbraň / Výbava!", "inline": False})
                await send_discord_webhook(
                    self.webhook_url,
                    f"📜 Zahájena mise: {chosen_card['title']}",
                    f"Bot automaticky vybral nejefektivnější úkol ({best['xp_per_min']:.1f} XP/min).",
                    color=0x2ECC71,
                    fields=fields,
                )

            await self.wait_for_quest_completion(chosen_card["title"])
            return True

        return False

    async def check_survival(self) -> bool:
        """AUTOMATICKÝ SURVIVAL (ARÉNA PŘEŽITÍ)."""
        if not self.config.get("auto_survival", True):
            return False

        now = time.time()
        if now < self.next_survival_available:
            return False

        # Šetříme energii: Survival bere 3 energie za vlnu, chceme mít rezervu aspoň 15 pro úkoly
        stats = await self.get_player_stats()
        current_energy = stats.get("energy", 100.0)
        if current_energy < 15.0:
            print(f"\n[🛡️ SURVIVAL] Energie ({current_energy:.1f}) je pod rezervou 15. Šetřím energii pro úkoly u Kmotra.")
            self.next_survival_available = now + 300
            return False

        print("\n[🛡️ SURVIVAL] Vstupuji do arény přežití (/game/duel/survival)...")

        waves_won = 0
        rem_energy = current_energy
        try:
            await self.page.goto(SURVIVAL_URL)
            await self.page.wait_for_timeout(2500)
            await self.ensure_on_main_game()

            # Maximálně 5 vln v jednom cyklu, ať nevyčerpáme veškerou energii na úkoly
            while waves_won < 5:
                # 1. Zkontrolujeme tlačítko pro boj (Attack nebo A new attempt)
                attack_btn = self.page.locator(
                    "button:has-text('Attack'), button:has-text('A new attempt')"
                ).first

                # Počkáme až se tlačítko objeví
                for _ in range(8):
                    if await attack_btn.is_visible():
                        break
                    await asyncio.sleep(0.5)

                if not await attack_btn.is_visible() or await attack_btn.is_disabled():
                    body_text = await self.page.locator("body").inner_text()
                    if "not enough energy" in body_text.lower():
                        print("-> V aréně přežití chybí energie na další vlnu.")
                        self.next_survival_available = now + 300
                    elif "progress saved for" in body_text.lower():
                        m = re.search(r"progress saved for:\s*(\d{1,2}):(\d{2})", body_text, re.IGNORECASE)
                        wait_sec = 600
                        if m:
                            wait_sec = int(m.group(1)) * 60 + int(m.group(2)) + 5
                        print(f"-> Survival pokus byl dokončen / padl (odpočet: {wait_sec // 60}m {wait_sec % 60}s).")
                        self.next_survival_available = now + wait_sec
                    else:
                        print("-> Tlačítko pro Survival není aktivní.")
                        self.next_survival_available = now + 600
                    break

                # 2. Tlačítko je aktivní! Spouštíme vlnu
                print(f"-> 🛡️ Zahajuji vlnu Survivalu (Pokus #{waves_won + 1})...")
                await asyncio.sleep(random.uniform(0.6, 1.0))
                await attack_btn.click()
                await self.page.wait_for_timeout(1500)

                # Zkontrolujeme, zda se neobjevilo varování o plném inventáři
                cont_btn = self.page.locator(
                    "button:has-text('Continue'), text:has-text('Continue')"
                ).first
                if await cont_btn.is_visible():
                    print("-> Potvrzuji dialog plného inventáře (Continue)...")
                    await cont_btn.click()
                    await self.page.wait_for_timeout(1000)

                # Vyhodnotíme souboj (Skip -> Okay)
                handled = await self.handle_duel_screen(context_name=f"Survival Vlna {waves_won + 1}")
                if handled:
                    waves_won += 1
                    print(f"[✓] \033[1;32mVlna {waves_won} v Survivalu úspěšně dokončena!\033[0m")
                    await self.page.wait_for_timeout(2000)

                    # Zkontrolujeme zbývající energii
                    updated_stats = await self.get_player_stats()
                    rem_energy = updated_stats.get("energy", 0)
                    if rem_energy < 15.0:
                        print(f"-> Zbývá {rem_energy:.1f} energie. Šetřím zbylou energii pro úkoly u Kmotra.")
                        break
                else:
                    print("-> Souboj v Survivalu nebyl úspěšně potvrzen.")
                    break

            self.next_survival_available = now + 720
            if waves_won > 0 and self.webhook_url:
                await send_discord_webhook(
                    self.webhook_url,
                    f"🛡️ Survival aréna: Dokončeno {waves_won} vln!",
                    f"Tvůj gangster úspěšně prošel **{waves_won} vln** v aréně přežití a získal odměny.",
                    color=0x9B59B6,
                    fields=[
                        {"name": "Dokončené vlny", "value": str(waves_won), "inline": True},
                        {"name": "Zbývající energie", "value": f"{rem_energy:.1f}", "inline": True},
                    ],
                )
            return waves_won > 0

        except Exception as e:
            print(f"[⚠️] Chyba při Survivalu: {e}")
            self.next_survival_available = now + 300
        finally:
            if "/game/police" in self.page.url or await self.is_police_encounter_visible():
                await self.handle_police_encounter()
            if "/game/godfather" not in self.page.url:
                await self.page.goto(GODFATHER_URL)
                await self.page.wait_for_timeout(2000)

        return False

    async def check_duels(self) -> bool:
        """AUTOMATICKÉ DUELY S HRÁČI."""
        if not self.config.get("auto_duels", True):
            return False

        now = time.time()
        if now < self.next_duel_available:
            return False

        print("\n[⚔️ DUEL] Kontroluji PvP duely s hráči (/game/duel)...")

        try:
            await self.page.goto(DUEL_URL)
            await self.page.wait_for_timeout(2500)
            await self.ensure_on_main_game()

            # 1. Karta PvP duelu s odkazem /game/duel/compare/
            compare_link = self.page.locator("a[href*='/duel/compare/']").first
            if not await compare_link.is_visible():
                print("-> Karta PvP duelu nebyla na obrazovce nalezena.")
                self.next_duel_available = now + 600
                return False

            # 2. PŘESNÁ kontrola cooldownu: Hledáme výhradně Mantine popover se 125 zlaťáky!
            # (NESMÍME se nechat zmást 625 zlaťáky ze sousední karty Survivalu!)
            duel_status = await self.page.evaluate(
                """() => {
                const dropdowns = Array.from(document.querySelectorAll("div[class*='Popover-dropdown'], div[class*='dropdown']"));
                const duelPopover = dropdowns.find(d => {
                    const txt = (d.innerText || "").toLowerCase();
                    return txt.includes("125") && txt.includes("free of charge");
                });

                if (duelPopover) {
                    const m = duelPopover.innerText.match(/(\\d{1,2}):(\\d{2})/);
                    return {
                        on_cooldown: true,
                        wait_sec: m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : 900
                    };
                }
                return { on_cooldown: false, wait_sec: 0 };
            }"""
            )

            if duel_status.get("on_cooldown"):
                wait_sec = duel_status.get("wait_sec", 900) + 5
                print(f"-> PvP Duel je v odpočtu (zbývá {wait_sec // 60}m {wait_sec % 60}s). Šetřím zlaťáky!")
                self.next_duel_available = now + wait_sec
                return False

            duel_btn = compare_link.locator("button").first
            if not await duel_btn.is_visible() or await duel_btn.is_disabled():
                print("-> Tlačítko PvP duelu je momentálně neaktivní.")
                self.next_duel_available = now + 300
                return False

            # 3. CHYTRÝ VÝBĚR SOUPEŘE: Zkontrolujeme level soupeře na kartě
            stats = await self.get_player_stats()
            my_level = stats.get("level", 1)

            for skip_attempt in range(3):
                opponent_level = await self.page.evaluate(
                    """() => {
                    const duelLink = document.querySelector("a[href*='/duel/compare/']");
                    if (!duelLink) return null;
                    let card = duelLink.parentElement;
                    while (card && card !== document.body) {
                        if (card.innerText && card.innerText.includes("Duel")) break;
                        card = card.parentElement;
                    }
                    const text = card ? card.innerText : "";
                    const m = text.match(/Level\\s*(\\d+)/i);
                    return m ? parseInt(m[1], 10) : null;
                }"""
                )

                if opponent_level is not None and opponent_level > my_level + 1:
                    print(
                        f"-> Soupeř má vysoký level ({opponent_level} vs náš {my_level}). Klikám na 'Other opponent'..."
                    )
                    other_btn = self.page.locator("button:has-text('Other opponent')").first
                    if await other_btn.is_visible() and not await other_btn.is_disabled():
                        await other_btn.click()
                        await self.page.wait_for_timeout(1400)
                    else:
                        break
                else:
                    if opponent_level is not None:
                        print(f"-> Nalezen vhodný soupeř (Level {opponent_level} vs náš Level {my_level})!")
                    break

            # 4. Tlačítko je volné a soupeř zvolen! Klikáme na Attack (přejde na /duel/compare/$id)
            print("-> Otevírám porovnání soupeře...")
            await asyncio.sleep(random.uniform(0.5, 0.9))
            await duel_btn.click()
            await self.page.wait_for_timeout(2500)

            # 5. Nyní jsme na porovnávací obrazovce /game/duel/compare/$id
            if "/duel/compare" in self.page.url:
                print("-> Načtena porovnávací obrazovka soupeře. Kontroluji bezplatnost souboje...")

                # Pojistka: Ověříme, že na tlačítku Start the fight NENÍ cooldown popover se 125 zlaťáky!
                has_gold_cost = await self.page.evaluate(
                    """() => {
                    const dropdowns = Array.from(document.querySelectorAll("div[class*='Popover-dropdown'], div[class*='dropdown']"));
                    return dropdowns.some(d => {
                        const txt = (d.innerText || "").toLowerCase();
                        return txt.includes("125") && txt.includes("free of charge");
                    });
                }"""
                )

                if has_gold_cost:
                    print("[🛡️ ZLATO OCHRÁNĚNO] Souboj by stál 125 zlaťáků! Bezpečně odstupuji.")
                    self.next_duel_available = now + 900
                    return False

                # Tlačítko pro zahájení souboje má aria-label="Start the fight"
                fight_btn = self.page.locator(
                    "button[aria-label='Start the fight'], button[tooltip='Start the fight'], button:has-text('Start the fight')"
                ).first

                # Počkáme až se načte soupeř i tlačítko
                for _ in range(12):
                    if await fight_btn.is_visible() and not await fight_btn.is_disabled():
                        break
                    await asyncio.sleep(0.5)

                if await fight_btn.is_visible() and not await fight_btn.is_disabled():
                    print("-> ⚔️ Zahajuji PvP souboj (klikám na 'Start the fight')...")
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                    await fight_btn.click()
                    await self.page.wait_for_timeout(2500)

                    # Vyhodnotíme souboj (Skip -> Okay)
                    handled = await self.handle_duel_screen(context_name="PvP Duel")
                    self.next_duel_available = now + 900
                    if handled and self.webhook_url:
                        await send_discord_webhook(
                            self.webhook_url,
                            "⚔️ PvP Duel vyhrán!",
                            "Bot úspěšně absolvoval souboj s hráčem a získal reputaci a peníze.",
                            color=0xE67E22,
                        )
                    return True
                else:
                    print("-> Tlačítko 'Start the fight' nebylo připraveno.")
                    self.next_duel_available = now + 300
                    return False

        except Exception as e:
            print(f"[⚠️] Chyba při PvP duelu: {e}")
            self.next_duel_available = now + 300
        finally:
            if "/game/police" in self.page.url or await self.is_police_encounter_visible():
                await self.handle_police_encounter()
            if "/game/godfather" not in self.page.url:
                await self.page.goto(GODFATHER_URL)
                await self.page.wait_for_timeout(2000)

        return False

    async def check_smart_skills(self, force: bool = False) -> bool:
        """
        SMART SKILL SYSTEM:
        1. Vždy přednostně utratí body ZDARMA ('still free') z Level Upu za $0.
        2. Pro placený trénink ($1,500/bod):
           - Hlídá přísnou finanční rezervu (min_cash_reserve, např. $2,000).
           - Omezuje maximální útratu (% z peněženky, max 1 bod za cyklus).
           - Netrénuje náhodně: investuje do hlavní synergie třídy (Taktik: Útok & Štěstí).
        """
        skill_cfg = self.config.get("smart_skills", {})
        if not skill_cfg.get("enabled", True):
            return False

        now = time.time()
        if not force and now < self.next_skill_available:
            return False

        self.next_skill_available = now + 300

        try:
            await self.page.goto(CHARACTER_URL)
            await self.page.wait_for_timeout(2500)
            await self.ensure_on_main_game()

            # 1. Zkontrolujeme, zda máme body ZDARMA z level upu
            page_text = await self.page.locator("body").inner_text()
            has_free_points = "still free" in page_text.lower()

            if has_free_points:
                print("\n[💪 SMART-SKILL] Nalezeny volné body zdarma! Rozděluji bez útraty hotovosti...")
                # Pro Taktika střídáme Attack a Luck
                for sel in ["button[aria-label='Upgrade attack power']", "button[aria-label='Upgrade luck']"]:
                    btn = self.page.locator(sel).first
                    while await btn.is_visible() and not await btn.is_disabled():
                        cur_text = await self.page.locator("body").inner_text()
                        if "still free" not in cur_text.lower():
                            break
                        label = await btn.get_attribute("aria-label") or "vlastnost"
                        print(f"   -> ZDARMA investován bod do: \033[1;32m{label}\033[0m")
                        await btn.click()
                        await self.page.wait_for_timeout(600)

            # 2. Placený trénink za hotovost (pouze v režimu smart_budget)
            mode = skill_cfg.get("mode", "smart_budget")
            if mode == "smart_budget":
                # Získáme aktuální hotovost
                current_cash = self.last_known_cash
                stats = await self.get_player_stats()
                current_cash = stats.get("cash", current_cash)

                min_reserve = skill_cfg.get("min_cash_reserve", 2000)
                max_percent = skill_cfg.get("max_spend_percent", 25)
                max_points = skill_cfg.get("max_points_per_cycle", 1)
                cost_per_point = 1500  # Cena za trénink 1 bodu v Mafia Reborn

                disposable = max(0, current_cash - min_reserve)
                max_budget = current_cash * (max_percent / 100.0)
                allowed_cash = min(disposable, max_budget)

                points_to_buy = min(int(allowed_cash // cost_per_point), max_points)

                if points_to_buy > 0:
                    print(
                        f"\n[💪 SMART-SKILL] Finanční rozpočet povolen: Hotovost ${current_cash:,} (Rezerva ${min_reserve:,})"
                    )
                    print(
                        f"   -> Investuji ${cost_per_point:,} do 1 bodu vlastnosti (Zbude bezpečných ${current_cash - cost_per_point:,})..."
                    )

                    # Vybereme mezi Attack power a Luck
                    btn = self.page.locator("button[aria-label='Upgrade attack power']").first
                    if await btn.is_visible() and not await btn.is_disabled():
                        await btn.click()
                        await self.page.wait_for_timeout(800)
                        print(f"[✓] \033[1;32mNatrénován 1 bod (Útok) za ${cost_per_point:,}!\033[0m")

                        if self.webhook_url:
                            await send_discord_webhook(
                                self.webhook_url,
                                "💪 Smart Skill Trénink",
                                f"Natrénován 1 bod vlastnosti za ${cost_per_point:,}.\nZůstatek hotovosti: **${current_cash - cost_per_point:,}** (Bezpečnostní rezerva ${min_reserve:,} zachována).",
                                color=0x1ABC9C,
                            )
                else:
                    if current_cash < min_reserve:
                        print(
                            f"[🛡️ FINANČNÍ OCHRANA] Hotovost ${current_cash:,} je pod bezpečnou rezervou (${min_reserve:,}). Trénink pozastaven!"
                        )
                    else:
                        print(
                            f"[🛡️ FINANČNÍ OCHRANA] Hotovost ${current_cash:,} nestačí na splnění limitu {max_percent}% útraty. Šetřím peníze!"
                        )

        except Exception as e:
            pass
        finally:
            if "/game/police" in self.page.url or await self.is_police_encounter_visible():
                await self.handle_police_encounter()
            if "/game/godfather" not in self.page.url:
                await self.page.goto(GODFATHER_URL)
                await self.page.wait_for_timeout(2000)

        return False

    async def perform_game_turn(self) -> None:
        """Jeden vyhodnocovací cyklus stavu hry."""
        await self.ensure_on_main_game()

        current_url = self.page.url

        # A) POLICEJNÍ PŘEPADENÍ
        if "/police" in current_url or await self.is_police_encounter_visible():
            await self.handle_police_encounter()
            return

        # B) JSME V BĚŽNÉM SOUBOJI
        if "/duel" in current_url or "/fight" in current_url:
            await self.handle_duel_screen()
            return

        # C) ÚKOL JE DOKONČEN A ČEKÁ NA POTVRZENÍ ('Okay' v zápisníku)
        if "/godfather" in current_url:
            quest_okay_btn = self.page.locator(
                "a[href*='godfather/duel'] button:has-text('Okay'), a[href*='godfather/duel'] button"
            ).first
            if await quest_okay_btn.is_visible():
                print("-> \033[1;32mÚkol je dokončen!\033[0m Klikám na 'Okay' pro přechod do souboje...")
                await asyncio.sleep(random.uniform(0.5, 1.0))
                await quest_okay_btn.click()
                await self.page.wait_for_timeout(1800)
                if "/police" in self.page.url or await self.is_police_encounter_visible():
                    await self.handle_police_encounter()
                elif "/duel" in self.page.url or "/fight" in self.page.url:
                    await self.handle_duel_screen()
                return

        # C) ÚKOL PRÁVĚ BĚŽÍ (ČEKÁME)
        cancel_btn = self.page.locator("button:has-text('Cancel')").first
        if await cancel_btn.is_visible():
            await self.wait_for_quest_completion()
            return

        # D) VEDLEJŠÍ AKTIVITY (SURVIVAL, DUELY, SMART SKILL) KDYŽ ŽÁDNÝ ÚKOL NEBĚŽÍ
        # Provedeme je pouze pokud jim vypršel odpočet (žádné zbytečné překlikávání mezi stránkami)
        now = time.time()
        if now >= self.next_survival_available:
            survival_done = await self.check_survival()
            if survival_done:
                return

        if now >= self.next_duel_available:
            duel_done = await self.check_duels()
            if duel_done:
                return

        if now >= self.next_skill_available:
            await self.check_smart_skills()

        # E) OTEVŘEME A SPOČÍTÁME NEJLEPŠÍ ÚKOL
        if "/game/godfather" not in self.page.url:
            await self.page.goto(GODFATHER_URL)
            await self.page.wait_for_timeout(2000)
            await self.ensure_on_main_game()

        stats = await self.get_player_stats()
        print("\n" + "=" * 65)
        print(
            f" [🎯 STAV HRY] Level: {stats['level']} | Energie: {stats['energy']} | Hotovost: ${stats['cash']:,} | Zlaťáky: {stats['gold']:,}"
        )
        print("=" * 65)

        await self.pick_and_start_optimal_quest()

    async def run_loop(self):
        """Hlavní smyčka bota."""
        print("\n" + "=" * 65)
        print(" [KROK 2] AUTOMATIZACE SPOČÍTANÁ BEZ CHYB")
        print("=" * 65)
        print("Bot nyní bezpečně monitoruje hru:")
        print(" • Zlaťáky, hotovost i level čte s 100% přesností")
        print(" • Smart Skill systém hlídá tvou peněženku a trénuje s rozumem")
        print(" • Zajišťuje plynulý běh misí, survivalu a duelů")
        print("Pro zastavení stiskni Ctrl+C v terminálu.\n")

        while self.is_running:
            try:
                await self.perform_game_turn()
                await asyncio.sleep(1)
            except Exception as e:
                if not self.is_running:
                    break
                print(f"\n[⚠️] Upozornění smyčky: {e}")
                await asyncio.sleep(3)


async def main():
    if "--learn" in sys.argv:
        from learn_mode import run_standalone_learning
        await run_standalone_learning()
        return

    if "--update" in sys.argv:
        from updater import check_for_updates, apply_update
        cfg = load_config()
        has_up, msg, manifest = check_for_updates(cfg)
        print(msg)
        if has_up and manifest:
            ok, r_msg = apply_update(manifest, cfg)
            print(r_msg)
        return

    config = load_config()

    if config.get("auto_update", True) and config.get("update_url"):
        try:
            from updater import check_for_updates, apply_update
            has_up, msg, manifest = check_for_updates(config)
            if has_up and manifest:
                print("\n" + "=" * 65)
                print(f" 🎉 \033[1;32m{msg}\033[0m")
                print("=" * 65)
                ans = input("Chcete aktualizaci nyní automaticky nainstalovat? [A/n]: ").strip().lower()
                if ans in ["a", "ano", "y", "yes", ""]:
                    ok, r_msg = apply_update(manifest, config)
                    print(r_msg)
                    if ok:
                        print("Spusťte prosím bota znovu pro načtení nové verze.")
                        return
        except Exception:
            pass

    config = terminal_settings_menu(config)

    print("\n" + "=" * 65)
    print(" 🚀  SPUŠTĚNÍ BOTA S AKTIVNÍM NASTAVENÍM")
    print("=" * 65)
    print(f" • Aréna Survival : {'[✓] ZAPNUTO' if config.get('auto_survival') else '[✗] VYPNUTO'}")
    print(f" • PvP Duely      : {'[✓] ZAPNUTO' if config.get('auto_duels') else '[✗] VYPNUTO'}")
    print(f" • Policie & SWAT : {'[✓] ZAPNUTO (Automatický boj)' if config.get('auto_police', True) else '[✗] VYPNUTO'}")

    strat = config.get("quest_strategy", "max_xp")
    strat_labels = {"max_xp": "Max XP (rychlý postup)", "max_cash": "Max Peníze ($$$)", "balanced": "Vyvážená (XP + $)"}
    print(f" • Výběr misí     : \033[1;36m{strat_labels.get(strat, strat)}\033[0m")

    skill_cfg = config.get("smart_skills", {})
    if skill_cfg.get("enabled"):
        mode = skill_cfg.get("mode", "smart_budget")
        if mode == "free_only":
            print(" • Smart-Skill    : \033[1;33m[⚡] POUZE BODY ZDARMA ($0 útrata z Level Upu)\033[0m")
        else:
            reserve = skill_cfg.get("min_cash_reserve", 2000)
            pct = skill_cfg.get("max_spend_percent", 25)
            print(" • Smart-Skill    : \033[1;32m[✓] AKTIVNÍ (Chytrý rozpočet)\033[0m")
            print(f"   🔒 Finanční rezerva : Minimálně ${reserve:,} (bot na tyto peníze NESMÍ sáhnout)")
            print(f"   📊 Max útrata      : Max {pct}% z hotovosti a max 1 bod ($1,500) za cyklus")
            print(f"   🎯 Taktik synergie : Útok & Štěstí (žádné náhodné klikání)")
    else:
        print(" • Smart-Skill    : \033[1;31m[✗] VYPNUTO (Žádné vylepšování)\033[0m")

    if config.get("discord_webhook_url"):
        print(" • Discord Webhook: \033[1;32m[✓] AKTIVNÍ\033[0m")
    else:
        print(" • Discord Webhook: [✗] Nenastaven")
    print("=" * 65 + "\n")

    print("Spouštím prohlížeč pro Mafia Reborn...")

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                channel="chrome",
                headless=False,
                viewport={"width": 1280, "height": 850},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                headless=False,
                viewport={"width": 1280, "height": 850},
            )

        page = context.pages[0] if context.pages else await context.new_page()
        bot = MafiaBot(page, context, config)

        try:
            await bot.wait_for_login()
            await bot.run_loop()

        except KeyboardInterrupt:
            print("\n\n[*] Bot byl ručně zastaven uživatelem (Ctrl+C). Měj se!")
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
