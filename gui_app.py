import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, Optional

import aiohttp
from playwright.async_api import BrowserContext, Page, async_playwright

from learn_mode import LearnSession
from mafia_bot import (
    BASE_URL,
    CONFIG_FILE,
    GODFATHER_URL,
    USER_DATA_DIR,
    MafiaBot,
    load_config,
    save_config,
    send_discord_webhook,
)
from updater import apply_update, check_for_updates, get_current_version

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """Odstraní ANSI únikové sekvence pro barvy v terminálu."""
    return ANSI_ESCAPE.sub("", text)


class IORedirector:
    """Přesměrovává výstup z print / stdout přímo do Tkinter okna."""

    def __init__(self, callback):
        self.callback = callback

    def write(self, s: str):
        cleaned = strip_ansi(s)
        if cleaned:
            self.callback(cleaned)

    def flush(self):
        pass


class MafiaBotRunner:
    """Správce běhu bota ve vedlejším vlákně s vlastním asyncio loopem."""

    def __init__(self, log_fn, status_fn):
        self.log_fn = log_fn
        self.status_fn = status_fn
        self.thread = None
        self.loop = None
        self.bot = None
        self.context = None
        self.is_running = False

    def start(self, config: Dict[str, Any]):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._worker, args=(config,), daemon=True)
        self.thread.start()

    def _worker(self, config: Dict[str, Any]):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run_bot(config))
        except Exception as e:
            self.log_fn(f"\n[⚠️] Chyba bota: {e}\n")
        finally:
            self.is_running = False
            self.status_fn(False)

    async def _run_bot(self, config: Dict[str, Any]):
        self.status_fn(True)
        self.log_fn("\n" + "=" * 60 + "\n")
        self.log_fn(" [🚀] SPUŠTĚNÍ MAFIA REBORN BOTA (Windows App)\n")
        self.log_fn("=" * 60 + "\n")
        self.log_fn("-> Spouštím prohlížeč Chromium / Google Chrome...\n")

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

            page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            self.bot = MafiaBot(page, self.context, config)

            try:
                await self.bot.wait_for_login()
                await self.bot.run_loop()
            except Exception as e:
                self.log_fn(f"[!] Ukončení smyčky: {e}\n")
            finally:
                try:
                    await self.context.close()
                except Exception:
                    pass

    def stop(self):
        if not self.is_running:
            return
        self.log_fn("\n[⏹] Požadavek na zastavení bota...\n")
        if self.bot:
            self.bot.stop()
        if self.context and self.loop:
            asyncio.run_coroutine_threadsafe(self.context.close(), self.loop)
        self.is_running = False
        self.status_fn(False)


class LearnModeRunner:
    """Správce pasivního režimu učení ve vedlejším vlákně."""

    def __init__(self, log_fn, status_fn, on_finished_fn):
        self.log_fn = log_fn
        self.status_fn = status_fn
        self.on_finished_fn = on_finished_fn
        self.session: Optional[LearnSession] = None
        self.thread = None
        self.loop = None
        self.is_recording = False

    def start(self):
        if self.is_recording:
            return
        self.is_recording = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.session = LearnSession(log_fn=self.log_fn)
        self.status_fn(True)
        try:
            self.loop.run_until_complete(self.session.start_recording())
        except Exception as e:
            self.log_fn(f"\n[⚠️] Chyba režimu učení: {e}\n")
        finally:
            self.is_recording = False
            self.status_fn(False)
            saved_file = getattr(self.session, "last_saved_file", "")
            if saved_file and os.path.exists(saved_file):
                self.on_finished_fn(saved_file)

    def stop(self):
        if not self.is_recording or not self.session:
            return
        self.log_fn("\n[⏹] Ukončuji záznam herní relace a generuji export...\n")
        self.session.is_recording = False
        self.is_recording = False


