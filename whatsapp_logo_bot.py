import os
import json
import re
import uuid
import unicodedata
from pathlib import Path
from typing import Dict, Tuple

import requests
import numpy as np
from flask import Flask, request, send_from_directory, url_for
from PIL import Image

# moviepy (vÃƒÂ­deo)
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from moviepy.video.VideoClip import VideoClip as MPVideoClip

# =========================
# CONFIG
# =========================


VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0")
WHATSAPP_TOKEN = (
    os.getenv("WHATSAPP_TOKEN")
    or os.getenv("META_TOKEN")
    or os.getenv("META_ACCESS_TOKEN")
    or ""
)
WHATSAPP_PHONE_NUMBER_ID = (
    os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    or os.getenv("PHONE_NUMBER_ID")
    or ""
)

# Pasta onde vamos salvar mÃƒÂ­dias recebidas e processadas
BASE_DIR = Path(__file__).parent
IN_DIR = BASE_DIR / "in_media"
OUT_DIR = BASE_DIR / "out_media"
IN_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# Logo fixa (certifique-se que o arquivo logo.png existe nesta pasta)
LOGO_PATH = BASE_DIR / "logo.png"

# Base publica para servir a midia processada.
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL") or (
    f"https://{_railway_domain}" if _railway_domain else ""
)

# Ajustes padrÃƒÂ£o da logo
DEFAULT_POSITION = "Canto superior esquerdo"

# --- AQUI ESTÃƒÂ O CONTROLE DO TAMANHO ---
# Estava 18. Tente 35 ou 40 para ficar bem maior.
# Esse nÃƒÂºmero representa a porcentagem da largura da imagem total que a logo vai ocupar.
DEFAULT_SIZE_PCT = 20
DEFAULT_MARGIN_PCT = 3  # Margem (distÃƒÂ¢ncia da borda)

MIN_SIZE_PCT = 1
MAX_SIZE_PCT = 50
MIN_MARGIN_PCT = 0
MAX_MARGIN_PCT = 20

ALLOWED_POSITIONS = {
    "canto superior esquerdo": "Canto superior esquerdo",
    "centro superior": "Centro superior",
    "canto superior direito": "Canto superior direito",
    "centro": "Centro",
    "canto inferior esquerdo": "Canto inferior esquerdo",
    "centro inferior": "Centro inferior",
    "canto inferior direito": "Canto inferior direito",
}

app = Flask(__name__)
SETTINGS_PATH = BASE_DIR / "user_presets.json"
USER_SETTINGS: Dict[str, Dict[str, object]] = {}


def _default_user_settings() -> Dict[str, object]:
    return {
        "position": DEFAULT_POSITION,
        "size_pct": DEFAULT_SIZE_PCT,
        "margin_pct": DEFAULT_MARGIN_PCT,
    }


def _normalize_text(value: str) -> str:
    value = value or ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    return " ".join(value.split())


def _normalize_position(value: str) -> str:
    normalized = _normalize_text(value)

    if normalized in ALLOWED_POSITIONS:
        return ALLOWED_POSITIONS[normalized]

    if "superior" in normalized and "esquerda" in normalized:
        return "Canto superior esquerdo"
    if "superior" in normalized and "direita" in normalized:
        return "Canto superior direito"
    if "superior" in normalized and "centro" in normalized:
        return "Centro superior"
    if "inferior" in normalized and "esquerda" in normalized:
        return "Canto inferior esquerdo"
    if "inferior" in normalized and "direita" in normalized:
        return "Canto inferior direito"
    if "inferior" in normalized and "centro" in normalized:
        return "Centro inferior"
    if normalized in {"centro", "meio"}:
        return "Centro"
    return ""


