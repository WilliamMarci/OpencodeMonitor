"""Persistent settings + the settings dialog."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSpinBox, QVBoxLayout,
)

from . import APP_NAME, ORG_NAME
from .autostart import is_enabled as autostart_enabled
from .autostart import set_enabled as set_autostart
from .autostart import is_supported as autostart_supported
from .i18n import Translator
from .sources import SourceConfig, build_source


@dataclass
class AppSettings:
    source: str = "auto"
    api_base: str = "https://opencode.ai/zen/go/v1"
    api_key: str = ""
    mode: str = "used"                 # used | remaining
    monthly_budget: float = 60.0
    refresh_sec: int = 60
    opacity: int = 95
    always_on_top: bool = True
    autostart: bool = False
    language: str = "auto"
    pos_x: int | None = None
    pos_y: int | None = None

    _qsettings: QSettings = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls) -> "AppSettings":
        store = QSettings(ORG_NAME, APP_NAME)
        settings = cls(_qsettings=store)
        settings.source = str(store.value("source", settings.source))
        settings.api_base = str(store.value("api_base", settings.api_base))
        settings.api_key = str(store.value("api_key", settings.api_key))
        settings.mode = str(store.value("mode", settings.mode))
        settings.monthly_budget = float(store.value("monthly_budget",
                                                    settings.monthly_budget))
        settings.refresh_sec = int(store.value("refresh_sec",
                                               settings.refresh_sec))
        settings.opacity = int(store.value("opacity", settings.opacity))
        settings.always_on_top = str(store.value(
            "always_on_top", settings.always_on_top)).lower() in ("1", "true")
        settings.autostart = str(store.value(
            "autostart", settings.autostart)).lower() in ("1", "true")
        settings.language = str(store.value("language", settings.language))
        x = store.value("pos_x")
        y = store.value("pos_y")
        settings.pos_x = int(x) if x is not None else None
        settings.pos_y = int(y) if y is not None else None
        return settings

    def save(self) -> None:
        store = self._qsettings or QSettings(ORG_NAME, APP_NAME)
        self._qsettings = store
        store.setValue("source", self.source)
        store.setValue("api_base", self.api_base)
        store.setValue("api_key", self.api_key)
        store.setValue("mode", self.mode)
        store.setValue("monthly_budget", self.monthly_budget)
        store.setValue("refresh_sec", self.refresh_sec)
        store.setValue("opacity", self.opacity)
        store.setValue("always_on_top", self.always_on_top)
        store.setValue("autostart", self.autostart)
        store.setValue("language", self.language)
        if self.pos_x is not None and self.pos_y is not None:
            store.setValue("pos_x", self.pos_x)
            store.setValue("pos_y", self.pos_y)
        store.sync()

    def source_config(self) -> SourceConfig:
        return SourceConfig(
            kind=self.source,
            api_base=self.api_base,
            api_key=self.api_key,
            monthly_budget=self.monthly_budget,
        )


class _TestWorker(QThread):
    finished_with = Signal(object)

    def __init__(self, config: SourceConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config

    def run(self) -> None:  # noqa: D102
        try:
            snapshot = build_source(self._config).fetch()
        except Exception as exc:  # noqa: BLE001
            self.finished_with.emit(exc)
            return
        self.finished_with.emit(snapshot)


class RawResponseDialog(QDialog):
    def __init__(self, payload, translator: Translator, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(translator("raw_title"))
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        view = QPlainTextEdit(self)
        view.setReadOnly(True)
        try:
            text = json.dumps(payload, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(payload)
        view.setPlainText(text)
        layout.addWidget(view)


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, translator: Translator,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(translator("settings"))
        self._settings = settings
        self._t = translator
        self._test_snapshot = None
        self._worker = None
        self.setMinimumWidth(420)

        form = QFormLayout()

        self.source_box = QComboBox(self)
        self.source_box.addItem(translator("source_auto"), "auto")
        self.source_box.addItem(translator("source_api"), "api")
        self.source_box.addItem(translator("source_local"), "local")
        self.source_box.addItem(translator("source_demo"), "demo")
        index = self.source_box.findData(settings.source)
        self.source_box.setCurrentIndex(max(0, index))
        form.addRow(translator("source"), self.source_box)

        self.api_base_edit = QLineEdit(settings.api_base, self)
        form.addRow(translator("api_base"), self.api_base_edit)

        self.api_key_edit = QLineEdit(settings.api_key, self)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText(translator("api_key_hint"))
        form.addRow(translator("api_key"), self.api_key_edit)

        self.mode_box = QComboBox(self)
        self.mode_box.addItem(translator("show_used"), "used")
        self.mode_box.addItem(translator("show_remaining"), "remaining")
        self.mode_box.setCurrentIndex(1 if settings.mode == "remaining" else 0)
        form.addRow(translator("display"), self.mode_box)

        self.budget_spin = QDoubleSpinBox(self)
        self.budget_spin.setRange(1.0, 100000.0)
        self.budget_spin.setDecimals(2)
        self.budget_spin.setPrefix("$ ")
        self.budget_spin.setValue(settings.monthly_budget)
        form.addRow(translator("monthly_budget"), self.budget_spin)

        self.refresh_spin = QSpinBox(self)
        self.refresh_spin.setRange(15, 3600)
        self.refresh_spin.setSuffix(" s")
        self.refresh_spin.setValue(settings.refresh_sec)
        form.addRow(translator("refresh_interval"), self.refresh_spin)

        self.opacity_spin = QSpinBox(self)
        self.opacity_spin.setRange(30, 100)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.setValue(settings.opacity)
        form.addRow(translator("opacity"), self.opacity_spin)

        self.language_box = QComboBox(self)
        self.language_box.addItem("Auto / 自动", "auto")
        self.language_box.addItem("English", "en")
        self.language_box.addItem("简体中文", "zh")
        index = self.language_box.findData(settings.language)
        self.language_box.setCurrentIndex(max(0, index))
        form.addRow(translator("language"), self.language_box)

        self.topmost_check = QCheckBox(translator("always_on_top"), self)
        self.topmost_check.setChecked(settings.always_on_top)
        form.addRow("", self.topmost_check)

        self.autostart_check = QCheckBox(translator("autostart"), self)
        if autostart_supported():
            self.autostart_check.setChecked(autostart_enabled())
            self.autostart_check.stateChanged.connect(
                lambda _state: self._sync_autostart())
        else:
            self.autostart_check.setEnabled(False)
        form.addRow("", self.autostart_check)

        layout = QVBoxLayout(self)
        layout.addLayout(form)

        note = QLabel(translator("budget_share"), self)
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        layout.addWidget(note)

        buttons_row = QHBoxLayout()
        self.test_button = QPushButton(translator("test"), self)
        self.test_button.clicked.connect(self._on_test)
        buttons_row.addWidget(self.test_button)
        self.raw_button = QPushButton(translator("raw_response"), self)
        self.raw_button.clicked.connect(self._on_raw)
        self.raw_button.setEnabled(False)
        buttons_row.addWidget(self.raw_button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)

        box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        box.button(QDialogButtonBox.Save).setText(translator("save"))
        box.button(QDialogButtonBox.Cancel).setText(translator("cancel"))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    # -- actions ---------------------------------------------------------
    def _sync_autostart(self) -> None:
        self._settings.autostart = self.autostart_check.isChecked()
        try:
            set_autostart(self._settings.autostart)
        except OSError:
            pass

    def _current_config(self) -> SourceConfig:
        return SourceConfig(
            kind=self.source_box.currentData(),
            api_base=self.api_base_edit.text().strip(),
            api_key=self.api_key_edit.text().strip(),
            monthly_budget=self.budget_spin.value(),
        )

    def _on_test(self) -> None:
        self.test_button.setEnabled(False)
        self.status_label.setText("…")
        self._worker = _TestWorker(self._current_config(), self)
        self._worker.finished_with.connect(self._on_test_done)
        self._worker.start()

    def _on_test_done(self, result) -> None:
        self.test_button.setEnabled(True)
        if isinstance(result, Exception):
            self.status_label.setText(
                self._t("test_fail", error=str(result)))
            return
        if result.error and not result.ok:
            self.status_label.setText(
                self._t("test_fail", error=result.error))
            return
        self._test_snapshot = result
        self.raw_button.setEnabled(result.raw is not None)
        detail = ", ".join(
            f"{w.label}: {w.used:.2f}/{w.limit:.2f} ({w.used_percent}%)"
            for w in result.windows
        )
        note = "" if not result.error else f" ({result.error})"
        self.status_label.setText(
            self._t("test_ok", source=result.source,
                    count=len(result.windows)) + note
            + "\n" + self._t("test_parsed", detail=detail))

    def _on_raw(self) -> None:
        if self._test_snapshot is None:
            return
        RawResponseDialog(self._test_snapshot.raw, self._t, self).exec()

    def apply_to_settings(self) -> AppSettings:
        settings = self._settings
        settings.source = self.source_box.currentData()
        settings.api_base = self.api_base_edit.text().strip()
        settings.api_key = self.api_key_edit.text().strip()
        settings.mode = self.mode_box.currentData()
        settings.monthly_budget = self.budget_spin.value()
        settings.refresh_sec = self.refresh_spin.value()
        settings.opacity = self.opacity_spin.value()
        settings.always_on_top = self.topmost_check.isChecked()
        settings.autostart = self.autostart_check.isChecked()
        settings.language = self.language_box.currentData()
        return settings