class MafiaApp(tk.Tk):
    """Hlavní grafické okno aplikace pro Windows."""

    def __init__(self):
        super().__init__()
        self.title(f"Mafia Reborn Bot — Windows App v{get_current_version()}")
        self.geometry("940x730")
        self.minsize(840, 620)
        self.configure(bg="#1e1e1e")

        self.config_data = load_config()
        self.runner = MafiaBotRunner(self.append_log, self.update_bot_status)
        self.learn_runner = LearnModeRunner(
            self.append_log, self.update_learn_status, self._on_learn_export_finished
        )

        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = IORedirector(self.append_log)
        sys.stderr = IORedirector(self.append_log)

        self._setup_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Kontrola aktualizací po spuštění na pozadí
        if self.config_data.get("auto_update", True) and self.config_data.get("update_url"):
            self.after(2000, self.check_updates_background)

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Obecné styly
        style.configure("TFrame", background="#1e1e1e")
        style.configure("Card.TFrame", background="#252526", relief="solid", borderwidth=1)
        style.configure("TLabel", background="#1e1e1e", foreground="#e0e0e0", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#252526", foreground="#e0e0e0", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#1e1e1e", foreground="#ffffff", font=("Segoe UI", 16, "bold"))
        style.configure("Subtitle.TLabel", background="#1e1e1e", foreground="#888888", font=("Segoe UI", 9))
        style.configure("Warning.TLabel", background="#2d2200", foreground="#ffd700", font=("Segoe UI", 9), padding=8)

        # Tlačítka a volby
        style.configure("Action.TButton", font=("Segoe UI", 11, "bold"), padding=6)
        style.configure("TCheckbutton", background="#252526", foreground="#ffffff", font=("Segoe UI", 10))
        style.configure("TRadiobutton", background="#252526", foreground="#ffffff", font=("Segoe UI", 10))

        # Záložky (Notebook)
        style.configure("TNotebook", background="#1e1e1e", borderwidth=0)
        style.configure("TNotebook.Tab", background="#2d2d30", foreground="#cccccc", padding=[16, 6], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#007acc")], foreground=[("selected", "#ffffff")])

    def _build_ui(self):
        # 1. HORNÍ ZÁHLAVÍ (HEADER)
        header = ttk.Frame(self)
        header.pack(fill="x", padx=16, pady=12)

        title_box = ttk.Frame(header)
        title_box.pack(side="left", fill="y")
        ttk.Label(title_box, text=f"🎩 MAFIA REBORN BOT (v{get_current_version()})", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Autonomní herní asistent s podporou pasivního učení a online aktualizací", style="Subtitle.TLabel").pack(anchor="w")

        # Stavový indikátor vpravo
        self.status_box = ttk.Frame(header)
        self.status_box.pack(side="right", fill="y")
        self.status_canvas = tk.Canvas(self.status_box, width=16, height=16, bg="#1e1e1e", highlightthickness=0)
        self.status_canvas.pack(side="left", padx=4)
        self.status_dot = self.status_canvas.create_oval(2, 2, 14, 14, fill="#dc3545", outline="")
        self.status_lbl = ttk.Label(self.status_box, text="ZASTAVENO", font=("Segoe UI", 11, "bold"), foreground="#dc3545")
        self.status_lbl.pack(side="left")

        # 2. HLAVNÍ OVLÁDACÍ LIŠTA (ACTION BUTTONS)
        actions_bar = ttk.Frame(self)
        actions_bar.pack(fill="x", padx=16, pady=(0, 12))

        # Tlačítko SPUSTIT BOTA
        self.btn_start = tk.Button(
            actions_bar,
            text="▶  SPUSTIT BOTA",
            bg="#28a745",
            fg="white",
            activebackground="#218838",
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=18,
            pady=8,
            cursor="hand2",
            command=self.start_bot,
        )
        self.btn_start.pack(side="left", padx=(0, 8))

        # Tlačítko ZASTAVIT BOTA
        self.btn_stop = tk.Button(
            actions_bar,
            text="⏹  ZASTAVIT BOTA",
            bg="#555555",
            fg="#aaaaaa",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=16,
            pady=8,
            state="disabled",
            cursor="arrow",
            command=self.stop_bot,
        )
        self.btn_stop.pack(side="left", padx=(0, 8))

        # Tlačítko REŽIM UČENÍ (ZÁZNAMNÍK HRY)
        self.btn_learn = tk.Button(
            actions_bar,
            text="🎓  REŽIM UČENÍ (ZÁZNAM)",
            bg="#8e44ad",
            fg="white",
            activebackground="#732d91",
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
            command=self.toggle_learn_mode,
        )
        self.btn_learn.pack(side="left", padx=(0, 8))

        # Tlačítko AKTUALIZACE
        btn_update = tk.Button(
            actions_bar,
            text="🔄  Aktualizace",
            bg="#333333",
            fg="#ffffff",
            activebackground="#444444",
            font=("Segoe UI", 10),
            relief="flat",
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.manual_check_update,
        )
        btn_update.pack(side="right", padx=(8, 0))

        # Tlačítko OTEVŘÍT HRU
        btn_open_game = tk.Button(
            actions_bar,
            text="🌐  Otevřít hru",
            bg="#007acc",
            fg="white",
            activebackground="#0062a3",
            font=("Segoe UI", 10),
            relief="flat",
            padx=12,
            pady=8,
            cursor="hand2",
            command=lambda: os.system("start https://mafiareborn.com" if os.name == "nt" else "open https://mafiareborn.com"),
        )
        btn_open_game.pack(side="right")

        # 3. ZÁLOŽKY (NOTEBOOK)
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        # TAB 1: ŽIVÝ ZÁZNAM (LOG)
        tab_log = ttk.Frame(notebook)
        notebook.add(tab_log, text=" 📜 Živý záznam ")
        self._build_log_tab(tab_log)

        # TAB 2: NASTAVENÍ (SETTINGS)
        tab_settings = ttk.Frame(notebook)
        notebook.add(tab_settings, text=" ⚙️ Nastavení ")
        self._build_settings_tab(tab_settings)

        # TAB 3: REŽIM UČENÍ (INFO & NÁVOD)
        tab_learn = ttk.Frame(notebook)
        notebook.add(tab_learn, text=" 🎓 Režim učení ")
        self._build_learn_tab(tab_learn)

        # TAB 4: NÁVOD
        tab_info = ttk.Frame(notebook)
        notebook.add(tab_info, text=" ℹ️ Návod k použití ")
        self._build_info_tab(tab_info)

    def _build_log_tab(self, parent):
        top_bar = ttk.Frame(parent)
        top_bar.pack(fill="x", pady=6)
        ttk.Label(top_bar, text="Konzolový výstup bota a režimu učení v reálném čase:").pack(side="left")

        btn_clear = tk.Button(
            top_bar,
            text="Vyčistit záznam",
            bg="#333333",
            fg="#ffffff",
            font=("Segoe UI", 9),
            relief="flat",
            padx=10,
            pady=2,
            command=self.clear_log,
        )
        btn_clear.pack(side="right")

        self.txt_log = ScrolledText(
            parent,
            bg="#141414",
            fg="#e0e0e0",
            insertbackground="white",
            font=("Consolas", 10),
            relief="flat",
            wrap="word",
        )
        self.txt_log.pack(fill="both", expand=True)

    def _build_settings_tab(self, parent):
        canvas = tk.Canvas(parent, bg="#1e1e1e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_container = ttk.Frame(canvas)

        scroll_container.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scroll_container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Skupina 1: Vedlejší herní aktivity
        card_activities = ttk.Frame(scroll_container, style="Card.TFrame", padding=12)
        card_activities.pack(fill="x", pady=(0, 10))

        ttk.Label(card_activities, text="HERNÍ AKTIVITY", font=("Segoe UI", 11, "bold"), style="Card.TLabel").pack(anchor="w", pady=(0, 8))

        self.var_survival = tk.BooleanVar(value=self.config_data.get("auto_survival", True))
        ttk.Checkbutton(card_activities, text="Aréna Survival (automatické zdolávání vln a sběr checkpointů)", variable=self.var_survival).pack(anchor="w", pady=3)

        self.var_duels = tk.BooleanVar(value=self.config_data.get("auto_duels", True))
        ttk.Checkbutton(card_activities, text="PvP Duely (automatické souboje s hráči, filtrace slabších soupeřů, 0 zlata)", variable=self.var_duels).pack(anchor="w", pady=3)

        self.var_police = tk.BooleanVar(value=self.config_data.get("auto_police", True))
        ttk.Checkbutton(card_activities, text="Policie & SWAT (automatický souboj s policií po misích o odznaky a hodinové bonusy)", variable=self.var_police).pack(anchor="w", pady=3)

        # Skupina 2: Strategie misí
        card_quest = ttk.Frame(scroll_container, style="Card.TFrame", padding=12)
        card_quest.pack(fill="x", pady=(0, 10))

        ttk.Label(card_quest, text="VÝBĚR MISÍ U KMOTRA", font=("Segoe UI", 11, "bold"), style="Card.TLabel").pack(anchor="w", pady=(0, 8))

        row_q = ttk.Frame(card_quest, style="Card.TFrame")
        row_q.pack(fill="x")
        ttk.Label(row_q, text="Strategie hodnocení nabídek:", style="Card.TLabel").pack(side="left", padx=(0, 12))

        self.var_quest_strat = tk.StringVar(value=self.config_data.get("quest_strategy", "max_xp"))
        strat_opts = [
            ("max_xp", "Maximální XP (nejrychlejší postup a levelování)"),
            ("max_cash", "Maximální hotovost (zaměření na vydělávání peněz)"),
            ("balanced", "Vyvážená strategie (optimální poměr XP a peněz)"),
        ]
        self.combo_strat = ttk.Combobox(row_q, state="readonly", width=45, values=[name for _, name in strat_opts])
        cur_idx = 0
        for idx, (val, name) in enumerate(strat_opts):
            if val == self.var_quest_strat.get():
                cur_idx = idx
                break
        self.combo_strat.current(cur_idx)
        self.combo_strat.pack(side="left")

        # Skupina 3: Smart-Skills
        card_skill = ttk.Frame(scroll_container, style="Card.TFrame", padding=12)
        card_skill.pack(fill="x", pady=(0, 10))

        ttk.Label(card_skill, text="SMART-SKILL SYSTÉM (VYLEPŠOVÁNÍ ATRIBUTŮ)", font=("Segoe UI", 11, "bold"), style="Card.TLabel").pack(anchor="w", pady=(0, 6))

        warn_box = tk.Label(
            card_skill,
            text="⚠️  UPOZORNĚNÍ: V beta verzi Mafia Reborn stojí nákup atributu $1,500/bod.\nPro ochranu hotovosti zvolte 'Chytrý rozpočet' s finanční rezervou, nebo 'Pouze body zdarma' ($0 útrata).",
            bg="#2c2205",
            fg="#f1c40f",
            font=("Segoe UI", 9),
            justify="left",
            padx=10,
            pady=6,
            relief="solid",
            borderwidth=1,
        )
        warn_box.pack(fill="x", pady=(0, 8))

        skill_cfg = self.config_data.get("smart_skills", {})
        self.var_skill_enabled = tk.BooleanVar(value=skill_cfg.get("enabled", True))
        ttk.Checkbutton(card_skill, text="Povolit automatické vylepšování atributů", variable=self.var_skill_enabled).pack(anchor="w", pady=3)

        self.var_skill_mode = tk.StringVar(value=skill_cfg.get("mode", "smart_budget"))
        ttk.Radiobutton(card_skill, text="Chytrý rozpočet (investuje s rozumem, hlídá přísnou finanční rezervu)", value="smart_budget", variable=self.var_skill_mode).pack(anchor="w", padx=20, pady=2)
        ttk.Radiobutton(card_skill, text="Pouze body ZDARMA z Level Upu ($0 útrata, žádný nákup za hotovost)", value="free_only", variable=self.var_skill_mode).pack(anchor="w", padx=20, pady=2)

        row_budget = ttk.Frame(card_skill, style="Card.TFrame")
        row_budget.pack(fill="x", padx=20, pady=6)

        ttk.Label(row_budget, text="Minimální rezerva ($):", style="Card.TLabel").pack(side="left", padx=(0, 6))
        self.entry_reserve = ttk.Entry(row_budget, width=10)
        self.entry_reserve.insert(0, str(skill_cfg.get("min_cash_reserve", 2000)))
        self.entry_reserve.pack(side="left", padx=(0, 20))

        ttk.Label(row_budget, text="Max útrata za cyklus (%):", style="Card.TLabel").pack(side="left", padx=(0, 6))
        self.entry_pct = ttk.Entry(row_budget, width=8)
        self.entry_pct.insert(0, str(skill_cfg.get("max_spend_percent", 25)))
        self.entry_pct.pack(side="left")

        # Skupina 4: Aktualizace na dálku
        card_update = ttk.Frame(scroll_container, style="Card.TFrame", padding=12)
        card_update.pack(fill="x", pady=(0, 10))

        ttk.Label(card_update, text="AKTUALIZACE NA DÁLKU (AUTO-UPDATE)", font=("Segoe UI", 11, "bold"), style="Card.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(
            card_update,
            text="Umožňuje stahovat nové aktualizace přímo z vašeho GitHubu bez nutnosti posílat kamarádovi nové soubory.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        row_up = ttk.Frame(card_update, style="Card.TFrame")
        row_up.pack(fill="x", pady=2)
        ttk.Label(row_up, text="GitHub / Update URL:", style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.entry_update_url = ttk.Entry(row_up, width=45)
        self.entry_update_url.insert(0, self.config_data.get("update_url", ""))
        self.entry_update_url.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_chk = tk.Button(
            row_up,
            text="🔄 Zkontrolovat",
            bg="#007acc",
            fg="white",
            relief="flat",
            padx=10,
            pady=2,
            cursor="hand2",
            command=self.manual_check_update,
        )
        btn_chk.pack(side="left")

        self.var_auto_update = tk.BooleanVar(value=self.config_data.get("auto_update", True))
        ttk.Checkbutton(card_update, text="Automaticky kontrolovat aktualizace při spuštění bota", variable=self.var_auto_update).pack(anchor="w", pady=(6, 0))

        # Skupina 5: Discord Webhook
        card_discord = ttk.Frame(scroll_container, style="Card.TFrame", padding=12)
        card_discord.pack(fill="x", pady=(0, 10))

        ttk.Label(card_discord, text="DISCORD WEBHOOK NOTIFIKACE", font=("Segoe UI", 11, "bold"), style="Card.TLabel").pack(anchor="w", pady=(0, 6))

        row_wh = ttk.Frame(card_discord, style="Card.TFrame")
        row_wh.pack(fill="x", pady=4)
        ttk.Label(row_wh, text="Webhook URL:", style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.entry_webhook = ttk.Entry(row_wh, width=45)
        self.entry_webhook.insert(0, self.config_data.get("discord_webhook_url", ""))
        self.entry_webhook.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_test_wh = tk.Button(
            row_wh,
            text="🔔 Otestovat",
            bg="#007acc",
            fg="white",
            relief="flat",
            padx=10,
            pady=2,
            cursor="hand2",
            command=self.test_webhook,
        )
        btn_test_wh.pack(side="left")

        # Tlačítko Uložit nastavení
        btn_save = tk.Button(
            scroll_container,
            text="💾  ULOŽIT VŠECHNA NASTAVENÍ",
            bg="#28a745",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2",
            command=self.save_settings,
        )
        btn_save.pack(anchor="e", pady=8)

    def _build_learn_tab(self, parent):
        info_frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        info_frame.pack(fill="both", expand=True, pady=6)

        text = """
🎓 REŽIM UČENÍ (ZÁZNAMNÍK LIDSKÉHO HRANÍ)

Tato funkce slouží k zachycení nových herních mechanik, které bot zatím nezná:
• Bot je v tomto režimu 100% PASIVNÍ: sám na nic nekliká, nehraje ani neutrácí peníze.
• Hráč může hrát hru úplně normálně (vyzkoušet nové obchody, rodinné války, bosse, kasino atd.).
• Během hraní skript tiše na pozadí zaznamenává:
  1. Kliknutí hráče (tlačítka, dialogy, sekce a prvky rozhraní).
  2. Navštívené herní stránky (/game/shops, /game/gangwar, /game/family...).
  3. Síťové API požadavky a odpovědi ze serveru (odměny, statistiky, předměty).

JAK REŽIM UČENÍ POUŽÍT:
1. Klikněte na fialové tlačítko "🎓 REŽIM UČENÍ (ZÁZNAM)" v horní liště.
2. Otevře se prohlížeč Chrome s Mafia Reborn.
3. Hrajte hru a dělejte akce, které chcete, aby se bot naučil.
4. Až skončíte, klikněte na červené tlačítko "⏹ UKONČIT A ULOŽIT ZÁZNAM".
5. Aplikace automaticky vytvoří soubor mafia_learn_export_<datum>.json a otevře složku.
6. Tento soubor stačí poslat tvůrci bota – ten z něj vyčte přesné herní struktury a přidá novou funkci!
"""
        txt = tk.Text(info_frame, bg="#1e1e1e", fg="#e0e0e0", font=("Segoe UI", 10), wrap="word", relief="flat")
        txt.insert("1.0", text.strip())
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)

    def _build_info_tab(self, parent):
        info_frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        info_frame.pack(fill="both", expand=True, pady=6)

        text = """
🎩 MAFIA REBORN BOT — NÁVOD K POUŽITÍ (WINDOWS EDITION)

1. SPUŠTĚNÍ BOTA:
   • Klikněte na zelené tlačítko "▶ SPUSTIT BOTA".
   • Otevře se okno Google Chrome / Chromium s hrou Mafia Reborn.
   • Pokud nejste přihlášeni, přihlaste se v prohlížeči ke svému účtu.
   • Jakmile jste ve hře, bot automaticky převezme řízení!
   • Všechny přihlašovací údaje zůstávají bezpečně uloženy v profilu .mafia_profile.

2. CO BOT DĚLÁ AUTOMATICKY:
   • 🧠 Kmotr (Mise): Prozkoumá všechny zadavatele v místnosti, vybere matematicky 
     nejvýhodnější úkol (nejvíce XP/min nebo předmět) a sám ho zahájí i dokončí.
   • 🛡️ Survival aréna: Pravidelně kontroluje bezplatné vlny a shrábne obrovské odměny.
   • ⚔️ PvP Duely: Bojuje s hráči pouze když je duel ZDARMA (nikdy neutrácí zlaťáky).
   • 🚨 Policie & SWAT: Při policejním přepadení nevolí útěk, ale pustí se do boje o odznaky.
   • 💰 Smart-Skills: Vylepšuje postavu (Útok & Štěstí) s dodržením nastavené rezervy.

3. AKTUALIZACE NA DÁLKU:
   • Do záložky Nastavení vložte odkaz na GitHub s novou verzí.
   • Bot se sám zaktualizuje bez nutnosti posílat nové instalační soubory!
"""
        txt = tk.Text(info_frame, bg="#1e1e1e", fg="#e0e0e0", font=("Segoe UI", 10), wrap="word", relief="flat")
        txt.insert("1.0", text.strip())
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)

    def append_log(self, text: str):
        def _insert():
            self.txt_log.insert("end", text)
            self.txt_log.see("end")

        self.after(0, _insert)

    def clear_log(self):
        self.txt_log.delete("1.0", "end")

    def update_bot_status(self, is_running: bool):
        def _update():
            if is_running:
                self.status_canvas.itemconfig(self.status_dot, fill="#28a745")
                self.status_lbl.configure(text="BĚŽÍ (Online)", foreground="#28a745")
                self.btn_start.configure(state="disabled", bg="#555555", fg="#aaaaaa", cursor="arrow")
                self.btn_stop.configure(state="normal", bg="#dc3545", fg="white", cursor="hand2")
                self.btn_learn.configure(state="disabled", bg="#555555", fg="#aaaaaa", cursor="arrow")
            else:
                if not self.learn_runner.is_recording:
                    self.status_canvas.itemconfig(self.status_dot, fill="#dc3545")
                    self.status_lbl.configure(text="ZASTAVENO", foreground="#dc3545")
                    self.btn_start.configure(state="normal", bg="#28a745", fg="white", cursor="hand2")
                    self.btn_stop.configure(state="disabled", bg="#555555", fg="#aaaaaa", cursor="arrow")
                    self.btn_learn.configure(state="normal", bg="#8e44ad", fg="white", cursor="hand2")

        self.after(0, _update)

    def update_learn_status(self, is_recording: bool):
        def _update():
            if is_recording:
                self.status_canvas.itemconfig(self.status_dot, fill="#9b59b6")
                self.status_lbl.configure(text="UČENÍ (Záznam)", foreground="#9b59b6")
                self.btn_start.configure(state="disabled", bg="#555555", fg="#aaaaaa", cursor="arrow")
                self.btn_stop.configure(state="disabled", bg="#555555", fg="#aaaaaa", cursor="arrow")
                self.btn_learn.configure(
                    text="⏹  UKONČIT A ULOŽIT",
                    bg="#e74c3c",
                    activebackground="#c0392b",
                )
            else:
                self.btn_learn.configure(
                    text="🎓  REŽIM UČENÍ (ZÁZNAM)",
                    bg="#8e44ad",
                    activebackground="#732d91",
                )
                if not self.runner.is_running:
                    self.status_canvas.itemconfig(self.status_dot, fill="#dc3545")
                    self.status_lbl.configure(text="ZASTAVENO", foreground="#dc3545")
                    self.btn_start.configure(state="normal", bg="#28a745", fg="white", cursor="hand2")
                    self.btn_learn.configure(state="normal", bg="#8e44ad", fg="white", cursor="hand2")

        self.after(0, _update)

    def toggle_learn_mode(self):
        if self.learn_runner.is_recording:
            self.learn_runner.stop()
        else:
            if self.runner.is_running:
                messagebox.showwarning("Upozornění", "Nejprve zastavte běžícího bota.")
                return

            confirm = messagebox.askyesno(
                "Spustit režim učení",
                "V režimu učení bot NIC nedělá a nechá vás hrát.\n"
                "Na pozadí bude tiše zaznamenávat herní akce a data.\n\n"
                "Chcete nyní zahájit nahrávání?",
            )
            if confirm:
                self.learn_runner.start()

    def _on_learn_export_finished(self, saved_file: str):
        def _show():
            filename = os.path.basename(saved_file)
            messagebox.showinfo(
                "Export dokončen",
                f"🎉 Herní relace byla úspěšně zaznamenána!\n\n"
                f"Soubor: {filename}\n\n"
                f"Tento soubor pošlete tvůrci bota pro přidání nových funkcí.",
            )
            # Otevřeme složku se souborem
            try:
                if os.name == "nt":
                    subprocess.run(["explorer", f"/select,{saved_file}"])
                else:
                    subprocess.run(["open", "-R", saved_file])
            except Exception:
                pass

        self.after(0, _show)

    def save_settings(self):
        self.config_data["auto_survival"] = self.var_survival.get()
        self.config_data["auto_duels"] = self.var_duels.get()
        self.config_data["auto_police"] = self.var_police.get()

        sel_strat_name = self.combo_strat.get()
        if "peníze" in sel_strat_name:
            self.config_data["quest_strategy"] = "max_cash"
        elif "Vyvážená" in sel_strat_name:
            self.config_data["quest_strategy"] = "balanced"
        else:
            self.config_data["quest_strategy"] = "max_xp"

        reserve_val = 2000
        try:
            reserve_val = int(self.entry_reserve.get().strip())
        except ValueError:
            pass

        pct_val = 25
        try:
            pct_val = int(self.entry_pct.get().strip())
        except ValueError:
            pass

        self.config_data["smart_skills"] = {
            "enabled": self.var_skill_enabled.get(),
            "mode": self.var_skill_mode.get(),
            "min_cash_reserve": reserve_val,
            "max_spend_percent": pct_val,
            "max_points_per_cycle": 1,
        }

        self.config_data["update_url"] = self.entry_update_url.get().strip()
        self.config_data["auto_update"] = self.var_auto_update.get()
        self.config_data["discord_webhook_url"] = self.entry_webhook.get().strip()

        save_config(self.config_data)
        messagebox.showinfo("Nastavení", "Nastavení bylo úspěšně uloženo do config.json!")

    def check_updates_background(self):
        def _check():
            has_update, msg, manifest = check_for_updates(self.config_data)
            if has_update and manifest:
                self.after(0, lambda: self._prompt_update(manifest, msg))

        threading.Thread(target=_check, daemon=True).start()

    def manual_check_update(self):
        self.save_settings()
        self.append_log("\n[🔄 AKTUALIZACE] Kontroluji dostupnost nové verze na serveru...\n")

        def _check():
            has_update, msg, manifest = check_for_updates(self.config_data)
            if has_update and manifest:
                self.after(0, lambda: self._prompt_update(manifest, msg))
            else:
                self.append_log(f"-> {msg}\n")
                self.after(0, lambda: messagebox.showinfo("Aktualizace", msg))

        threading.Thread(target=_check, daemon=True).start()

    def _prompt_update(self, manifest: Dict[str, Any], msg: str):
        confirm = messagebox.askyesno("Dostupná aktualizace", f"{msg}\n\nChcete aktualizaci nyní nainstalovat?")
        if confirm:
            self.append_log("\n[⬇️ AKTUALIZACE] Stahuji a instaluji novou verzi...\n")

            def _apply():
                ok, res_msg = apply_update(manifest, self.config_data, log_fn=self.append_log)
                self.append_log(f"\n{res_msg}\n")
                if ok:
                    self.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Aktualizace dokončena",
                            "Bot byl úspěšně zaktualizován! Pro uplatnění změn prosím restartujte aplikaci.",
                        ),
                    )
                else:
                    self.after(0, lambda: messagebox.showerror("Chyba aktualizace", res_msg))

            threading.Thread(target=_apply, daemon=True).start()

    def test_webhook(self):
        url = self.entry_webhook.get().strip()
        if not url:
            messagebox.showwarning("Webhook", "Zadejte nejprve Discord Webhook URL.")
            return

        def _send():
            async def _coro():
                await send_discord_webhook(
                    url,
                    "🔔 Test z Mafia Reborn Windows App",
                    "Spojení mezi aplikací a Discordem funguje na 100 %! 🎉",
                    color=0x3498DB,
                )

            asyncio.run(_coro())
            self.after(0, lambda: messagebox.showinfo("Discord", "Zkušební zpráva byla odeslána na váš Discord!"))

        threading.Thread(target=_send, daemon=True).start()

    def start_bot(self):
        if self.learn_runner.is_recording:
            messagebox.showwarning("Upozornění", "Režim učení právě běží. Nejprve jej ukončete.")
            return
        self.save_settings()
        self.runner.start(self.config_data)

    def stop_bot(self):
        self.runner.stop()

    def _on_close(self):
        if self.runner.is_running or self.learn_runner.is_recording:
            if messagebox.askyesno("Ukončení", "Aktivita stále běží. Opravdu chcete aplikaci ukončit?"):
                if self.runner.is_running:
                    self.runner.stop()
                if self.learn_runner.is_recording:
                    self.learn_runner.stop()
                self.destroy()
        else:
            self.destroy()


def main():
    app = MafiaApp()
    app.mainloop()


if __name__ == "__main__":
    main()