def _sanitize_user_settings(settings: Dict[str, object]) -> Dict[str, object]:
    defaults = _default_user_settings()
    position = _normalize_position(str(settings.get("position", defaults["position"])))
    size_raw = settings.get("size_pct", defaults["size_pct"])
    margin_raw = settings.get("margin_pct", defaults["margin_pct"])

    try:
        size_pct = int(size_raw)
    except (TypeError, ValueError):
        size_pct = int(defaults["size_pct"])

    try:
        margin_pct = int(margin_raw)
    except (TypeError, ValueError):
        margin_pct = int(defaults["margin_pct"])

    return {
        "position": position or defaults["position"],
        "size_pct": max(MIN_SIZE_PCT, min(MAX_SIZE_PCT, size_pct)),
        "margin_pct": max(MIN_MARGIN_PCT, min(MAX_MARGIN_PCT, margin_pct)),
    }


def _load_user_settings() -> None:
    global USER_SETTINGS
    if not SETTINGS_PATH.exists():
        USER_SETTINGS = {}
        return

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            USER_SETTINGS = {}
            return
        parsed: Dict[str, Dict[str, object]] = {}
        for phone, settings in data.items():
            if isinstance(phone, str) and isinstance(settings, dict):
                parsed[phone] = _sanitize_user_settings(settings)
        USER_SETTINGS = parsed
    except Exception as e:
        print(f"Falha ao carregar presets: {e}")
        USER_SETTINGS = {}


