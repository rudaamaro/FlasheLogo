import json
from pathlib import Path
from datetime import date, datetime
from typing import Dict, List, Optional

from PIL import Image
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from image_utils import load_image, pil_to_qpixmap, place_logo

CONFIG_PATH = Path(__file__).with_name("watermark_config.json")
OUTPUT_DEFAULT = Path.cwd() / "saidas_com_logo"

POSITION_LABELS = [
    "Canto superior esquerdo",
    "Centro superior",
    "Canto superior direito",
    "Centro",
    "Canto inferior esquerdo",
    "Centro inferior",
    "Canto inferior direito",
]


class WatermarkTool(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.photo_paths: List[str] = []
        self.logo_path: Optional[str] = None
        self.default_logo_path: Optional[str] = None
        self.output_dir: Path = OUTPUT_DEFAULT
        self.base_output_dir: Path = OUTPUT_DEFAULT
        self.global_settings: Dict[str, object] = {
            "size": 38,
            "margin": 2,
            "position": "Canto superior esquerdo",
        }
        self.per_photo_settings: Dict[str, Dict[str, object]] = {}
        self.edit_single: bool = False  # False: controles afetam todas; True: somente a foto selecionada
        self.updating_controls: bool = False
        self.load_config()
        self.build_ui()

    # ----------------- Config -----------------
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
        saved_output = data.get("base_output_dir")
        if saved_output:
            self.base_output_dir = Path(saved_output)
            self.output_dir = self.base_output_dir

    def save_config(self) -> None:
        data = self._read_config()
        data.update(
            {
                "default_logo": self.default_logo_path,
                "base_output_dir": str(self.base_output_dir),
            }
        )
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ----------------- UI -----------------
    def build_ui(self) -> None:
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)

        photos_row = QHBoxLayout()
        select_photos_btn = QPushButton("Selecionar fotos")
        select_photos_btn.clicked.connect(self.select_photos)
        self.photos_label = QLabel("0 selecionadas")
        self.photos_label.setMinimumWidth(120)
        photos_row.addWidget(select_photos_btn)
        photos_row.addWidget(self.photos_label)
        photos_row.addStretch()
        main_layout.addLayout(photos_row)

        self.photos_list = QListWidget()
        self.photos_list.setSelectionMode(QListWidget.SingleSelection)
        self.photos_list.itemSelectionChanged.connect(self.on_photo_selection_changed)
        main_layout.addWidget(self.photos_list)

        lock_row = QHBoxLayout()
        self.lock_button = QPushButton("[Lock] Ajustar todas")
        self.lock_button.setCheckable(True)
        self.lock_button.setToolTip("Travar: controles valem para todas. Destravar: apenas para a selecionada.")
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

        self.preview_label = QLabel("Pre-visualizacao")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(360)
        self.preview_label.setStyleSheet("border: 1px solid #444; background-color: #111; color: #ccc;")
        main_layout.addWidget(self.preview_label)

        apply_btn = QPushButton("Aplicar logo em todas as fotos")
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

    def update_logo_label(self) -> None:
        chosen = self.logo_path
        default_txt = f" (padrao: {Path(self.default_logo_path).name})" if self.default_logo_path else ""
        if chosen:
            self.logo_label.setText(Path(chosen).name + default_txt)
        elif self.use_default_checkbox.isChecked() and self.default_logo_path:
            self.logo_label.setText(Path(self.default_logo_path).name + " (usando padrao)")
        else:
            self.logo_label.setText("Nenhuma logo escolhida" + default_txt)

    def current_photo_path(self) -> Optional[str]:
        item = self.photos_list.currentItem()
        if item:
            data = item.data(Qt.UserRole)
            return data if data else item.text()
        return self.photo_paths[0] if self.photo_paths else None

    def current_control_settings(self) -> Dict[str, object]:
        return {
            "size": self.size_slider.value(),
            "margin": self.margin_slider.value(),
            "position": self.position_combo.currentText(),
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
        self.updating_controls = False

    def store_current_controls(self) -> None:
        settings = self.current_control_settings()
        if self.edit_single:
            photo = self.current_photo_path()
            if photo:
                self.per_photo_settings[photo] = settings
        else:
            self.global_settings = settings

    def settings_for_photo(self, photo: str) -> Dict[str, object]:
        if photo in self.per_photo_settings:
            return self.per_photo_settings[photo]
        return self.global_settings

    # ----------------- Slots -----------------
    def select_photos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Escolha as fotos",
            str(Path.home()),
            "Imagens (*.png *.jpg *.jpeg *.bmp *.gif)",
        )
        if not files:
            return
        self.photo_paths = files
        self.photos_list.clear()
        self.per_photo_settings.clear()
        for f in files:
            item = QListWidgetItem(Path(f).name)
            item.setData(Qt.UserRole, f)
            self.photos_list.addItem(item)
        self.photos_label.setText(f"{len(files)} selecionadas")
        self.photos_list.setCurrentRow(0)
        self.on_photo_selection_changed()

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

    def toggle_lock_mode(self) -> None:
        self.edit_single = self.lock_button.isChecked()
        if self.edit_single:
            self.lock_button.setText("[Unlock] Ajustar somente selecionada")
            self.on_photo_selection_changed()
        else:
            self.lock_button.setText("[Lock] Ajustar todas")
            self.set_controls_from_settings(self.global_settings)
            self.update_preview()

    def on_photo_selection_changed(self) -> None:
        if self.edit_single:
            photo = self.current_photo_path()
            if photo:
                settings = self.per_photo_settings.get(photo, self.global_settings)
                self.set_controls_from_settings(settings)
        else:
            self.set_controls_from_settings(self.global_settings)
        self.update_preview()

    # ----------------- Render & Apply -----------------
    def get_active_logo_path(self) -> Optional[str]:
        if self.logo_path:
            return self.logo_path
        if self.use_default_checkbox.isChecked():
            return self.default_logo_path
        return None

    def update_preview(self) -> None:
        photo_path = self.current_photo_path()
        logo_path = self.get_active_logo_path()
        if not photo_path or not logo_path:
            self.preview_label.setText("Adicione fotos e uma logo para visualizar.")
            self.preview_label.setPixmap(QPixmap())
            return
        try:
            base = load_image(Path(photo_path))
            logo = load_image(Path(logo_path))
            settings = self.settings_for_photo(photo_path)
            composed = place_logo(
                base,
                logo,
                int(settings["size"]),
                int(settings["margin"]),
                str(settings["position"]),
            )
            pix = pil_to_qpixmap(composed, self.preview_label.size())
            self.preview_label.setPixmap(pix)
        except Exception as exc:
            self.preview_label.setText(f"Erro na pre-visualizacao: {exc}")

    def apply_watermark_to_all(self) -> None:
        logo_path = self.get_active_logo_path()
        if not self.photo_paths:
            QMessageBox.warning(self, "Faltam fotos", "Selecione pelo menos uma foto.")
            return
        if not logo_path:
            QMessageBox.warning(self, "Falta a logo", "Selecione uma logo ou habilite a logo padrao.")
            return
        today_folder = f"fotos ({date.today().isoformat()})"
        time_folder = datetime.now().strftime("Time %H;%M")
        self.output_dir = self.base_output_dir / today_folder / time_folder
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_label.setText(str(self.output_dir))
        self.save_config()
        succeeded = 0
        failed: List[str] = []
        for photo in self.photo_paths:
            try:
                base = load_image(Path(photo))
                logo = load_image(Path(logo_path))
                settings = self.settings_for_photo(photo)
                result = place_logo(
                    base,
                    logo,
                    int(settings["size"]),
                    int(settings["margin"]),
                    str(settings["position"]),
                )
                dest = self.output_dir / (Path(photo).stem + "_watermarked" + Path(photo).suffix)
                self.save_image_preserving_format(result, dest)
                succeeded += 1
            except Exception:
                failed.append(Path(photo).name)
        msg = f"Logos aplicadas em {succeeded} arquivo(s)."
        if failed:
            msg += f"\nFalha em: {', '.join(failed)}"
        QMessageBox.information(self, "Concluido", msg)

    @staticmethod
    def save_image_preserving_format(img, path: Path) -> None:
        fmt = path.suffix.lower()
        if fmt in [".jpg", ".jpeg"]:
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            background.save(path, quality=95)
        else:
            img.save(path)
