# Copyright (c) Metriq Foundation, Inc.
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
"""Bottom-docked scientific and source panels for Metriq Visualizer."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from PySide6.QtCore import QRectF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOptionSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from metriq_visualizer_bookmarks import Bookmark, bookmark_at
from metriq_visualizer_core import AnalysisResult, GeometryResult

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
except ImportError:  # pragma: no cover
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg  # type: ignore[no-redef]

try:
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:  # pragma: no cover - minimal PySide installations
    QMediaPlayer = Any  # type: ignore[misc,assignment]
    QVideoWidget = None  # type: ignore[assignment]

BACKGROUND = "#070b11"
SURFACE = "#0b121b"
TEXT = "#dce8ed"
MUTED = "#8299a4"
GRID = "#233743"
CURSOR = "#4ce3ad"
TRACE_COLORS = ("#5fa6f7", "#4ce3ad", "#e9bd55", "#c48bf2", "#ef7f7f")
METRIQ_CMAP = LinearSegmentedColormap.from_list(
    "metriq_spectrum",
    ["#070b11", "#0c2633", "#07566b", "#07966a", "#53d39a", "#5fa6f7", "#e6f2ff"],
)


def _normalized(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.size == 0:
        return array
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return np.zeros_like(array)
    low, high = np.percentile(finite, [2.0, 98.0])
    if high <= low + 1e-12:
        return np.zeros_like(array)
    return np.clip((np.nan_to_num(array, nan=low) - low) / (high - low), 0.0, 1.0)


class BookmarkStrip(QWidget):
    """Thin timeline lane above the time slider showing bookmarks.

    Regions draw as translucent bars and points as ticks. A click seeks to the
    bookmark's start (or to the clicked time on empty lane), and a double-click
    asks the owner to edit the bookmark under the cursor.
    """

    seekRequested = Signal(float)
    editRequested = Signal(object)

    HEIGHT = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BookmarkStrip")
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.bookmarks: list[Bookmark] = []
        self.duration = 0.0
        self.current_time = 0.0
        self.selected: Bookmark | None = None
        self._inset = 0.0

    def set_bookmarks(self, bookmarks: list[Bookmark], duration: float) -> None:
        self.bookmarks = list(bookmarks)
        self.duration = max(0.0, float(duration))
        if self.selected is not None and self.selected not in self.bookmarks:
            self.selected = None
        self.update()

    def set_selected(self, bookmark: Bookmark | None) -> None:
        self.selected = bookmark
        self.update()

    def set_time(self, seconds: float) -> None:
        self.current_time = max(0.0, float(seconds))
        self.update()

    def align_to_slider(self, slider: QWidget) -> None:
        """Match the slider's handle travel so positions line up with it."""

        option = QStyleOptionSlider()
        option.initFrom(slider)
        option.orientation = Qt.Orientation.Horizontal
        handle = slider.style().pixelMetric(QStyle.PixelMetric.PM_SliderLength, option, slider)
        self._inset = max(0.0, handle / 2.0)
        self.update()

    def _track(self) -> tuple[float, float]:
        left = self._inset
        return left, max(1.0, self.width() - 2.0 * self._inset)

    def x_for_time(self, seconds: float) -> float:
        left, width = self._track()
        if self.duration <= 0.0:
            return left
        return left + width * min(1.0, max(0.0, seconds / self.duration))

    def time_for_x(self, x: float) -> float:
        left, width = self._track()
        return self.duration * min(1.0, max(0.0, (x - left) / width))

    def bookmark_at_x(self, x: float) -> Bookmark | None:
        if self.duration <= 0.0:
            return None
        _left, width = self._track()
        tolerance = 4.0 / width * self.duration
        return bookmark_at(self.bookmarks, self.time_for_x(x), tolerance=tolerance)

    def paintEvent(self, _event: QPaintEvent) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        height = float(self.height())
        left, width = self._track()
        painter.fillRect(QRectF(left, height / 2.0 - 1.0, width, 2.0), QColor(GRID))
        if self.duration > 0.0:
            for item in self.bookmarks:
                color = QColor(item.color)
                selected = item == self.selected
                if item.end is not None:
                    x0 = self.x_for_time(item.start)
                    x1 = max(x0 + 2.0, self.x_for_time(item.end))
                    fill = QColor(color)
                    fill.setAlpha(150 if selected else 90)
                    painter.fillRect(QRectF(x0, 2.0, x1 - x0, height - 4.0), fill)
                    painter.fillRect(QRectF(x0, 1.0, 2.0, height - 2.0), color)
                else:
                    x = self.x_for_time(item.start)
                    painter.setPen(QPen(color, 3.0 if selected else 2.0))
                    painter.drawLine(int(round(x)), 1, int(round(x)), int(height) - 1)
            cursor_x = self.x_for_time(self.current_time)
            painter.setPen(QPen(QColor(CURSOR), 1.0))
            painter.drawLine(int(round(cursor_x)), 0, int(round(cursor_x)), int(height))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton or self.duration <= 0.0:
            super().mousePressEvent(event)
            return
        x = float(event.position().x())
        item = self.bookmark_at_x(x)
        self.set_selected(item)
        self.seekRequested.emit(item.start if item is not None else self.time_for_x(x))
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        item = self.bookmark_at_x(float(event.position().x()))
        if item is not None:
            self.editRequested.emit(item)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        item = self.bookmark_at_x(float(event.position().x()))
        if item is None:
            self.setToolTip("")
        else:
            span = f"{item.start:.2f}s" if item.end is None else f"{item.start:.2f}s – {item.end:.2f}s"
            note = f"\n{item.note}" if item.note else ""
            self.setToolTip(f"{item.label} · {span}{note}")
        super().mouseMoveEvent(event)


