"""Small building blocks: state marks (shape + word), panels, facts, the verdict bar.

A state is never colour alone. Each tone has its own shape:

    good  filled circle with a tick        warn  filled triangle with "!"
    bad   filled square with a cross       busy  ring with a dot in the middle
    idle  empty ring (nothing to say, or nothing known)

and every mark that stands alone has a word beside it ("Running", "Stopped").
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import theme

def draw_mark(p: QPainter, rect: QRectF, tone: str) -> None:
    """Paint the shape for ``tone`` inside ``rect`` (square works best)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    col = theme.qc({"good": "good", "warn": "warn", "bad": "bad", "busy": "primary"}
                   .get(tone, "text_muted"))
    ink = theme.qc("card")
    s = min(rect.width(), rect.height())
    r = QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s)
    lw = max(1.5, s / 9)
    if tone == "good":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(r)
        pen = QPen(ink, lw * 1.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(QPointF(r.left() + s * 0.28, r.top() + s * 0.52))
        path.lineTo(QPointF(r.left() + s * 0.44, r.top() + s * 0.68))
        path.lineTo(QPointF(r.left() + s * 0.73, r.top() + s * 0.34))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    elif tone == "warn":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPolygon(QPolygonF([QPointF(r.center().x(), r.top() + s * 0.04),
                                 QPointF(r.right(), r.bottom() - s * 0.06),
                                 QPointF(r.left(), r.bottom() - s * 0.06)]))
        p.setPen(QPen(ink, lw, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(r.center().x(), r.top() + s * 0.36),
                   QPointF(r.center().x(), r.top() + s * 0.62))
        p.drawPoint(QPointF(r.center().x(), r.top() + s * 0.78))
    elif tone == "bad":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r.adjusted(s * 0.04, s * 0.04, -s * 0.04, -s * 0.04), s * 0.14, s * 0.14)
        p.setPen(QPen(ink, lw, Qt.SolidLine, Qt.RoundCap))
        m = s * 0.32
        p.drawLine(QPointF(r.left() + m, r.top() + m), QPointF(r.right() - m, r.bottom() - m))
        p.drawLine(QPointF(r.right() - m, r.top() + m), QPointF(r.left() + m, r.bottom() - m))
    elif tone == "busy":
        p.setPen(QPen(col, lw))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r.adjusted(lw / 2, lw / 2, -lw / 2, -lw / 2))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        d = s * 0.36
        p.drawEllipse(QRectF(r.center().x() - d / 2, r.center().y() - d / 2, d, d))
    else:
        p.setPen(QPen(col, lw))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r.adjusted(lw / 2, lw / 2, -lw / 2, -lw / 2))
    p.restore()


def mark_icon(tone: str, size: int = 14) -> QIcon:
    ratio = 2.0
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    draw_mark(p, QRectF(0, 0, size, size), tone)
    p.end()
    return QIcon(pm)


class Mark(QWidget):
    """Just the shape, for rows whose sentence already says the state."""

    def __init__(self, size: int = 14, parent=None):
        super().__init__(parent)
        self._tone = "idle"
        self._size = size
        self.setFixedSize(size, size)

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        draw_mark(p, QRectF(0, 0, self._size, self._size), self._tone)
        p.end()


class StateMark(QWidget):
    """Shape + word, e.g. a green tick circle and "Running"."""

    def __init__(self, size: int = 16, text_px: int = 15, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.mark = Mark(size)
        self.word = QLabel()
        self.word.setFont(theme.font(text_px, 600))
        lay.addWidget(self.mark)
        lay.addWidget(self.word)
        lay.addStretch(1)

    def set_state(self, tone: str, word: str) -> None:
        self.mark.set_tone(tone)
        self.word.setText(word)
        self.word.setStyleSheet(f"color: {theme.tone_color(tone) if tone != 'idle' else theme.c('text')};")
        self.setAccessibleName(word)


class Panel(QFrame):
    """A Harbor panel ("deck"): card tone on the harbor background, radius 10, padding 16."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 16)
        self.body.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("panelTitle")
            self.body.addWidget(label)


def muted(text: str = "", px: int = 12) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setFont(theme.font(px))
    return label


class Facts(QWidget):
    """Label above value, laid out in a grid. Values are set by key."""

    def __init__(self, items: list[tuple[str, str]], columns: int = 4, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(12)
        self.values: dict[str, QLabel] = {}
        for i, (key, caption) in enumerate(items):
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(muted(caption))
            value = QLabel("–")
            value.setFont(theme.font(15, 600))
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.addWidget(value)
            grid.addLayout(box, i // columns, i % columns)
            self.values[key] = value
        for col in range(columns):
            grid.setColumnStretch(col, 1)

    def set(self, key: str, text: str) -> None:
        self.values[key].setText(text or "–")


class CheckRow(QWidget):
    """One line of "This PC": a mark, then a sentence."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)
        self.mark = Mark(14)
        self.text = QLabel()
        self.text.setWordWrap(True)
        lay.addWidget(self.mark, 0, Qt.AlignTop)
        lay.addWidget(self.text, 1)

    def set(self, tone: str, sentence: str) -> None:
        self.mark.set_tone(tone)
        self.text.setText(sentence)
        self.setAccessibleName(sentence)


class VerdictBar(QFrame):
    """The one-line answer at the top of the window, with its mark and side facts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)
        self.mark = Mark(22)
        self.sentence = QLabel()
        self.sentence.setFont(theme.font(16, 600))
        self.sentence.setWordWrap(True)
        self.sentence.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.facts = muted("", 12)
        self.facts.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.mark)
        lay.addWidget(self.sentence, 1)
        lay.addWidget(self.facts)
        self._tone = "idle"

    def set(self, tone: str, sentence: str, facts: str = "") -> None:
        self._tone = tone
        self.mark.set_tone(tone)
        self.sentence.setText(sentence)
        self.facts.setText(facts)
        tint = {"bad": "bad_tint", "warn": "warn_tint"}.get(tone)
        bg = theme.c(tint) if tint else theme.c("card")
        edge = theme.tone_color(tone) if tint else theme.c("card")
        self.setStyleSheet(f"QFrame#panel {{ background: {bg}; border-left: 4px solid {edge}; }}")
        self.setAccessibleName(sentence)

    def sizeHint(self):  # noqa: N802
        return QSize(600, 56)
