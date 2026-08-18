from __future__ import annotations

import configparser
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTextEdit,
    QWidget,
)


_RUSSIAN = {
    "Bright-band series analyzer": "Анализатор серий ярких полос",
    "Bright-band series analyzer — Raw TXT portfolio MVP": "Анализатор серий ярких полос — исходные TXT",
    "Periodic bright-band series analyzer": "Анализатор серий периодических ярких полос",
    "Raw floating-point matrices and legacy images share one detector through analyze_array().": "Матрицы с плавающей точкой и изображения обрабатываются одним детектором analyze_array().",
    "The physical interpretation and scientific accuracy of the detector must be validated against expert annotation or an independent method.": "Физическую интерпретацию и научную точность детектора необходимо проверить по экспертной разметке или независимым методом.",
    "A. Source series": "A. Исходная серия",
    "Source type": "Тип источника",
    "Raw TXT matrices": "Матрицы TXT",
    "PNG/TIFF images": "Изображения PNG/TIFF",
    "Source folder": "Папка с исходными файлами",
    "Folder containing safe TXT matrices": "Папка с числовыми матрицами TXT",
    "Browse…": "Обзор…",
    "Found files: 0": "Найдено файлов: 0",
    "Valid matrices: 0": "Корректных матриц: 0",
    "Invalid files: 0": "Некорректных файлов: 0",
    "Common shape: —": "Общий размер: —",
    "First: —": "Первый: —",
    "Last: —": "Последний: —",
    "Detected gaps: —": "Пропуски: —",
    "Numbering: —": "Нумерация: —",
    "filename": "имя файла",
    "source_number": "номер источника",
    "layer_index": "индекс слоя",
    "matrix_shape": "размер матрицы",
    "minimum": "минимум",
    "maximum": "максимум",
    "import_status": "статус импорта",
    "B. Series parameters and optional exports": "B. Параметры серии и дополнительные экспорты",
    "Physical frame width": "Физическая ширина кадра",
    "First layer position z₀": "Положение первого слоя z₀",
    "Layer spacing Δz": "Шаг между слоями Δz",
    "Direction": "Направление",
    "Display unit": "Единица отображения",
    "increasing z": "z возрастает",
    "decreasing z": "z убывает",
    "Results base folder": "Папка результатов",
    "Base folder; every run creates a new run_* directory": "Базовая папка; каждый запуск создаёт новый каталог run_*",
    "Export preview PNG files (display only; percentiles 1/99)": "Экспортировать PNG предпросмотра (только отображение; процентили 1/99)",
    "Export float32 TIFF stack (ZYX; no contrast or quantization)": "Экспортировать стек TIFF float32 (ZYX; без контраста и квантования)",
    "Save config JSON…": "Сохранить конфигурацию JSON…",
    "Load config JSON…": "Загрузить конфигурацию JSON…",
    "C. Import and preflight validation": "C. Импорт и предварительная проверка",
    "Choose an input folder to inspect the source series.": "Выберите папку, чтобы проверить исходную серию.",
    "I confirm the displayed order and any numeric gaps": "Подтверждаю показанный порядок и числовые пропуски",
    "D. Run": "D. Запуск",
    "Run analysis": "Запустить анализ",
    "Cancel": "Отмена",
    "Current file: —": "Текущий файл: —",
    "Setup": "Настройка",
    "Source layer": "Исходный слой",
    "← Previous": "← Предыдущий",
    "Next →": "Следующий →",
    "Layer 0 of 0": "Слой 0 из 0",
    "Choose and validate a source folder.": "Выберите и проверьте папку с исходными файлами.",
    "Display preview uses percentile normalization on a copy. The raw float matrix remains unchanged and is the analysis input.": "Предпросмотр нормализует копию по процентилям. Исходная матрица float не изменяется и используется для анализа.",
    "Source preview": "Исходный предпросмотр",
    "Candidate measurements only. CHECK rows are not validated physical results.": "Только предварительные измерения. Строки CHECK не являются проверенными физическими результатами.",
    "Summary": "Сводка",
    "bright bands": "яркие полосы",
    "dark intervals": "тёмные интервалы",
    "candidate wall width, µm": "предварительная ширина стенки, мкм",
    "candidate domain width, µm": "предварительная ширина домена, мкм",
    "period, µm": "период, мкм",
    "rotation, °": "поворот, °",
    "Layer": "Слой",
    "Display preview of source": "Предпросмотр исходных данных",
    "Full QC visualization": "Полная визуализация контроля качества",
    "Open full size": "Открыть в полном размере",
    "QC preview": "Контроль качества",
    "Exploratory plot": "Обзорный график",
    "Run the analysis to generate depth plots.": "Запустите анализ для построения графиков по глубине.",
    "Exploratory depth analysis": "Обзорный анализ по глубине",
    "Errors": "Ошибки",
    "stage": "этап",
    "file": "файл",
    "error type": "тип ошибки",
    "message": "сообщение",
    "Zoom out": "Уменьшить",
    "Zoom in": "Увеличить",
    "Fit to window": "По размеру окна",
    "No image selected": "Изображение не выбрано",
    "Image unavailable": "Изображение недоступно",
    "Raw TXT mode analyzes the original floating-point matrices.": "Режим TXT анализирует исходные матрицы с плавающей точкой.",
    "Legacy image mode analyzes already converted image files.": "Режим изображений анализирует ранее преобразованные файлы.",
    "Folder containing numeric TXT matrices": "Папка с числовыми матрицами TXT",
    "Folder containing PNG/TIFF images": "Папка с изображениями PNG/TIFF",
    "Choose source series": "Выберите исходную серию",
    "Choose results base folder": "Выберите папку результатов",
    "No result available": "Результат отсутствует",
    "No series": "Серия не выбрана",
    "Choose and validate a source series first.": "Сначала выберите и проверьте исходную серию.",
    "Save series configuration": "Сохранение конфигурации серии",
    "Load series configuration": "Загрузка конфигурации серии",
    "Preflight failed": "Предварительная проверка не пройдена",
    "Order confirmation required": "Необходимо подтвердить порядок",
    "No layer table": "Нет таблицы слоёв",
    "The explicit layer table is empty.": "Таблица слоёв пуста.",
    "Cancelled": "Отменено",
    "Completed": "Завершено",
    "Analysis and export complete": "Анализ и экспорт завершены",
    "Run failed": "Ошибка запуска",
    "Analysis failed": "Ошибка анализа",
}

