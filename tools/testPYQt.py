"""PyQt compatibility test for a PowerFactory ComPython or standalone Python.

Copy the complete file into a ComPython and run it. PyQt6 or PyQt5 must be
installed in the Python environment configured in PowerFactory. QT_BINDING
can select a version explicitly; auto reuses a loaded PyQt binding, otherwise
tries PyQt6 and then PyQt5. A broken installation is reported without loading
a second Qt version into the process.

The dialog tests navigation, widgets, signals and timer events. Only the
active project and study-case names are read; no calculation or write to the
PowerFactory model is performed. Closing the dialog returns to the script.
An existing QApplication is reused and is never quit or restyled.

Qt lifecycle reference: https://doc.qt.io/qt-6/qapplication.html
Dialog event loop: https://doc.qt.io/qt-6/qdialog.html#exec
"""

from __future__ import annotations

import importlib
import platform
import sys
import threading


QT_BINDING = 'auto'  # 'auto', 'PyQt6' or 'PyQt5'
_qt_app = None


def load_qt():
    """Load one binding only; avoid mixing PyQt/PySide or different Qt majors."""
    if QT_BINDING not in ('auto', 'PyQt6', 'PyQt5'):
        raise RuntimeError('QT_BINDING muss auto, PyQt6 oder PyQt5 sein.')
    loaded = {name for name in ('PyQt6', 'PyQt5', 'PySide6', 'PySide2')
              if any(key == name or key.startswith(name + '.') for key in sys.modules)}
    if loaded & {'PySide6', 'PySide2'} or len(loaded) > 1:
        raise RuntimeError('Bereits geladene Qt-Bindings: {}. PyQt bitte in einer frischen '
                           'PowerFactory-Sitzung testen.'.format(', '.join(sorted(loaded))))
    if loaded and QT_BINDING != 'auto' and QT_BINDING not in loaded:
        raise RuntimeError('{} ist bereits geladen; QT_BINDING={} würde Qt-Versionen mischen.'
                           .format(next(iter(loaded)), QT_BINDING))
    candidates = sorted(loaded) if loaded else (['PyQt6', 'PyQt5'] if QT_BINDING == 'auto' else [QT_BINDING])
    for name in candidates:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise RuntimeError('{} ist installiert, aber eine Abhängigkeit fehlt: {}'
                                   .format(name, exc)) from exc
            continue
        try:
            core = importlib.import_module(name + '.QtCore')
            widgets = importlib.import_module(name + '.QtWidgets')
        except (ImportError, OSError) as exc:
            raise RuntimeError('{} konnte nicht geladen werden: {}. Python-Version, '
                               'Architektur und Qt-/DLL-Installation prüfen.'.format(name, exc)) from exc
        return name, core, widgets
    raise RuntimeError('PyQt6/PyQt5 wurde nicht gefunden (Auswahl: {}). PyQt in der von PowerFactory '
                       'verwendeten Python-Umgebung installieren. Python: {}; Umgebung: {}'
                       .format(QT_BINDING, platform.python_version(), sys.prefix))


def powerfactory_context():
    """The current PowerFactory application and a read-only context description."""
    try:
        powerfactory = importlib.import_module('powerfactory')
    except ModuleNotFoundError as exc:
        if exc.name == 'powerfactory':
            return None, 'Standalone · PowerFactory-Modul nicht verfügbar'
        raise
    get_application = getattr(powerfactory, 'GetApplication', None)
    if not callable(get_application):
        # A checkout may contain a directory named powerfactory, which Python
        # can import as a namespace package even without the PowerFactory API.
        return None, 'Standalone · Paket powerfactory enthält keine PowerFactory-API'
    app = get_application()
    if app is None:
        return None, 'Keine aktive PowerFactory-Verbindung'
    project, study = app.GetActiveProject(), app.GetActiveStudyCase()
    return app, 'PowerFactory verbunden\nProjekt: {}\nStudienfall: {}'.format(
        project.loc_name if project is not None else 'keines',
        study.loc_name if study is not None else 'keiner')


def log(app, text, error=False):
    message = '[PYQT-TEST] ' + text
    if app is not None:
        printer = getattr(app, 'PrintError' if error else 'PrintPlain', None)
        if callable(printer):
            printer(message)
            return
    print(message, file=sys.stderr if error else sys.stdout)


