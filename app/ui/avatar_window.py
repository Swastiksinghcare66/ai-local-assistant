from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


# ============================================================
# AVATAR IMAGE
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ASSET_PATH = PROJECT_ROOT / "anime.png"


class CornerAvatar(QWidget):

    WINDOW_WIDTH = 330
    WINDOW_HEIGHT = 500

    RIGHT_MARGIN = 15
    BOTTOM_MARGIN = 5

    def __init__(self):
        super().__init__()

        if not ASSET_PATH.exists():
            raise FileNotFoundError(
                f"Avatar image not found: {ASSET_PATH}"
            )

        # ----------------------------------------------------
        # Window
        # ----------------------------------------------------

        self.setWindowTitle("Sara")

        self.setFixedSize(
            self.WINDOW_WIDTH,
            self.WINDOW_HEIGHT,
        )

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            True,
        )

        # ----------------------------------------------------
        # Load avatar
        # ----------------------------------------------------

        self.original_pixmap = QPixmap(
            str(ASSET_PATH)
        )

        if self.original_pixmap.isNull():
            raise RuntimeError(
                f"Failed to load avatar image: {ASSET_PATH}"
            )

        self.avatar_pixmap = (
            self.original_pixmap.scaled(
                self.WINDOW_WIDTH,
                self.WINDOW_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        # ----------------------------------------------------
        # Idle animation
        # ----------------------------------------------------

        self.breath_phase = 0.0
        self.breath_offset = 0

        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(
            self._animate
        )
        self.animation_timer.start(33)

        # ----------------------------------------------------
        # Dragging
        # ----------------------------------------------------

        self.dragging = False
        self.drag_position = QPoint()

        self._place_bottom_right()


    # ========================================================
    # POSITION
    # ========================================================

    def _place_bottom_right(self):

        screen = QApplication.primaryScreen()

        if screen is None:
            return

        area = screen.availableGeometry()

        x = (
            area.right()
            - self.width()
            - self.RIGHT_MARGIN
            + 1
        )

        y = (
            area.bottom()
            - self.height()
            - self.BOTTOM_MARGIN
            + 1
        )

        self.move(x, y)


    # ========================================================
    # IDLE ANIMATION
    # ========================================================

    def _animate(self):

        self.breath_phase += 0.045

        self.breath_offset = int(
            math.sin(
                self.breath_phase
            ) * 2
        )

        self.update()


    # ========================================================
    # DRAW
    # ========================================================

    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            True,
        )

        x = (
            self.width()
            - self.avatar_pixmap.width()
        ) // 2

        y = (
            self.height()
            - self.avatar_pixmap.height()
            + self.breath_offset
        )

        painter.drawPixmap(
            x,
            y,
            self.avatar_pixmap,
        )


    # ========================================================
    # DRAGGING
    # ========================================================

    def mousePressEvent(self, event):

        if (
            event.button()
            == Qt.MouseButton.LeftButton
        ):
            self.dragging = True

            self.drag_position = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )

            event.accept()


    def mouseMoveEvent(self, event):

        if (
            self.dragging
            and
            event.buttons()
            & Qt.MouseButton.LeftButton
        ):
            self.move(
                event.globalPosition().toPoint()
                - self.drag_position
            )

            event.accept()


    def mouseReleaseEvent(self, event):

        if (
            event.button()
            == Qt.MouseButton.LeftButton
        ):
            self.dragging = False
            event.accept()


    # ========================================================
    # CLOSE
    # ========================================================

    def mouseDoubleClickEvent(self, event):

        if (
            event.button()
            == Qt.MouseButton.RightButton
        ):
            QApplication.quit()


def main():

    app = QApplication(sys.argv)

    avatar = CornerAvatar()

    avatar.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
