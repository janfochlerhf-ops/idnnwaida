import json
import os
import re
import shutil
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

VERSION = "1.0.0"
CONFIG_FILE = "config.json"
BACKUP_DIR = ".backups"


def get_current_version() -> str:
    """Vrací aktuální verzi bota."""
    return VERSION


def parse_semver(version_str: str) -> Tuple[int, ...]:
    """Převede řetězec verze (např. '1.0.2' nebo 'v1.2') na porovnatelnou n-tici čísel."""
    numbers = [int(n) for n in re.findall(r"\d+", version_str)]
    return tuple(numbers) if numbers else (0,)


def check_for_updates(config: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Zkontroluje vzdálený manifest version.json a zjistí, zda je dostupná nová verze.
    Vrací: (is_update_available, message, manifest_data)
    """
    update_url = config.get("update_url", "").strip()
    if not update_url:
        return (
            False,
            "Aktualizační URL není v config.json nastavena.\n"
            "Chcete-li bota aktualizovat na dálku bez posílání souborů, vložte do Nastavení odkaz na svůj GitHub nebo server.",
            None,
        )

    # Pokud byla zadána přímo URL na version.json nebo bázová URL složky/repozitáře
    if update_url.endswith(".json"):
        manifest_url = update_url
    else:
        manifest_url = update_url.rstrip("/") + "/version.json"

    try:
        req = urllib.request.Request(
            manifest_url,
            headers={"User-Agent": f"MafiaBotUpdater/{VERSION} (Windows/Mac; autonomous)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        remote_version = data.get("version", "").strip()
        if not remote_version:
            return False, "Vzdálený manifest neobsahuje platné číslo verze.", None

        local_ver = config.get("version", VERSION)
        if parse_semver(remote_version) > parse_semver(local_ver):
            changelog = data.get("changelog", "Byla vydána nová verze s vylepšeními.")
            msg = (
                f"🎉 Byla nalezena nová verze: {remote_version} (aktuální: {local_ver})!\n\n"
                f"Popis změn:\n{changelog}"
            )
            return True, msg, data
        else:
            return False, f"Používáte nejnovější verzi bota (v{local_ver}).", data

    except Exception as e:
        return False, f"Nepodařilo se zkontrolovat aktualizace: {e}", None


def apply_update(
    manifest: Dict[str, Any], config: Dict[str, Any], log_fn=print
) -> Tuple[bool, str]:
    """
    Stáhne aktualizované soubory, bezpečně zazálohuje stávající soubory do .backups/
    a přepíše je novým kódem.
    """
    files = manifest.get("files", {})
    if not files:
        return False, "Aktualizační manifest neobsahuje žádné soubory k instalaci."

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = int(time.time())
    backup_ver_dir = os.path.join(BACKUP_DIR, f"backup_v{VERSION}_{timestamp}")
    os.makedirs(backup_ver_dir, exist_ok=True)

    downloaded = {}
    try:
        # Fáze 1: Stáhneme všechny soubory do paměti (pokud některý selže, původní kód se nepoškodí)
        for filename, file_url in files.items():
            log_fn(f"-> Stahuji aktualizovaný soubor: {filename}...")
            req = urllib.request.Request(
                file_url,
                headers={"User-Agent": f"MafiaBotUpdater/{VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                downloaded[filename] = resp.read()

        # Fáze 2: Záloha stávajících souborů
        for filename in downloaded.keys():
            if os.path.exists(filename):
                shutil.copy2(filename, os.path.join(backup_ver_dir, filename))

        # Fáze 3: Přepsání souborů novým obsahem
        for filename, content in downloaded.items():
            with open(filename, "wb") as f:
                f.write(content)
            log_fn(f"[✓] {filename} úspěšně aktualizován.")

        # Aktualizujeme verzi v config.json
        new_version = manifest.get("version", VERSION)
        config["version"] = new_version
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        return (
            True,
            f"🎉 Bot byl úspěšně aktualizován na verzi {new_version}!\n"
            f"Záloha původních souborů byla uložena do: {backup_ver_dir}",
        )

    except Exception as e:
        return False, f"Chyba při instalaci aktualizace: {e}"
