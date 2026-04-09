import json
from pathlib import Path
from typing import Any, Dict


def load_settings(filepath: Path | str) -> Dict[str, Any]:
    path = Path(filepath)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(filepath: Path | str, settings: Dict[str, Any]) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_chat_settings(filepath: Path | str, chat_id: str | int) -> Dict[str, Any]:
    settings = load_settings(filepath)
    return settings.get(str(chat_id), {})


def update_chat_settings(
    filepath: Path | str,
    chat_id: str | int,
    time_str: str | None = None,
    enabled: bool | None = None
) -> Dict[str, Any]:
    settings = load_settings(filepath)
    chat_id_str = str(chat_id)
    chat_config = settings.get(chat_id_str, {})
    
    if time_str is not None:
        chat_config["time"] = time_str
    if enabled is not None:
        chat_config["enabled"] = enabled
        
    settings[chat_id_str] = chat_config
    save_settings(filepath, settings)
    return chat_config