_PREFIXES = {
    "Found files: ": "Найдено файлов: ",
    "Valid matrices: ": "Корректных матриц: ",
    "Valid images: ": "Корректных изображений: ",
    "Invalid files: ": "Некорректных файлов: ",
    "Common shape: ": "Общий размер: ",
    "First: ": "Первый: ",
    "Last: ": "Последний: ",
    "Detected gaps: ": "Пропуски: ",
    "Extracted numbering: ": "Распознано номеров: ",
    "Current file: ": "Текущий файл: ",
    "Layer ": "Слой ",
    "processed ": "обработано ",
}


def load_application_language() -> str:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return "english"
    parser = configparser.ConfigParser()
    parser.read(Path(appdata) / "SHG Series Analyzer" / "settings.ini", encoding="utf-8")
    language = parser.get("application", "language", fallback="english").lower()
    return language if language in {"english", "russian"} else "english"


def _translate(text: str) -> str:
    translated = _RUSSIAN.get(text)
    if translated is not None:
        return translated
    for prefix, replacement in _PREFIXES.items():
        if text.startswith(prefix):
            return replacement + text[len(prefix):].replace(" of ", " из ", 1)
    return text


def _translate_widget(widget: QWidget) -> None:
    title = widget.windowTitle()
    if title:
        translated = _translate(title)
        if translated != title:
            widget.setWindowTitle(translated)
    if isinstance(widget, QGroupBox):
        title = widget.title()
        translated = _translate(title)
        if translated != title:
            widget.setTitle(translated)
    if isinstance(widget, QAbstractButton):
        text = widget.text()
        translated = _translate(text)
        if translated != text:
            widget.setText(translated)
    elif isinstance(widget, QLabel):
        text = widget.text()
        translated = _translate(text)
        if translated != text:
            widget.setText(translated)
    if isinstance(widget, QLineEdit):
        placeholder = widget.placeholderText()
        translated = _translate(placeholder)
        if translated != placeholder:
            widget.setPlaceholderText(translated)
    elif isinstance(widget, QTextEdit):
        placeholder = widget.placeholderText()
        translated = _translate(placeholder)
        if translated != placeholder:
            widget.setPlaceholderText(translated)
    if isinstance(widget, QComboBox):
        for index in range(widget.count()):
            text = widget.itemText(index)
            translated = _translate(text)
            if translated != text:
                widget.setItemText(index, translated)
    if isinstance(widget, QTabWidget):
        for index in range(widget.count()):
            text = widget.tabText(index)
            translated = _translate(text)
            if translated != text:
                widget.setTabText(index, translated)
    if isinstance(widget, QTableWidget):
        for column in range(widget.columnCount()):
            item = widget.horizontalHeaderItem(column)
            if item is not None:
                text = item.text()
                translated = _translate(text)
                if translated != text:
                    item.setText(translated)


class _RussianUiFilter(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QWidget) and event.type() in {
            QEvent.Show,
            QEvent.ChildPolished,
            QEvent.LayoutRequest,
        }:
            _translate_widget(watched)
            for child in watched.findChildren(QWidget):
                _translate_widget(child)
        return False


def install_application_language(app: QApplication, language: str) -> None:
    if language != "russian":
        return
    language_filter = _RussianUiFilter(app)
    app.installEventFilter(language_filter)
    app._shg_language_filter = language_filter
