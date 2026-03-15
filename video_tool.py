import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from image_utils import compute_logo_size, load_image, pil_to_qpixmap

CONFIG_PATH = Path(__file__).with_name("watermark_config.json")
OUTPUT_VIDEO_DEFAULT = Path.cwd() / "saidas_com_video"

POSITION_LABELS = [
    "Canto superior esquerdo",
    "Centro superior",
    "Canto superior direito",
    "Centro",
    "Canto inferior esquerdo",
    "Centro inferior",
    "Canto inferior direito",
]


class VideoWatermarkTool(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.video_paths: List[str] = []
        self.video_info: Dict[str, float] = {}  # path -> duration (seconds)
        self.logo_path: Optional[str] = None
        self.default_logo_path: Optional[str] = None
        self.base_output_dir: Path = OUTPUT_VIDEO_DEFAULT
        self.output_dir: Path = OUTPUT_VIDEO_DEFAULT
        self.global_settings: Dict[str, object] = {
            "size": 38,
            "margin": 2,
            "position": "Canto superior esquerdo",
            "fade_in": "Fade",
            "fade_out": "Fade",
            "fade_in_dur": 1.0,
            "fade_out_dur": 1.0,
        }
        self.per_video_settings: Dict[str, Dict[str, object]] = {}
        self.edit_single: bool = False
        self.updating_controls: bool = False
        self.current_time_ms: int = 0
        self.current_duration_ms: int = 0
        self.playing: bool = False
        self.timer = None
        self.load_config()
        self.build_ui()

    # ----------------- Config helpers -----------------
    def _read_config(self) -> Dict[str, object]:
        if CONFIG_PATH.exists():
            try:
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def load_config(self) -> None:
        data = self._read_config()
        saved_logo = data.get("default_logo")
        if saved_logo and Path(saved_logo).exists():
            self.default_logo_path = saved_logo
        saved_output = data.get("video_base_output_dir") or data.get("base_output_dir")
        if saved_output:
            self.base_output_dir = Path(saved_output)
            self.output_dir = self.base_output_dir

    def save_config(self) -> None:
        data = self._read_config()
        data.update(
            {
                "default_logo": self.default_logo_path,
                "video_base_output_dir": str(self.base_output_dir),
            }
        )
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ----------------- UI -----------------
    def build_ui(self) -> None:
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)

        header = QLabel("Ferramenta: Logo em vídeos")
        header.setStyleSheet("font-weight: bold;")
        main_layout.addWidget(header)

        row_videos = QHBoxLayout()
        select_videos_btn = QPushButton("Selecionar vídeos")
        select_videos_btn.clicked.connect(self.select_videos)
        self.videos_label = QLabel("0 selecionados")
        self.videos_label.setMinimumWidth(140)
        row_videos.addWidget(select_videos_btn)
        row_videos.addWidget(self.videos_label)
        row_videos.addStretch()
        main_layout.addLayout(row_videos)

        self.videos_list = QListWidget()
        self.videos_list.setSelectionMode(QListWidget.SingleSelection)
        self.videos_list.itemSelectionChanged.connect(self.on_video_selection_changed)
        main_layout.addWidget(self.videos_list)

        lock_row = QHBoxLayout()
        self.lock_button = QPushButton("[Lock] Ajustar todas")
        self.lock_button.setCheckable(True)
        self.lock_button.setToolTip("Travar: controles valem para todos. Destravar: apenas para o selecionado.")
        self.lock_button.clicked.connect(self.toggle_lock_mode)
        lock_row.addWidget(self.lock_button)
        lock_row.addStretch()
        main_layout.addLayout(lock_row)

        logo_row = QHBoxLayout()
        select_logo_btn = QPushButton("Selecionar logo")
        select_logo_btn.clicked.connect(self.select_logo)
        self.logo_label = QLabel("Nenhuma logo escolhida")
        self.logo_label.setMinimumWidth(200)
        logo_row.addWidget(select_logo_btn)
        logo_row.addWidget(self.logo_label)
        logo_row.addStretch()
        main_layout.addLayout(logo_row)

        default_row = QHBoxLayout()
        self.use_default_checkbox = QCheckBox("Usar logo padrao (se existir)")
        self.use_default_checkbox.stateChanged.connect(self.handle_default_toggle)
        self.save_default_btn = QPushButton("Definir logo atual como padrao")
        self.save_default_btn.clicked.connect(self.set_as_default)
        default_row.addWidget(self.use_default_checkbox)
        default_row.addWidget(self.save_default_btn)
        default_row.addStretch()
        main_layout.addLayout(default_row)

        controls_grid = QGridLayout()
        controls_grid.setVerticalSpacing(12)

        self.position_combo = QComboBox()
        self.position_combo.addItems(POSITION_LABELS)
        self.position_combo.setCurrentText("Canto superior esquerdo")
        self.position_combo.currentIndexChanged.connect(self.on_controls_changed)
        controls_grid.addWidget(QLabel("Posicao"), 0, 0)
        controls_grid.addWidget(self.position_combo, 0, 1)

        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setMinimum(5)
        self.size_slider.setMaximum(50)
        self.size_slider.setValue(38)
        self.size_slider.valueChanged.connect(self.update_size_label)
        self.size_value_label = QLabel("38% (do lado menor)")
        controls_grid.addWidget(QLabel("Tamanho da logo"), 1, 0)
        controls_grid.addWidget(self.size_slider, 1, 1)
        controls_grid.addWidget(self.size_value_label, 1, 2)

        self.margin_slider = QSlider(Qt.Horizontal)
        self.margin_slider.setMinimum(0)
        self.margin_slider.setMaximum(20)
        self.margin_slider.setValue(2)
        self.margin_slider.valueChanged.connect(self.update_margin_label)
        self.margin_value_label = QLabel("2%")
        controls_grid.addWidget(QLabel("Margem"), 2, 0)
        controls_grid.addWidget(self.margin_slider, 2, 1)
        controls_grid.addWidget(self.margin_value_label, 2, 2)

        # Linha: fade in/out
        fade_options = ["None", "Fade"]
        self.fade_in_combo = QComboBox()
        self.fade_in_combo.addItems(fade_options)
        self.fade_in_combo.setCurrentText("Fade")
        self.fade_in_combo.currentIndexChanged.connect(self.on_controls_changed)
        self.fade_out_combo = QComboBox()
        self.fade_out_combo.addItems(fade_options)
        self.fade_out_combo.setCurrentText("Fade")
        self.fade_out_combo.currentIndexChanged.connect(self.on_controls_changed)

        self.fade_in_spin = QDoubleSpinBox()
        self.fade_in_spin.setRange(0.0, 2.0)
        self.fade_in_spin.setSingleStep(0.1)
        self.fade_in_spin.setDecimals(2)
        self.fade_in_spin.setValue(1.0)
        self.fade_in_spin.valueChanged.connect(self.on_controls_changed)

        self.fade_out_spin = QDoubleSpinBox()
        self.fade_out_spin.setRange(0.0, 2.0)
        self.fade_out_spin.setSingleStep(0.1)
        self.fade_out_spin.setDecimals(2)
        self.fade_out_spin.setValue(1.0)
        self.fade_out_spin.valueChanged.connect(self.on_controls_changed)

        controls_grid.addWidget(QLabel("Entrada"), 3, 0)
        fade_in_layout = QHBoxLayout()
        fade_in_layout.addWidget(self.fade_in_combo)
        fade_in_layout.addWidget(QLabel("dur (s):"))
        fade_in_layout.addWidget(self.fade_in_spin)
        fade_in_container = QWidget()
        fade_in_container.setLayout(fade_in_layout)
        controls_grid.addWidget(fade_in_container, 3, 1)

        controls_grid.addWidget(QLabel("Saida"), 4, 0)
        fade_out_layout = QHBoxLayout()
        fade_out_layout.addWidget(self.fade_out_combo)
        fade_out_layout.addWidget(QLabel("dur (s):"))
        fade_out_layout.addWidget(self.fade_out_spin)
        fade_out_container = QWidget()
        fade_out_container.setLayout(fade_out_layout)
        controls_grid.addWidget(fade_out_container, 4, 1)

        # Linha: timeline e play/pause
        timeline_row = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(1000)
        self.timeline_slider.valueChanged.connect(self.on_timeline_scrub)
        self.time_label = QLabel("0.00 / 0.00 s")
        self.time_label.setMinimumWidth(110)
        timeline_row.addWidget(self.play_button)
        timeline_row.addWidget(self.timeline_slider)
        timeline_row.addWidget(self.time_label)
        main_layout.addLayout(timeline_row)

        output_row = QHBoxLayout()
        output_btn = QPushButton("Escolher pasta de saida")
        output_btn.clicked.connect(self.select_output_dir)
        self.output_label = QLabel(str(self.output_dir))
        self.output_label.setWordWrap(True)
        output_row.addWidget(output_btn)
        output_row.addWidget(self.output_label)
        output_row.addStretch()

        main_layout.addLayout(controls_grid)
        main_layout.addLayout(output_row)

        self.preview_label = QLabel("Pre-visualizacao (frame 0)")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(320)
        self.preview_label.setStyleSheet("border: 1px solid #444; background-color: #111; color: #ccc;")
        main_layout.addWidget(self.preview_label)

        apply_btn = QPushButton("Aplicar logo em todos os videos")
        apply_btn.clicked.connect(self.apply_watermark_to_all)
        main_layout.addWidget(apply_btn)

        self.setLayout(main_layout)
        self.refresh_default_state()
        self.global_settings = self.current_control_settings()

    # ----------------- Helpers -----------------
    def refresh_default_state(self) -> None:
        has_default = self.default_logo_path is not None
        self.use_default_checkbox.setEnabled(has_default)
        if has_default and not self.logo_path:
            self.use_default_checkbox.setChecked(True)
        elif not has_default:
            self.use_default_checkbox.setChecked(False)
        self.update_logo_label()

    def update_timeline_duration(self, duration_s: float) -> None:
        self.current_duration_ms = int(duration_s * 1000)
        self.timeline_slider.setMaximum(max(self.current_duration_ms, 1))
        if self.current_time_ms > self.current_duration_ms:
            self.current_time_ms = self.current_duration_ms
        self.timeline_slider.setValue(self.current_time_ms)
        self.update_time_label()

    def update_time_label(self) -> None:
        curr = self.current_time_ms / 1000
        total = self.current_duration_ms / 1000
        self.time_label.setText(f"{curr:.2f} / {total:.2f} s")

    def moviepy_imports(self) -> Tuple[object, object, object]:
        """Import moviepy classes without depender do moviepy.editor (ausente em builds antigos)."""
        try:
            from moviepy.video.io.VideoFileClip import VideoFileClip
            from moviepy.video.VideoClip import ImageClip
            from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip

            return VideoFileClip, ImageClip, CompositeVideoClip
        except Exception as exc:  # pragma: no cover - apenas caminho de erro
            raise ImportError(f"MoviePy não encontrado: {exc}") from exc

    def get_fade_fx(self) -> Tuple[Optional[object], Optional[object]]:
        """Retorna fadein/fadeout se disponíveis; senão None (não trava render)."""
        return None, None  # estamos usando fade manual para compatibilidade

    def update_logo_label(self) -> None:
        chosen = self.logo_path
        default_txt = f" (padrao: {Path(self.default_logo_path).name})" if self.default_logo_path else ""
        if chosen:
            self.logo_label.setText(Path(chosen).name + default_txt)
        elif self.use_default_checkbox.isChecked() and self.default_logo_path:
            self.logo_label.setText(Path(self.default_logo_path).name + " (usando padrao)")
        else:
            self.logo_label.setText("Nenhuma logo escolhida" + default_txt)

    def current_video_path(self) -> Optional[str]:
        item = self.videos_list.currentItem()
        if item:
            data = item.data(Qt.UserRole)
            return data if data else item.text()
        return self.video_paths[0] if self.video_paths else None

    def current_control_settings(self) -> Dict[str, object]:
        return {
            "size": self.size_slider.value(),
            "margin": self.margin_slider.value(),
            "position": self.position_combo.currentText(),
            "fade_in": self.fade_in_combo.currentText(),
            "fade_out": self.fade_out_combo.currentText(),
            "fade_in_dur": round(self.fade_in_spin.value(), 2),
            "fade_out_dur": round(self.fade_out_spin.value(), 2),
        }

    def set_controls_from_settings(self, settings: Dict[str, object]) -> None:
        self.updating_controls = True
        self.size_slider.setValue(int(settings.get("size", self.size_slider.value())))
        self.margin_slider.setValue(int(settings.get("margin", self.margin_slider.value())))
        position = settings.get("position", self.position_combo.currentText())
        if isinstance(position, str) and position in POSITION_LABELS:
            self.position_combo.setCurrentText(position)
        self.size_value_label.setText(f"{self.size_slider.value()}% (do lado menor)")
        self.margin_value_label.setText(f"{self.margin_slider.value()}%")
        fade_in = settings.get("fade_in", "Fade")
        fade_out = settings.get("fade_out", "Fade")
        if isinstance(fade_in, str) and fade_in in ["None", "Fade"]:
            self.fade_in_combo.setCurrentText(fade_in)
        if isinstance(fade_out, str) and fade_out in ["None", "Fade"]:
            self.fade_out_combo.setCurrentText(fade_out)
        self.fade_in_spin.setValue(float(settings.get("fade_in_dur", self.fade_in_spin.value())))
        self.fade_out_spin.setValue(float(settings.get("fade_out_dur", self.fade_out_spin.value())))
        self.updating_controls = False

    def store_current_controls(self) -> None:
        settings = self.current_control_settings()
        if self.edit_single:
            video = self.current_video_path()
            if video:
                self.per_video_settings[video] = settings
        else:
            self.global_settings = settings

    def settings_for_video(self, video: str) -> Dict[str, object]:
        if video in self.per_video_settings:
            return self.per_video_settings[video]
        return self.global_settings

    def ensure_video_info(self, video: str) -> float:
        if video in self.video_info:
            return self.video_info[video]
        try:
            VideoFileClip, _, _ = self.moviepy_imports()
            with VideoFileClip(video) as clip:
                dur = clip.duration or 0
                self.video_info[video] = dur
                return dur
        except Exception:
            return 0.0

    # ----------------- Slots -----------------
    def select_videos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Escolha os videos",
            str(Path.home()),
            "Videos (*.mp4 *.mov *.avi *.mkv *.wmv *.flv)",
        )
        if not files:
            return
        self.video_paths = files
        self.videos_list.clear()
        self.per_video_settings.clear()
        for f in files:
            item = QListWidgetItem(Path(f).name)
            item.setData(Qt.UserRole, f)
            self.videos_list.addItem(item)
        self.videos_label.setText(f"{len(files)} selecionados")
        self.videos_list.setCurrentRow(0)
        self.on_video_selection_changed()

    def select_logo(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Escolha a logo",
            str(Path.home()),
            "Imagens (*.png *.jpg *.jpeg *.bmp *.gif)",
        )
        if not file_path:
            return
        self.logo_path = file_path
        self.use_default_checkbox.setChecked(False)
        self.update_logo_label()
        self.update_preview()

    def set_as_default(self) -> None:
        if not self.logo_path:
            QMessageBox.information(self, "Logo padrao", "Escolha uma logo antes de definir como padrao.")
            return
        self.default_logo_path = self.logo_path
        self.save_config()
        self.refresh_default_state()
        QMessageBox.information(self, "Logo padrao", "Logo definida como padrao.")

    def handle_default_toggle(self, state: int) -> None:
        if state == Qt.Checked:
            self.logo_path = None
        self.update_logo_label()
        self.update_preview()

    def select_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Escolha a pasta de saida", str(self.output_dir))
        if directory:
            self.base_output_dir = Path(directory)
            self.output_dir = self.base_output_dir
            self.output_label.setText(str(self.output_dir))
            self.save_config()

    def update_size_label(self) -> None:
        self.size_value_label.setText(f"{self.size_slider.value()}% (do lado menor)")
        self.on_controls_changed()

    def update_margin_label(self) -> None:
        self.margin_value_label.setText(f"{self.margin_slider.value()}%")
        self.on_controls_changed()

    def on_controls_changed(self) -> None:
        if self.updating_controls:
            return
        self.store_current_controls()
        self.update_preview()

    def toggle_play(self) -> None:
        if self.playing:
            self.stop_playback()
        else:
            self.start_playback()

    def start_playback(self) -> None:
        if self.current_duration_ms <= 0:
            return
        if self.timer is None:
            from PyQt5.QtCore import QTimer

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.advance_frame)
        self.playing = True
        self.play_button.setText("Pause")
        self.timer.start(200)

    def stop_playback(self) -> None:
        if self.timer:
            self.timer.stop()
        self.playing = False
        self.play_button.setText("Play")

    def advance_frame(self) -> None:
        step = 200  # ms
        self.current_time_ms += step
        if self.current_time_ms > self.current_duration_ms:
            self.current_time_ms = self.current_duration_ms
            self.stop_playback()
        self.timeline_slider.blockSignals(True)
        self.timeline_slider.setValue(self.current_time_ms)
        self.timeline_slider.blockSignals(False)
        self.update_time_label()
        self.update_preview()

    def on_timeline_scrub(self, value: int) -> None:
        self.current_time_ms = value
        self.update_time_label()
        self.update_preview()

    def toggle_lock_mode(self) -> None:
        self.edit_single = self.lock_button.isChecked()
        if self.edit_single:
            self.lock_button.setText("[Unlock] Ajustar somente selecionado")
            self.on_video_selection_changed()
        else:
            self.lock_button.setText("[Lock] Ajustar todas")
            self.set_controls_from_settings(self.global_settings)
            self.update_preview()

    def on_video_selection_changed(self) -> None:
        self.stop_playback()
        self.current_time_ms = 0
        if self.edit_single:
            video = self.current_video_path()
            if video:
                dur = self.ensure_video_info(video)
                if dur:
                    self.update_timeline_duration(dur)
                settings = self.per_video_settings.get(video, self.global_settings)
                self.set_controls_from_settings(settings)
        else:
            self.set_controls_from_settings(self.global_settings)
            video = self.current_video_path()
            if video:
                dur = self.ensure_video_info(video)
                if dur:
                    self.update_timeline_duration(dur)
        self.update_preview()

    # ----------------- Render & Apply -----------------
    def get_active_logo_path(self) -> Optional[str]:
        if self.logo_path:
            return self.logo_path
        if self.use_default_checkbox.isChecked():
            return self.default_logo_path
        return None

    def update_preview(self) -> None:
        video_path = self.current_video_path()
        logo_path = self.get_active_logo_path()
        if not video_path or not logo_path:
            self.preview_label.setText("Adicione videos e uma logo para visualizar.")
            self.preview_label.setPixmap(QPixmap())
            return
        try:
            VideoFileClip, _, _ = self.moviepy_imports()
        except Exception as exc:
            self.preview_label.setText(f"Instale moviepy para pré-visualizar: {exc}")
            return
        try:
            with VideoFileClip(video_path) as clip:
                duration = clip.duration or 0
                self.video_info[video_path] = duration
                self.update_timeline_duration(duration)
                t = min(self.current_time_ms / 1000, duration if duration else 0)
                frame = clip.get_frame(t)
                base_img = Image.fromarray(frame).convert("RGBA")
                logo = load_image(Path(logo_path))
                settings = self.settings_for_video(video_path)
                composed = self.compose_frame(base_img, logo, settings, t_s=t, duration_s=duration)
                pix = pil_to_qpixmap(composed, self.preview_label.size())
                self.preview_label.setPixmap(pix)
        except Exception as exc:
            self.preview_label.setText(f"Erro na pre-visualizacao: {exc}")

    def compose_frame(
        self,
        base_img: Image.Image,
        logo: Image.Image,
        settings: Dict[str, object],
        t_s: Optional[float] = None,
        duration_s: Optional[float] = None,
    ) -> Image.Image:
        base_w, base_h = base_img.size
        new_w, new_h, margin_px = compute_logo_size(
            (base_w, base_h), logo.size, int(settings["size"]), int(settings["margin"])
        )
        resized_logo = logo.resize((new_w, new_h), Image.LANCZOS)
        positions = {
            "Canto superior esquerdo": (margin_px, margin_px),
            "Centro superior": ((base_w - new_w) // 2, margin_px),
            "Canto superior direito": (base_w - new_w - margin_px, margin_px),
            "Centro": ((base_w - new_w) // 2, (base_h - new_h) // 2),
            "Canto inferior esquerdo": (margin_px, base_h - new_h - margin_px),
            "Centro inferior": ((base_w - new_w) // 2, base_h - new_h - margin_px),
            "Canto inferior direito": (base_w - new_w - margin_px, base_h - new_h - margin_px),
        }
        pos = positions.get(str(settings["position"]), positions["Canto inferior direito"])
        pos = (max(0, pos[0]), max(0, pos[1]))
        start_t = 0.0
        end_t = duration_s if duration_s is not None else None
        # aplica fade in/out manual para prévia
        alpha_factor = 1.0
        fade_in_choice = str(settings.get("fade_in", "Fade"))
        fade_out_choice = str(settings.get("fade_out", "Fade"))
        fade_in_dur = max(0.0, float(settings.get("fade_in_dur", 0.5)))
        fade_out_dur = max(0.0, float(settings.get("fade_out_dur", 0.5)))
        if t_s is not None:
            if fade_in_choice == "Fade" and fade_in_dur > 0:
                if t_s - start_t < fade_in_dur:
                    alpha_factor *= max(0.0, (t_s - start_t) / fade_in_dur)
            if fade_out_choice == "Fade" and fade_out_dur > 0 and end_t is not None:
                if end_t - t_s < fade_out_dur:
                    alpha_factor *= max(0.0, (end_t - t_s) / fade_out_dur)
        composed = base_img.copy()
        if alpha_factor < 1.0:
            r, g, b, a = resized_logo.split()
            a = a.point(lambda p: int(p * alpha_factor))
            faded_logo = Image.merge("RGBA", (r, g, b, a))
            composed.paste(faded_logo, pos, faded_logo)
        else:
            composed.paste(resized_logo, pos, resized_logo)
        return composed

    def apply_watermark_to_all(self) -> None:
        import sys  # <-- necessário (você usa sys.stderr)
        logo_path = self.get_active_logo_path()
        if not self.video_paths:
            QMessageBox.warning(self, "Faltam videos", "Selecione pelo menos um video.")
            return
        if not logo_path:
            QMessageBox.warning(self, "Falta a logo", "Selecione uma logo ou habilite a logo padrao.")
            return

        # Importa MoviePy de forma mais compatível (editor ou imports diretos)
        try:
            try:
                from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
                from moviepy.video.VideoClip import VideoClip
            except Exception:
                VideoFileClip, ImageClip, CompositeVideoClip = self.moviepy_imports()
                from moviepy.video.VideoClip import VideoClip
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Dependencia faltando",
                f"Instale o moviepy para processar videos:\n{exc}\nUse: pip install moviepy",
            )
            return

        today_folder = f"videos ({date.today().isoformat()})"
        time_folder = datetime.now().strftime("Time %H;%M")
        self.output_dir = self.base_output_dir / today_folder / time_folder
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_label.setText(str(self.output_dir))
        self.save_config()

        succeeded = 0
        failed: List[str] = []
        logo_image = load_image(Path(logo_path))

        for video in self.video_paths:
            try:
                settings = self.settings_for_video(video)

                with VideoFileClip(video) as clip:
                    base_w, base_h = clip.w, clip.h
                    duration = float(clip.duration or 0.0)

                    new_w, new_h, margin_px = compute_logo_size(
                        (base_w, base_h),
                        logo_image.size,
                        int(settings["size"]),
                        int(settings["margin"]),
                    )

                    resized_logo = logo_image.resize((new_w, new_h), Image.LANCZOS)

                    positions = {
                        "Canto superior esquerdo": (margin_px, margin_px),
                        "Centro superior": ((base_w - new_w) // 2, margin_px),
                        "Canto superior direito": (base_w - new_w - margin_px, margin_px),
                        "Centro": ((base_w - new_w) // 2, (base_h - new_h) // 2),
                        "Canto inferior esquerdo": (margin_px, base_h - new_h - margin_px),
                        "Centro inferior": ((base_w - new_w) // 2, base_h - new_h - margin_px),
                        "Canto inferior direito": (base_w - new_w - margin_px, base_h - new_h - margin_px),
                    }
                    pos = positions.get(str(settings["position"]), positions["Canto inferior direito"])
                    pos = (max(0, pos[0]), max(0, pos[1]))

                    start_t = 0.0
                    end_t = duration
                    logo_duration = max(0.001, end_t - start_t)

                    # separa RGB e alpha (fade só no alpha)
                    rgb = np.array(resized_logo.convert("RGB"))
                    base_alpha = (np.array(resized_logo.split()[3], dtype=np.float32) / 255.0)

                    # logo clip (usar setters, não .pos/.start/.end)
                    logo_clip = (
                        ImageClip(rgb)
                        .set_duration(logo_duration)
                        .set_position(pos)
                        .set_start(start_t)
                        .set_end(end_t)
                    )

                    fade_in_dur = float(settings.get("fade_in_dur", 0.5))
                    fade_out_dur = float(settings.get("fade_out_dur", 0.5))
                    fade_in_on = settings.get("fade_in", "Fade") == "Fade" and fade_in_dur > 0
                    fade_out_on = settings.get("fade_out", "Fade") == "Fade" and fade_out_dur > 0

                    def mask_frame(t, a=base_alpha, fi=fade_in_dur, fo=fade_out_dur, dur=logo_duration):
                        factor = 1.0
                        if fade_in_on and t < fi:
                            factor *= max(0.0, t / fi)
                        if fade_out_on and (dur - t) < fo:
                            factor *= max(0.0, (dur - t) / fo)
                        return a * factor

                    # máscara como VideoClip (compatível) - ismask (não is_mask)
                    mask_clip = (
                        VideoClip(make_frame=mask_frame, ismask=True)
                        .set_duration(logo_duration)
                        .set_position(pos)
                        .set_start(start_t)
                        .set_end(end_t)
                    )
                    # algumas versões precisam disso explicitamente
                    mask_clip.size = (new_w, new_h)

                    logo_clip = logo_clip.set_mask(mask_clip)

                    composite = CompositeVideoClip([clip, logo_clip])
                    dest = self.output_dir / (Path(video).stem + "_watermarked" + Path(video).suffix)

                    composite.write_videofile(
                        str(dest),
                        codec="libx264",
                        audio_codec="aac",
                        temp_audiofile=str(dest.with_suffix(".temp-audio.m4a")),
                        remove_temp=True,
                        threads=2,
                        logger=None,
                    )
                    composite.close()
                    succeeded += 1

            except Exception as exc:
                print(f"[video_tool] Falha em {video}: {exc}", file=sys.stderr)
                failed.append(f"{Path(video).name} ({exc})")

        msg = f"Logos aplicadas em {succeeded} video(s)."
        if failed:
            msg += f"\nFalha em: {', '.join(failed)}"
        QMessageBox.information(self, "Concluido", msg)