def application(core, widgets):
    """Keep the QApplication alive, and create widgets only on its GUI thread."""
    global _qt_app
    app = widgets.QApplication.instance()
    if app is None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('PyQt benötigt den GUI-Hauptthread. Den ComPython direkt '
                               'aus der PowerFactory-Oberfläche starten.')
        app = widgets.QApplication(['GridLens-PyQt-Test'])
    if not isinstance(app, widgets.QApplication):
        raise RuntimeError('Die vorhandene Qt-Anwendung unterstützt keine Widgets.')
    if core.QThread.currentThread() != app.thread():
        raise RuntimeError('Der ComPython läuft außerhalb des Qt-GUI-Threads. '
                           'Den Test direkt aus der PowerFactory-Oberfläche starten.')
    _qt_app = app
    return app


def build_dialog(core, widgets, version, context, app=None):
    dialog = widgets.QDialog()
    dialog.setObjectName('GridLensPyQtTest')
    dialog.setWindowTitle('GridLens · PyQt-Test für PowerFactory')
    dialog.resize(1080, 720)
    dialog.setMinimumSize(840, 560)
    attribute = getattr(core.Qt, 'WidgetAttribute', core.Qt).WA_QuitOnClose
    dialog.setAttribute(attribute, False)
    dialog.setStyleSheet('''
        QDialog#GridLensPyQtTest { background: #101827; }
        QWidget { color: #e7edf7; font-family: "Segoe UI"; font-size: 13px; }
        QFrame#sidebar { background: #172236; border-radius: 12px; }
        QFrame#card { background: #1e2d45; border-radius: 12px; }
        QLabel#title { font-size: 25px; font-weight: bold; }
        QLabel#muted { color: #a4b3c9; }
        QLabel#success { color: #72d8a5; }
        QPushButton { background: #253650; border: 0; border-radius: 6px; padding: 12px 16px; }
        QPushButton:hover { background: #324967; }
        QPushButton:focus { border: 1px solid #91baff; }
        QPushButton#primary, QPushButton:checked { background: #3478ed; }
        QLineEdit, QComboBox { background: #172236; border: 1px solid #435676; padding: 8px; }
        QComboBox QAbstractItemView { background: #172236; selection-background-color: #3478ed; }
        QCheckBox { spacing: 8px; }
        QTableWidget { background: #172236; alternate-background-color: #1e2d45; gridline-color: #435676; }
        QHeaderView::section { background: #253650; color: #e7edf7; padding: 8px; border: 0; }
    ''')
    layout = widgets.QHBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(24)
    sidebar = widgets.QFrame()
    sidebar.setObjectName('sidebar')
    sidebar.setFixedWidth(205)
    navigation = widgets.QVBoxLayout(sidebar)
    brand = widgets.QLabel('GRIDLENS\nPyQt-Kompatibilität')
    navigation.addWidget(brand)
    navigation.addSpacing(24)
    layout.addWidget(sidebar)
    content = widgets.QVBoxLayout()
    content.setSpacing(16)
    layout.addLayout(content, 1)
    title = widgets.QLabel()
    title.setObjectName('title')
    content.addWidget(title)
    subtitle = widgets.QLabel(version)
    subtitle.setWordWrap(True)
    subtitle.setObjectName('muted')
    content.addWidget(subtitle)
    stack = widgets.QStackedWidget()
    stack.setObjectName('pages')
    content.addWidget(stack, 1)
    buttons = []
    group = widgets.QButtonGroup(dialog)
    group.setExclusive(True)

    def page(name):
        frame = widgets.QWidget()
        body = widgets.QVBoxLayout(frame)
        body.setSpacing(16)
        index = stack.addWidget(frame)
        button = widgets.QPushButton(name)
        button.setCheckable(True)
        button.setAutoDefault(False)
        group.addButton(button)
        navigation.addWidget(button)
        buttons.append(button)

        def show_page(_checked=False):
            stack.setCurrentIndex(index)
            title.setText(name)
        button.clicked.connect(show_page)
        return body

    home = page('Übersicht')
    card = widgets.QFrame()
    card.setObjectName('card')
    card_layout = widgets.QVBoxLayout(card)
    card_layout.setContentsMargins(20, 20, 20, 20)
    card_layout.addWidget(widgets.QLabel('GUI-Kompatibilität · Qt Widgets'))
    timer_label = widgets.QLabel('Ereignisschleife: wartet auf Timer …')
    timer_label.setObjectName('heartbeat')
    card_layout.addWidget(timer_label)
    home.addWidget(card)
    home.addWidget(widgets.QLabel('Name des Testfalls'))
    name = widgets.QLineEdit('Testfall 2030')
    name.setObjectName('caseName')
    home.addWidget(name)
    checks = widgets.QHBoxLayout()
    n0, n1 = widgets.QCheckBox('n-0'), widgets.QCheckBox('n-1')
    n0.setObjectName('n0')
    n1.setObjectName('n1')
    for check in (n0, n1):
        check.setChecked(True)
        checks.addWidget(check)
    checks.addStretch()
    home.addLayout(checks)
    test = widgets.QPushButton('Oberfläche testen')
    test.setObjectName('primary')
    test.setAutoDefault(False)

    def test_button(_checked=False):
        text = 'Testfall: {}\nn-0: {}\nn-1: {}\n\nPyQt-Signal empfangen. Keine Berechnung ausgeführt.'.format(
            name.text(), n0.isChecked(), n1.isChecked())
        log(app, text)
        widgets.QMessageBox.information(dialog, 'GridLens PyQt-Test erfolgreich', text)
    test.clicked.connect(test_button)
    home.addWidget(test)
    home.addStretch()

    cases = page('Planungsfälle')
    cases.addWidget(widgets.QLabel('Beispiel-Tabelle · keine echten Netzdaten'))
    table = widgets.QTableWidget(3, 3)
    table.setObjectName('caseTable')
    table.setHorizontalHeaderLabels(['Planungsfall', 'Status', 'Bewertung'])
    table.verticalHeader().hide()
    table.setAlternatingRowColors(True)
    view = widgets.QAbstractItemView
    table.setEditTriggers(getattr(view, 'EditTrigger', view).NoEditTriggers)
    for row, values in enumerate([('Referenz', 'Bereit', 'n-0'),
                                  ('Kabeltausch Nord', 'Entwurf', 'n-1'),
                                  ('Wartung Trafo 2', 'Entwurf', "(n-1)'")]):
        for column, value in enumerate(values):
            table.setItem(row, column, widgets.QTableWidgetItem(value))
    table.horizontalHeader().setStretchLastSection(True)
    table.resizeColumnsToContents()
    cases.addWidget(table)

    network = page('Netzauswahl')
    network.addWidget(widgets.QLabel('Beispiel-Netzauswahl'))
    grids = widgets.QComboBox()
    grids.setObjectName('gridChoice')
    grids.addItems(['Gesamtes Netz', 'Netz Nord', 'Netz Süd'])
    network.addWidget(grids)
    note = widgets.QLabel('Nur Demo-Werte. Es werden keine PowerFactory-Netze gelesen.')
    note.setWordWrap(True)
    network.addWidget(note)
    network.addStretch()

    settings = page('Einstellungen')
    details = widgets.QLabel('{}\n\n{}\n\nPython {} · {}\nInterpreter: {}\nUmgebung: {}'.format(
        version, context, platform.python_version(), platform.machine(), sys.executable, sys.prefix))
    details.setWordWrap(True)
    settings.addWidget(details)
    settings.addStretch()
    navigation.addStretch()
    safe = widgets.QLabel('NUR TEST\nKEINE BERECHNUNG')
    safe.setObjectName('success')
    navigation.addWidget(safe)
    close = widgets.QPushButton('Fenster schließen')
    close.setAutoDefault(False)
    close.clicked.connect(dialog.reject)
    content.addWidget(close)
    buttons[0].click()
    timer = core.QTimer(dialog)
    timer.setInterval(1000)
    ticks = [0]

    def tick():
        ticks[0] += 1
        timer_label.setText('Ereignisschleife aktiv · {} s'.format(ticks[0]))
    timer.timeout.connect(tick)
    timer.start()
    dialog.finished.connect(timer.stop)
    return dialog


def main():
    pf_app = None
    try:
        pf_app, context = powerfactory_context()
        log(pf_app, 'Python {} · {} · {}'.format(platform.python_version(), platform.machine(), sys.prefix))
        binding, core, widgets = load_qt()
        version = '{} {} · Qt {}'.format(binding, core.PYQT_VERSION_STR, core.QT_VERSION_STR)
        log(pf_app, version + '\n' + context)
        application(core, widgets)
        dialog = build_dialog(core, widgets, version, context, pf_app)
        log(pf_app, 'Testfenster wird geöffnet. Zum Fortsetzen das Fenster schließen.')
        # ComPython waits here until the dialog closes. Do not start or quit
        # the host QApplication's global event loop.
        execute = getattr(dialog, 'exec', None) or dialog.exec_
        execute()
        dialog.deleteLater()
        log(pf_app, 'Testfenster geschlossen; Kontrolle an PowerFactory zurückgegeben.')
    except Exception as exc:
        log(pf_app, str(exc), error=True)
        raise


if __name__ == '__main__':
    main()
