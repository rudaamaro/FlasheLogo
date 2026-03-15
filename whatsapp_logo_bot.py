import os
import uuid
from pathlib import Path
from typing import Tuple

import requests
import numpy as np
from flask import Flask, request, send_from_directory, url_for, Response
from twilio.twiml.messaging_response import MessagingResponse
from PIL import Image

# moviepy (vídeo)
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from moviepy.video.VideoClip import VideoClip as MPVideoClip

# =========================
# CONFIG
# =========================

ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")

# Pasta onde vamos salvar mídias recebidas e processadas
BASE_DIR = Path(__file__).parent
IN_DIR = BASE_DIR / "in_media"
OUT_DIR = BASE_DIR / "out_media"
IN_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# Logo fixa (certifique-se que o arquivo logo.png existe nesta pasta)
LOGO_PATH = BASE_DIR / "logo.png"

# SEU DOMÍNIO DO NGROK (Atualizado conforme seu print)
# IMPORTANTE: Se você reiniciar o ngrok, essa URL muda e você precisa atualizar aqui.
PUBLIC_BASE_URL = "https://epidemiologically-odourless-casen.ngrok-free.dev"

# Ajustes padrão da logo
DEFAULT_POSITION = "Canto superior esquerdo"

# --- AQUI ESTÁ O CONTROLE DO TAMANHO ---
# Estava 18. Tente 35 ou 40 para ficar bem maior.
# Esse número representa a porcentagem da largura da imagem total que a logo vai ocupar.
DEFAULT_SIZE_PCT = 35

DEFAULT_MARGIN_PCT = 3  # Margem (distância da borda)

app = Flask(__name__)


# =========================
# HELPERS (Cálculo de tamanho e posição)
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


def download_twilio_media(url: str, dest: Path) -> Tuple[Path, str]:
    """
    Twilio MediaUrl exige Basic Auth com AccountSid:AuthToken para baixar.
    """
    r = requests.get(url, auth=(ACCOUNT_SID, AUTH_TOKEN), stream=True, timeout=60)
    r.raise_for_status()
    ct = r.headers.get("Content-Type", "")
    ext = safe_ext_from_content_type(ct)
    if ext and dest.suffix.lower() != ext:
        dest = dest.with_suffix(ext)

    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 256):
            if chunk:
                f.write(chunk)
    return dest, ct


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

        # CORREÇÃO AQUI: ismask (sem underline)
        logo_clip = ImageClip(rgb, ismask=False, duration=duration)
        logo_clip = logo_clip.set_position(pos).set_start(0)

        def mask_frame(t, base_alpha=alpha):
            return base_alpha

        # CORREÇÃO AQUI: ismask (sem underline)
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
    # Usando send_from_directory que já está importado e é seguro
    return send_from_directory(OUT_DIR, filename)


# =========================
# WHATSAPP WEBHOOK
# =========================
@app.get("/")
def home():
    return "Servidor WhatsApp OK", 200


@app.post("/whatsapp")
def whatsapp_webhook():
    resp = MessagingResponse()
    msg = resp.message()

    num_media = int(request.form.get("NumMedia", "0") or "0")

    # Se não tiver mídia, pede uma
    if num_media <= 0:
        msg.body("Manda uma *foto* ou *vídeo* aqui que eu devolvo com a logo ✅")
        return Response(str(resp), mimetype="application/xml")

    media_url = request.form.get("MediaUrl0", "")
    media_type = request.form.get("MediaContentType0", "")

    # 1. Baixar a mídia
    uid = uuid.uuid4().hex
    in_path = IN_DIR / f"in_{uid}"

    try:
        downloaded_path, ct = download_twilio_media(media_url, in_path)
    except Exception as e:
        print(f"Erro download: {e}")
        msg.body(f"Não consegui baixar a mídia. Erro: {e}")
        return Response(str(resp), mimetype="application/xml")

    # 2. Processar a mídia
    out_path = None
    try:
        if "image/" in (media_type or ""):
            out_path = apply_logo_to_image(downloaded_path, LOGO_PATH)
        elif "video/" in (media_type or ""):
            # Atenção: Vídeos longos podem causar timeout no Twilio (15s limite)
            out_path = apply_logo_to_video(downloaded_path, LOGO_PATH)
        else:
            msg.body(f"Tipo não suportado: {media_type}. Envie imagem ou vídeo.")
            return Response(str(resp), mimetype="application/xml")
    except Exception as e:
        print(f"Erro processamento: {e}")
        msg.body(f"Falha ao aplicar logo. Erro: {e}")
        return Response(str(resp), mimetype="application/xml")

    # 3. Enviar de volta
    if not PUBLIC_BASE_URL:
        msg.body("Erro de config: PUBLIC_BASE_URL não configurado.")
        return Response(str(resp), mimetype="application/xml")

    # Gera a URL pública para o Twilio baixar a imagem processada
    # url_for('media', ...) vai criar algo como /media/nome_arquivo.jpg
    public_file_url = f"{PUBLIC_BASE_URL}{url_for('media', filename=out_path.name)}"

    print(f"Enviando de volta: {public_file_url}")  # Log para debug

    msg.body("Pronto ✅ aqui está:")
    msg.media(public_file_url)

    return Response(str(resp), mimetype="application/xml")


if __name__ == "__main__":
    # debug=True ajuda a ver erros no terminal se acontecerem
    app.run(host="0.0.0.0", port=5000, debug=True)