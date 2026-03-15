from PyQt5.QtWidgets import QMainWindow, QTabWidget

from watermark_tool import WatermarkTool
from video_tool import VideoWatermarkTool


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Automatizador - Ferramentas Flash")
        tabs = QTabWidget()
        tabs.addTab(WatermarkTool(), "Logo em fotos")
        tabs.addTab(VideoWatermarkTool(), "Logo em vídeos")
        self.setCentralWidget(tabs)
        self.resize(980, 780)
