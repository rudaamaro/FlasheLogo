import os
import uuid
from pathlib import Path
from typing import Tuple

import requests
import numpy as np
from flask import Flask, request, send_from_directory, url_for
from PIL import Image

# moviepy (vÃ­deo)
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from moviepy.video.VideoClip import VideoClip as MPVideoClip

# =========================
# CONFIG
# =========================

<<<<<<< HEAD
ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
=======
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
>>>>>>> 62d829b (mudança do codigo)

# Pasta onde vamos salvar mÃ­dias recebidas e processadas
BASE_DIR = Path(__file__).parent
IN_DIR = BASE_DIR / "in_media"
OUT_DIR = BASE_DIR / "out_media"
IN_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# Logo fixa (certifique-se que o arquivo logo.png existe nesta pasta)
LOGO_PATH = BASE_DIR / "logo.png"

<<<<<<< HEAD
# SEU DOMÍNIO DO NGROK (Atualizado conforme seu print)
# IMPORTANTE: Se você reiniciar o ngrok, essa URL muda e você precisa atualizar aqui.
=======
# SEU DOMÃNIO DO NGROK (Atualizado conforme seu print)
# IMPORTANTE: Se vocÃª reiniciar o ngrok, essa URL muda e vocÃª precisa atualizar aqui.
>>>>>>> 62d829b (mudança do codigo)
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL") or (
    f"https://{_railway_domain}" if _railway_domain else ""
)

# Ajustes padrÃ£o da logo
DEFAULT_POSITION = "Canto superior esquerdo"

# --- AQUI ESTÃ O CONTROLE DO TAMANHO ---
# Estava 18. Tente 35 ou 40 para ficar bem maior.
# Esse nÃºmero representa a porcentagem da largura da imagem total que a logo vai ocupar.
DEFAULT_SIZE_PCT = 35

DEFAULT_MARGIN_PCT = 3  # Margem (distÃ¢ncia da borda)

app = Flask(__name__)


# =========================
# HELPERS (CÃ¡lculo de tamanho e posiÃ§Ã£o)
# =========================
def compute_logo_size(
        base_size: Tuple[int, int],
        logo_size: Tuple[int, int],
        size_pct: int,
        margin_pct: int,
) -> Tuple[int, int, int]:
    base_w, base_h = base_size
    logo_w, logo_h = logo_size

    size_pct = max(1, min(50, int(size_pct)))
    margin_pct = max(0, min(20, int(margin_pct)))

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
    meta_resp = requests.get(media_meta_url, headers=meta_headers(), timeout=30)
    meta_resp.raise_for_status()
    media_url = (meta_resp.json() or {}).get("url")
    ct = (meta_resp.json() or {}).get("mime_type", "")

    if not media_url:
        raise RuntimeError("Meta nao retornou URL da media.")

    media_resp = requests.get(media_url, headers=meta_headers(), stream=True, timeout=120)
    media_resp.raise_for_status()
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
    resp = requests.post(
        url,
        headers={**meta_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
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
    resp = requests.post(
        url,
        headers={**meta_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
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

        # CORREÃ‡ÃƒO AQUI: ismask (sem underline)
        logo_clip = ImageClip(rgb, ismask=False, duration=duration)
        logo_clip = logo_clip.set_position(pos).set_start(0)

        def mask_frame(t, base_alpha=alpha):
            return base_alpha

        # CORREÃ‡ÃƒO AQUI: ismask (sem underline)
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
    # Usando send_from_directory que jÃ¡ estÃ¡ importado e Ã© seguro
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
<<<<<<< HEAD

    if mode == "subscribe" and VERIFY_TOKEN and token == VERIFY_TOKEN:
        return challenge or "", 200
    return "error", 403


@app.post("/webhook")
def whatsapp_cloud_events():
    return "EVENT_RECEIVED", 200


@app.post("/whatsapp")
def whatsapp_webhook():
    resp = MessagingResponse()
    msg = resp.message()
=======
>>>>>>> 62d829b (mudança do codigo)

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
                handle_incoming_message(incoming_message)

    return "EVENT_RECEIVED", 200


def handle_incoming_message(message: dict) -> None:
    from_number = message.get("from")
    message_type = message.get("type")

    if not from_number:
        return

    if message_type not in {"image", "video"}:
        send_whatsapp_text(from_number, "Envie uma foto ou video para eu aplicar a logo.")
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
        if "image/" in (media_content_type or ""):
            out_path = apply_logo_to_image(downloaded_path, LOGO_PATH)
            outbound_type = "image"
        elif "video/" in (media_content_type or ""):
            out_path = apply_logo_to_video(downloaded_path, LOGO_PATH)
            outbound_type = "video"
        else:
            send_whatsapp_text(from_number, "Tipo de arquivo nao suportado. Envie imagem ou video.")
            return
    except Exception as e:
        print(f"Erro processamento: {e}")
        send_whatsapp_text(from_number, "Falha ao aplicar logo na sua midia.")
        return

    public_file_url = f"{PUBLIC_BASE_URL}{url_for('media', filename=out_path.name)}"
    sent = send_whatsapp_media(from_number, outbound_type, public_file_url, "Pronto")
    if not sent:
        send_whatsapp_text(from_number, f"Processado. Baixe aqui: {public_file_url}")



if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