class AnalysisCanvas(FigureCanvasQTAgg):
    """One time-aligned scientific panel.

    A click seeks to that time; a shift-drag proposes a bookmark region.
    """

    seekRequested = Signal(float)
    regionDragged = Signal(float, float)
    """Compact Matplotlib panel with a synchronized time cursor."""

    def __init__(self, mode: str, parent: QWidget | None = None) -> None:
        self.mode = str(mode)
        self.figure = Figure(figsize=(8.0, 2.1), dpi=100)
        self.figure.patch.set_facecolor(BACKGROUND)
        super().__init__(self.figure)
        self.setParent(parent)
        self.setMinimumHeight(150)
        self.analysis: AnalysisResult | None = None
        self.geometry: GeometryResult | None = None
        self.cursor: Any = None
        self.cursors: list[Any] = []
        self.axis: Any = None
        self.axes: list[Any] = []
        self._last_time = -1.0
        self.bookmarks: list[Bookmark] = []
        self._bookmark_artists: list[Any] = []
        self._drag_start: float | None = None
        self._drag_end: float | None = None
        self._drag_artist: Any = None
        self.mpl_connect("button_press_event", self._mouse_pressed)
        self.mpl_connect("motion_notify_event", self._mouse_moved)
        self.mpl_connect("button_release_event", self._mouse_released)
        self._build_empty("NO ANALYSIS")

    def _style_axis(self, axis: Any) -> None:
        axis.set_facecolor(BACKGROUND)
        axis.tick_params(colors=MUTED, labelsize=7, length=2)
        axis.xaxis.label.set_color(MUTED)
        axis.yaxis.label.set_color(MUTED)
        axis.title.set_color(TEXT)
        for spine in axis.spines.values():
            spine.set_color(GRID)
        axis.grid(False)

    def _build_empty(self, message: str) -> None:
        self._bookmark_artists = []
        self._drag_artist = None
        self.figure.clear()
        axis = self.figure.add_subplot(111)
        self._style_axis(axis)
        axis.set_xticks([])
        axis.set_yticks([])
        axis.text(0.5, 0.5, message, transform=axis.transAxes, ha="center", va="center", color=MUTED, family="monospace")
        self.axis = axis
        self.axes = [axis]
        self.cursor = None
        self.cursors = []
        self.figure.subplots_adjust(left=0.025, right=0.995, bottom=0.12, top=0.92)
        self.draw_idle()

    def set_data(
        self,
        analysis: AnalysisResult | None,
        geometry: GeometryResult | None = None,
        *,
        compare: AnalysisResult | None = None,
        compare_geometry: GeometryResult | None = None,
        compare_offset: float = 0.0,
    ) -> None:
        """Draw *analysis*; with *compare*, draw source B in a second row below.

        B is placed on A's timeline shifted by *compare_offset* seconds, so the
        one cursor lines up with what both 3D views show.
        """

        self.analysis = analysis
        self.geometry = geometry
        if analysis is None:
            self._build_empty("NO ANALYSIS")
            return
        self._bookmark_artists = []
        self._drag_artist = None
        self.figure.clear()
        rows = 2 if compare is not None else 1
        axis = self.figure.add_subplot(rows, 1, 1)
        self.axis = axis
        self.axes = [axis]
        self._style_axis(axis)
        duration = max(0.001, float(analysis.duration))
        self._plot(axis, analysis, geometry, 0.0)
        if compare is not None:
            lower = self.figure.add_subplot(rows, 1, 2, sharex=axis)
            self._style_axis(lower)
            self._plot(lower, compare, compare_geometry, float(compare_offset))
            # One legend and one axis label per panel keep the two short rows readable.
            lower.set_ylabel("")
            legend = lower.get_legend()
            if legend is not None:
                legend.remove()
            self.axes.append(lower)
            axis.tick_params(labelbottom=False)
            for row_axis, tag in ((axis, "A"), (lower, "B")):
                row_axis.text(
                    0.004, 0.94, tag, transform=row_axis.transAxes, ha="left", va="top",
                    color=TEXT, fontsize=7, family="monospace", fontweight="bold",
                )
        axis.set_xlim(0.0, duration)
        self.axes[-1].set_xlabel("TIME / SECONDS", fontsize=7)
        self.cursors = [row_axis.axvline(0.0, color=CURSOR, linewidth=1.05, alpha=0.94) for row_axis in self.axes]
        self.cursor = self.cursors[0]
        self.figure.subplots_adjust(left=0.055, right=0.995, bottom=0.23 if rows == 1 else 0.14, top=0.94, hspace=0.08)
        self._last_time = 0.0
        self._draw_bookmarks()
        self.draw_idle()

    def _plot(self, axis: Any, analysis: AnalysisResult, geometry: GeometryResult | None, offset: float) -> None:
        duration = max(0.001, float(analysis.duration))
        mode = self.mode.casefold()
        if mode == "waveform":
            values = np.asarray(analysis.waveform, dtype=np.float64).reshape(-1)
            if values.size:
                maximum = 60_000
                if values.size > maximum:
                    indices = np.linspace(0, values.size - 1, maximum, dtype=np.int64)
                    values = values[indices]
                times = np.linspace(offset, offset + duration, values.size)
                axis.plot(times, values, color=TRACE_COLORS[1], linewidth=0.65, alpha=0.86)
                axis.fill_between(times, 0.0, values, color=TRACE_COLORS[1], alpha=0.08)
            axis.set_ylim(-1.05, 1.05)
            axis.set_ylabel("AMPLITUDE", fontsize=7)
        elif mode == "spectrogram":
            matrix = np.asarray(analysis.spectrogram, dtype=np.float64)
            if matrix.size:
                frequencies = np.asarray(analysis.spectrogram_frequencies, dtype=np.float64).reshape(-1)
                top = float(frequencies[-1]) if frequencies.size else float(matrix.shape[0])
                axis.imshow(matrix, origin="lower", aspect="auto", extent=(offset, offset + duration, 0.0, top), cmap=METRIQ_CMAP, interpolation="bilinear")
                axis.set_ylabel("HZ", fontsize=7)
            else:
                axis.text(0.5, 0.5, "SPECTROGRAM UNAVAILABLE", transform=axis.transAxes, ha="center", va="center", color=MUTED)
        elif mode == "chromagram":
            matrix = np.asarray(analysis.chromagram, dtype=np.float64)
            if matrix.size:
                axis.imshow(matrix, origin="lower", aspect="auto", extent=(offset, offset + duration, 1.0, 12.0), cmap=METRIQ_CMAP, interpolation="nearest")
                axis.set_yticks([1, 4, 7, 10, 12])
                axis.set_ylabel("PITCH CLASS", fontsize=7)
            else:
                axis.text(0.5, 0.5, "CHROMAGRAM UNAVAILABLE", transform=axis.transAxes, ha="center", va="center", color=MUTED)
        elif mode == "mfcc":
            matrix = np.asarray(analysis.mfcc, dtype=np.float64)
            if matrix.size:
                axis.imshow(matrix, origin="lower", aspect="auto", extent=(offset, offset + duration, 1.0, float(matrix.shape[0])), cmap=METRIQ_CMAP, interpolation="nearest")
                axis.set_ylabel("COEFFICIENT", fontsize=7)
            else:
                axis.text(0.5, 0.5, "MFCC UNAVAILABLE", transform=axis.transAxes, ha="center", va="center", color=MUTED)
        elif mode == "traces":
            if geometry is not None and geometry.times_full.size:
                series = (
                    (geometry.x_full, "X"),
                    (geometry.y_full, "Y"),
                    (geometry.z_full, "Z"),
                    (geometry.color_full, "COLOR"),
                )
                for index, (values, label) in enumerate(series):
                    axis.plot(geometry.times_full + offset, _normalized(values), linewidth=0.8, alpha=0.85, label=label, color=TRACE_COLORS[index])
                legend = axis.legend(loc="upper right", frameon=False, ncol=4, fontsize=6.5, handlelength=1.2)
                for text in legend.get_texts():
                    text.set_color(MUTED)
                axis.set_ylim(-0.03, 1.03)
                axis.set_ylabel("NORMALIZED", fontsize=7)
            else:
                axis.text(0.5, 0.5, "MAPPED TRACES APPEAR AFTER GEOMETRY BUILD", transform=axis.transAxes, ha="center", va="center", color=MUTED)

    def set_bookmarks(self, bookmarks: list[Bookmark], *, draw: bool = True) -> None:
        self.bookmarks = list(bookmarks)
        self._draw_bookmarks()
        if draw:
            self.draw_idle()

    def _draw_bookmarks(self) -> None:
        for artist in self._bookmark_artists:
            with suppress(ValueError, AttributeError):
                artist.remove()
        self._bookmark_artists = []
        if self.analysis is None or self.cursor is None or self.axis is None:
            return
        for row_axis in self.axes:
            for item in self.bookmarks:
                if item.end is not None:
                    artist = row_axis.axvspan(item.start, item.end, color=item.color, alpha=0.16, linewidth=0, zorder=0.5)
                else:
                    artist = row_axis.axvline(item.start, color=item.color, linewidth=0.9, linestyle="--", alpha=0.8)
                self._bookmark_artists.append(artist)

    def _event_time(self, event: Any) -> float | None:
        if self.analysis is None or event.inaxes not in self.axes or event.xdata is None:
            return None
        return min(max(0.0, float(event.xdata)), max(0.0, float(self.analysis.duration)))

    @staticmethod
    def _shift_held(event: Any) -> bool:
        modifiers = getattr(event, "modifiers", None) or ()
        return "shift" in modifiers or str(getattr(event, "key", "") or "") == "shift"

    def _mouse_pressed(self, event: Any) -> None:
        seconds = self._event_time(event)
        if seconds is None or getattr(event, "button", None) != 1:
            return
        if self._shift_held(event):
            self._drag_start = seconds
            self._update_drag(seconds)
        else:
            self.seekRequested.emit(seconds)

    def _mouse_moved(self, event: Any) -> None:
        if self._drag_start is None:
            return
        seconds = self._event_time(event)
        if seconds is not None:
            self._update_drag(seconds)

    def _mouse_released(self, event: Any) -> None:
        if self._drag_start is None:
            return
        start = self._drag_start
        seconds = self._event_time(event)
        end = seconds if seconds is not None else self._drag_end
        self._drag_start = None
        if self._drag_artist is not None:
            with suppress(ValueError, AttributeError):
                self._drag_artist.remove()
            self._drag_artist = None
            self.draw_idle()
        if end is not None and abs(end - start) >= 0.01:
            self.regionDragged.emit(min(start, end), max(start, end))

    def _update_drag(self, seconds: float) -> None:
        if self._drag_start is None or self.axis is None:
            return
        self._drag_end = seconds
        if self._drag_artist is not None:
            with suppress(ValueError, AttributeError):
                self._drag_artist.remove()
        low, high = sorted((self._drag_start, seconds))
        self._drag_artist = self.axis.axvspan(low, max(high, low + 1e-6), color=CURSOR, alpha=0.22, linewidth=0)
        self.draw_idle()

    def set_time(self, seconds: float, *, draw: bool = True) -> None:
        if self.cursor is None:
            return
        value = max(0.0, float(seconds))
        if abs(value - self._last_time) < 1e-4:
            return
        self._last_time = value
        for cursor in self.cursors:
            cursor.set_xdata([value, value])
        if draw:
            self.draw_idle()