def _save_user_settings() -> None:
    try:
        SETTINGS_PATH.write_text(
            json.dumps(USER_SETTINGS, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"Falha ao salvar presets: {e}")


def get_user_settings(phone: str) -> Dict[str, object]:
    settings = USER_SETTINGS.get(phone)
    if not settings:
        settings = _default_user_settings()
    settings = _sanitize_user_settings(settings)
    USER_SETTINGS[phone] = settings
    return settings


def set_user_settings(phone: str, settings: Dict[str, object]) -> Dict[str, object]:
    normalized = _sanitize_user_settings(settings)
    USER_SETTINGS[phone] = normalized
    _save_user_settings()
    return normalized


def format_status_message(settings: Dict[str, object]) -> str:
    positions = ", ".join(ALLOWED_POSITIONS.values())
    return (
        "Status atual:\n"
        f"- Margem: {settings['margin_pct']}%\n"
        f"- Tamanho da logo: {settings['size_pct']}%\n"
        f"- Posicao: {settings['position']}\n\n"
        "Comandos:\n"
        f"- margem <{MIN_MARGIN_PCT}-{MAX_MARGIN_PCT}>\n"
        f"- tamanho <{MIN_SIZE_PCT}-{MAX_SIZE_PCT}>\n"
        "- posicao <nome>\n"
        "- status\n"
        "- reset\n\n"
        f"Posicoes aceitas: {positions}"
    )


def handle_text_command(from_number: str, text: str) -> None:
    raw_text = (text or "").strip()
    cmd = _normalize_text(raw_text)
    settings = get_user_settings(from_number)

    if not cmd or cmd in {"status", "config", "configuracao", "configuracoes", "ajuda", "help"}:
        send_whatsapp_text(from_number, format_status_message(settings))
        return

    if cmd in {"reset", "padrao", "default"}:
        settings = set_user_settings(from_number, _default_user_settings())
        send_whatsapp_text(from_number, "Preset resetado.\n\n" + format_status_message(settings))
        return

    if cmd.startswith("margem"):
        match = re.search(r"-?\d+", cmd)
        if not match:
            send_whatsapp_text(from_number, f"Use: margem <{MIN_MARGIN_PCT}-{MAX_MARGIN_PCT}>")
            return
        margin_pct = max(MIN_MARGIN_PCT, min(MAX_MARGIN_PCT, int(match.group(0))))
        settings["margin_pct"] = margin_pct
        settings = set_user_settings(from_number, settings)
        send_whatsapp_text(from_number, f"Margem atualizada para {margin_pct}%.\n\n" + format_status_message(settings))
        return

    if cmd.startswith("tamanho"):
        match = re.search(r"-?\d+", cmd)
        if not match:
            send_whatsapp_text(from_number, f"Use: tamanho <{MIN_SIZE_PCT}-{MAX_SIZE_PCT}>")
            return
        size_pct = max(MIN_SIZE_PCT, min(MAX_SIZE_PCT, int(match.group(0))))
        settings["size_pct"] = size_pct
        settings = set_user_settings(from_number, settings)
        send_whatsapp_text(from_number, f"Tamanho atualizado para {size_pct}%.\n\n" + format_status_message(settings))
        return

    if cmd.startswith("posicao"):
        desired = raw_text.split(" ", 1)[1].strip() if " " in raw_text else ""
        parsed = _normalize_position(desired)
        if not parsed:
            send_whatsapp_text(from_number, "Use: posicao <nome>. Envie 'status' para ver as opcoes.")
            return
        settings["position"] = parsed
        settings = set_user_settings(from_number, settings)
        send_whatsapp_text(from_number, f"Posicao atualizada para: {parsed}.\n\n" + format_status_message(settings))
        return

    direct_position = _normalize_position(raw_text)
    if direct_position:
        settings["position"] = direct_position
        settings = set_user_settings(from_number, settings)
        send_whatsapp_text(from_number, f"Posicao atualizada para: {direct_position}.\n\n" + format_status_message(settings))
        return

    send_whatsapp_text(
        from_number,
        "Comando nao reconhecido. Envie 'status' para ver configuracoes e opcoes.",
    )


# =========================
# HELPERS (CÃƒÂ¡lculo de tamanho e posiÃƒÂ§ÃƒÂ£o)
# =========================
def compute_logo_size(
        base_size: Tuple[int, int],
        logo_size: Tuple[int, int],
        size_pct: int,
        margin_pct: int,
) -> Tuple[int, int, int]:
    base_w, base_h = base_size
    logo_w, logo_h = logo_size

    size_pct = max(MIN_SIZE_PCT, min(MAX_SIZE_PCT, int(size_pct)))
    margin_pct = max(MIN_MARGIN_PCT, min(MAX_MARGIN_PCT, int(margin_pct)))

    target_w = int(base_w * (size_pct / 100.0))
    scale = target_w / float(logo_w)
    new_w = max(1, int(logo_w * scale))
    new_h = max(1, int(logo_h * scale))

    margin_px = int(min(base_w, base_h) * (margin_pct / 100.0))
    return new_w, new_h, margin_px


def pick_position(base_w: int, base_h: int, logo_w: int, logo_h: int, margin_px: int, position: str):
    positions = {
        "Canto superior esquerdo": (margin_px, margin_px),
        "Centro superior": ((base_w - logo_w) // 2, margin_px),
        "Canto superior direito": (base_w - logo_w - margin_px, margin_px),
        "Centro": ((base_w - logo_w) // 2, (base_h - logo_h) // 2),
        "Canto inferior esquerdo": (margin_px, base_h - logo_h - margin_px),
        "Centro inferior": ((base_w - logo_w) // 2, base_h - logo_h - margin_px),
        "Canto inferior direito": (base_w - logo_w - margin_px, base_h - logo_h - margin_px),
    }
    x, y = positions.get(position, positions["Canto inferior direito"])
    return (max(0, x), max(0, y))


def safe_ext_from_content_type(ct: str) -> str:
    ct = (ct or "").lower()
    if "image/jpeg" in ct: return ".jpg"
    if "image/png" in ct: return ".png"
    if "image/webp" in ct: return ".webp"
    if "video/mp4" in ct: return ".mp4"
    if "video/quicktime" in ct: return ".mov"
    return ""


def meta_headers() -> dict:
    return {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}


def download_whatsapp_media(media_id: str, dest: Path) -> Tuple[Path, str]:
    """
    Busca URL temporaria da media na Meta e baixa o arquivo.
    """
    if not WHATSAPP_TOKEN:
        raise RuntimeError("WHATSAPP_TOKEN nao configurado.")

    media_meta_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}"
    try:
        meta_resp = requests.get(media_meta_url, headers=meta_headers(), timeout=30)
        meta_resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Falha ao consultar media na Meta: {e}") from e
    media_url = (meta_resp.json() or {}).get("url")
    ct = (meta_resp.json() or {}).get("mime_type", "")

    if not media_url:
        raise RuntimeError("Meta nao retornou URL da media.")

    try:
        media_resp = requests.get(media_url, headers=meta_headers(), stream=True, timeout=120)
        media_resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Falha ao baixar arquivo da Meta: {e}") from e
    ct = media_resp.headers.get("Content-Type", ct)

    ext = safe_ext_from_content_type(ct)
    if ext and dest.suffix.lower() != ext:
        dest = dest.with_suffix(ext)

    with open(dest, "wb") as f:
        for chunk in media_resp.iter_content(chunk_size=1024 * 256):
            if chunk:
                f.write(chunk)
    return dest, ct


def send_whatsapp_text(to_number: str, body: str) -> bool:
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("Config ausente: WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID.")
        return False

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": body},
    }
    try:
        resp = requests.post(
            url,
            headers={**meta_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        print(f"Erro de rede ao enviar texto: {e}")
        return False
    if not resp.ok:
        print(f"Erro ao enviar texto: {resp.status_code} - {resp.text}")
    return resp.ok


def send_whatsapp_media(to_number: str, media_type: str, media_link: str, caption: str = "") -> bool:
    if media_type not in {"image", "video"}:
        return False
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("Config ausente: WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID.")
        return False

    media_obj = {"link": media_link}
    if caption:
        media_obj["caption"] = caption

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": media_type,
        media_type: media_obj,
    }
    try:
        resp = requests.post(
            url,
            headers={**meta_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        print(f"Erro de rede ao enviar media: {e}")
        return False
    if not resp.ok:
        print(f"Erro ao enviar media: {resp.status_code} - {resp.text}")
    return resp.ok


# =========================
# PROCESS IMAGE
# =========================
def apply_logo_to_image(image_path: Path, logo_path: Path,
                        position=DEFAULT_POSITION, size_pct=DEFAULT_SIZE_PCT, margin_pct=DEFAULT_MARGIN_PCT) -> Path:
    base = Image.open(image_path).convert("RGBA")
    logo = Image.open(logo_path).convert("RGBA")

    base_w, base_h = base.size
    new_w, new_h, margin_px = compute_logo_size((base_w, base_h), logo.size, size_pct, margin_pct)
    logo_r = logo.resize((new_w, new_h), Image.LANCZOS)

    pos = pick_position(base_w, base_h, new_w, new_h, margin_px, position)

    out = base.copy()
    out.paste(logo_r, pos, logo_r)

    out_name = image_path.stem + "_logo.jpg"
    out_path = OUT_DIR / out_name
    out.convert("RGB").save(out_path, "JPEG", quality=95)
    return out_path


# =========================
# PROCESS VIDEO
# =========================
# =========================
# PROCESS VIDEO (CORRIGIDO)
# =========================
def apply_logo_to_video(video_path: Path, logo_path: Path,
                        position=DEFAULT_POSITION, size_pct=DEFAULT_SIZE_PCT, margin_pct=DEFAULT_MARGIN_PCT) -> Path:
    logo = Image.open(logo_path).convert("RGBA")

    with VideoFileClip(str(video_path)) as clip:
        base_w, base_h = clip.w, clip.h
        duration = clip.duration or 0

        new_w, new_h, margin_px = compute_logo_size((base_w, base_h), logo.size, size_pct, margin_pct)
        logo_r = logo.resize((new_w, new_h), Image.LANCZOS)

        pos = pick_position(base_w, base_h, new_w, new_h, margin_px, position)

        # Prepara o logo como clip
        rgb = np.array(logo_r.convert("RGB"))
        alpha = np.array(logo_r.split()[3], dtype=float) / 255.0

        # CORREÃƒâ€¡ÃƒÆ’O AQUI: ismask (sem underline)
        logo_clip = ImageClip(rgb, ismask=False, duration=duration)
        logo_clip = logo_clip.set_position(pos).set_start(0)

        def mask_frame(t, base_alpha=alpha):
            return base_alpha

        # CORREÃƒâ€¡ÃƒÆ’O AQUI: ismask (sem underline)
        mask_clip = MPVideoClip(mask_frame, ismask=True, duration=duration)
        mask_clip = mask_clip.set_position(pos).set_start(0)
        mask_clip.size = (new_w, new_h)

        logo_clip.mask = mask_clip

        composite = CompositeVideoClip([clip, logo_clip])

        out_name = video_path.stem + "_logo.mp4"
        out_path = OUT_DIR / out_name

        composite.write_videofile(
            str(out_path),
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(out_path.with_suffix(".temp-audio.m4a")),
            remove_temp=True,
            threads=2,
            logger=None,
        )
        composite.close()

    return out_path


# =========================
# SERVE PROCESSED MEDIA
# AQUI ESTAVA O ERRO PRINCIPAL
# =========================
@app.route("/media/<path:filename>")
def media(filename):
    # Usando send_from_directory que jÃƒÂ¡ estÃƒÂ¡ importado e ÃƒÂ© seguro
    return send_from_directory(OUT_DIR, filename)


# =========================
# WHATSAPP WEBHOOK
# =========================
@app.get("/")
def home():
    return "Servidor WhatsApp OK", 200


@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and VERIFY_TOKEN and token == VERIFY_TOKEN:
        return challenge or "", 200
    return "error", 403


@app.post("/webhook")
def whatsapp_cloud_events():
    data = request.get_json(silent=True) or {}

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for incoming_message in value.get("messages", []):
                try:
                    handle_incoming_message(incoming_message)
                except Exception as e:
                    print(f"Erro ao processar mensagem recebida: {e}")

    return "EVENT_RECEIVED", 200


def handle_incoming_message(message: dict) -> None:
    from_number = message.get("from")
    message_type = message.get("type")

    if not from_number:
        return

    if message_type == "text":
        text_body = (message.get("text") or {}).get("body", "")
        handle_text_command(from_number, text_body)
        return

    if message_type not in {"image", "video"}:
        send_whatsapp_text(
            from_number,
            "Envie uma foto/video para aplicar logo ou envie 'status' para configurar preset.",
        )
        return

    media_id = (message.get(message_type) or {}).get("id")
    if not media_id:
        send_whatsapp_text(from_number, "Nao consegui identificar a media enviada.")
        return

    if not PUBLIC_BASE_URL:
        send_whatsapp_text(from_number, "Erro de configuracao: PUBLIC_BASE_URL nao definido.")
        return

    uid = uuid.uuid4().hex
    in_path = IN_DIR / f"in_{uid}"

    try:
        downloaded_path, media_content_type = download_whatsapp_media(media_id, in_path)
    except Exception as e:
        print(f"Erro download Meta: {e}")
        send_whatsapp_text(from_number, "Nao consegui baixar sua midia.")
        return

    try:
        user_settings = get_user_settings(from_number)
        position = str(user_settings["position"])
        size_pct = int(user_settings["size_pct"])
        margin_pct = int(user_settings["margin_pct"])

        if "image/" in (media_content_type or ""):
            out_path = apply_logo_to_image(
                downloaded_path,
                LOGO_PATH,
                position=position,
                size_pct=size_pct,
                margin_pct=margin_pct,
            )
            outbound_type = "image"
        elif "video/" in (media_content_type or ""):
            out_path = apply_logo_to_video(
                downloaded_path,
                LOGO_PATH,
                position=position,
                size_pct=size_pct,
                margin_pct=margin_pct,
            )
            outbound_type = "video"
        else:
            send_whatsapp_text(from_number, "Tipo de arquivo nao suportado. Envie imagem ou video.")
            return
    except Exception as e:
        print(f"Erro processamento: {e}")
        send_whatsapp_text(from_number, "Falha ao aplicar logo na sua midia.")
        return

    public_file_url = f"{PUBLIC_BASE_URL}{url_for('media', filename=out_path.name)}"
    sent = send_whatsapp_media(from_number, outbound_type, public_file_url)
    if not sent:
        send_whatsapp_text(from_number, f"Processado. Baixe aqui: {public_file_url}")


_load_user_settings()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