class SourcePanel(QWidget):
    """Video output when present, waveform otherwise."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stack = QStackedWidget(self)
        self.waveform = AnalysisCanvas("waveform", self)
        self.message = QLabel("SOURCE PREVIEW UNAVAILABLE")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setObjectName("Subtle")
        self.video_widget: Any = None
        if QVideoWidget is not None:
            self.video_widget = QVideoWidget(self)
            self.video_widget.setMinimumHeight(150)
            self.video_widget.setStyleSheet("background:#070b11;")
            self.stack.addWidget(self.video_widget)
        self.stack.addWidget(self.waveform)
        self.stack.addWidget(self.message)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.analysis: AnalysisResult | None = None
        self.media_player: Any = None

    def set_media_player(self, player: Any) -> None:
        self.media_player = player
        if self.video_widget is not None and player is not None:
            with suppress(Exception):
                player.setVideoOutput(self.video_widget)

    def set_data(
        self,
        analysis: AnalysisResult | None,
        geometry: GeometryResult | None = None,
        **compare: Any,
    ) -> None:
        self.analysis = analysis
        self.waveform.set_data(analysis, geometry, **compare)
        if analysis is None:
            self.stack.setCurrentWidget(self.message)
        elif bool(analysis.has_video) and self.video_widget is not None:
            self.stack.setCurrentWidget(self.video_widget)
        else:
            self.stack.setCurrentWidget(self.waveform)

    def set_time(self, seconds: float, *, draw: bool = True) -> None:
        self.waveform.set_time(seconds, draw=draw)

    def set_bookmarks(self, bookmarks: list[Bookmark], *, draw: bool = True) -> None:
        self.waveform.set_bookmarks(bookmarks, draw=draw)


class AnalysisDockWidget(QWidget):
    """A compact, collapsible panel dock placed below the 3D viewport."""

    collapsedChanged = Signal(bool)
    seekRequested = Signal(float)
    regionDragged = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalysisDock")
        self.setMinimumHeight(190)
        self._expanded_height = 245
        self._collapsed = False
        self._current_time = 0.0
        self._analysis: AnalysisResult | None = None
        self._geometry: GeometryResult | None = None
        self._compare: dict[str, Any] = {}

        header = QHBoxLayout()
        header.setContentsMargins(8, 2, 8, 2)
        self.title = QLabel("ANALYSIS DOCK / SOURCE + SCIENTIFIC PANELS")
        self.title.setObjectName("Eyebrow")
        header.addWidget(self.title)
        header.addStretch(1)
        self.collapse_button = QPushButton("Collapse")
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.collapse_button)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.source_panel = SourcePanel(self)
        self.spectrogram = AnalysisCanvas("spectrogram", self)
        self.chromagram = AnalysisCanvas("chromagram", self)
        self.mfcc = AnalysisCanvas("mfcc", self)
        self.traces = AnalysisCanvas("traces", self)
        self.tabs.addTab(self.source_panel, "Source")
        self.tabs.addTab(self.spectrogram, "Spectrogram")
        self.tabs.addTab(self.chromagram, "Chromagram")
        self.tabs.addTab(self.mfcc, "MFCC")
        self.tabs.addTab(self.traces, "Mapped traces")
        self.tabs.currentChanged.connect(self._tab_changed)
        for canvas in self._canvases():
            canvas.seekRequested.connect(self.seekRequested)
            canvas.regionDragged.connect(self.regionDragged)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(header)
        layout.addWidget(self.tabs, 1)

    def set_media_player(self, player: Any) -> None:
        self.source_panel.set_media_player(player)

    def set_data(self, analysis: AnalysisResult | None, geometry: GeometryResult | None = None) -> None:
        self._analysis = analysis
        self._geometry = geometry
        self.source_panel.set_data(analysis, geometry, **self._compare)
        for panel in (self.spectrogram, self.chromagram, self.mfcc, self.traces):
            panel.set_data(analysis, geometry, **self._compare)
        self.set_time(self._current_time, draw=False)

    def set_compare(
        self,
        analysis: AnalysisResult | None,
        geometry: GeometryResult | None = None,
        offset: float = 0.0,
    ) -> None:
        """Show source B under A in every panel, or remove it with ``None``."""

        compare = (
            {"compare": analysis, "compare_geometry": geometry, "compare_offset": float(offset)}
            if analysis is not None
            else {}
        )
        previous = self._compare
        if (
            previous.get("compare") is compare.get("compare")
            and previous.get("compare_geometry") is compare.get("compare_geometry")
            and previous.get("compare_offset") == compare.get("compare_offset")
        ):
            return
        self._compare = compare
        self.set_data(self._analysis, self._geometry)

    def _canvases(self) -> tuple[AnalysisCanvas, ...]:
        return (self.source_panel.waveform, self.spectrogram, self.chromagram, self.mfcc, self.traces)

    def set_bookmarks(self, bookmarks: list[Bookmark]) -> None:
        current = self.tabs.currentWidget()
        for canvas in self._canvases():
            visible = canvas is current or (current is self.source_panel and canvas is self.source_panel.waveform)
            canvas.set_bookmarks(bookmarks, draw=visible)

    def update_geometry(self, analysis: AnalysisResult | None, geometry: GeometryResult | None) -> None:
        self._analysis = analysis
        self._geometry = geometry
        self.traces.set_data(analysis, geometry, **self._compare)
        self.source_panel.waveform.set_data(analysis, geometry, **self._compare)

    def set_time(self, seconds: float, *, draw: bool = True) -> None:
        self._current_time = max(0.0, float(seconds))
        current = self.tabs.currentWidget()
        if current is self.source_panel:
            self.source_panel.set_time(self._current_time, draw=draw)
        elif isinstance(current, AnalysisCanvas):
            current.set_time(self._current_time, draw=draw)
        # Keep every cursor correct when the user changes tabs, without forcing
        # five canvas redraws for every playback frame.
        for panel in (self.spectrogram, self.chromagram, self.mfcc, self.traces):
            if panel is not current:
                panel.set_time(self._current_time, draw=False)

    @Slot(int)
    def _tab_changed(self, _index: int) -> None:
        current = self.tabs.currentWidget()
        if current is self.source_panel:
            self.source_panel.set_time(self._current_time)
            self.source_panel.waveform.draw_idle()
        elif isinstance(current, AnalysisCanvas):
            current.set_time(self._current_time, draw=False)
            current.draw_idle()

    @Slot()
    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.tabs.setVisible(not self._collapsed)
        self.collapse_button.setText("Expand" if self._collapsed else "Collapse")
        if self._collapsed:
            self._expanded_height = max(self._expanded_height, self.height())
            self.setMinimumHeight(34)
            self.setMaximumHeight(42)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setMaximumHeight(16_777_215)
            self.setMinimumHeight(190)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.updateGeometry()
        self.collapsedChanged.emit(self._collapsed)

    @property
    def is_collapsed(self) -> bool:
        return bool(self._collapsed)

    @property
    def preferred_expanded_height(self) -> int:
        return int(max(190, self._expanded_height))


__all__ = ["AnalysisCanvas", "AnalysisDockWidget", "BookmarkStrip", "SourcePanel"]
