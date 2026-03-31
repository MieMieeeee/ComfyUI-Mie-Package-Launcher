"""
Minimal pytest-qt compatibility spike test for PyQt5.
Validates: QApplication singleton, qtbot fixture, signals/slots.
"""
import sys
import pytest
from PyQt5 import QtWidgets, QtCore


class TestQtAppSingleton:
    """Test QApplication singleton handling (one per process)."""

    def test_qapplication_singleton(self, qtbot):
        """QApplication.instance() returns same app within process."""
        app = QtWidgets.QApplication.instance()
        assert app is not None, "QApplication should exist"
        assert app is QtWidgets.QApplication.instance(), "Singleton check failed"

    def test_qtbot_provides_qapplication(self, qtbot):
        """qtbot fixture provides access to QApplication."""
        assert qtbot.app is not None, "qtbot.app should be QApplication"

    def test_multiple_widgets_same_app(self, qtbot):
        """Multiple widgets share same QApplication instance."""
        app1 = QtWidgets.QApplication.instance()
        widget1 = QtWidgets.QPushButton("Button 1")
        widget2 = QtWidgets.QPushButton("Button 2")
        qtbot.addWidget(widget1)
        qtbot.addWidget(widget2)
        app2 = QtWidgets.QApplication.instance()
        assert app1 is app2, "All widgets must share same QApplication"


class TestQtBotButtonInteraction:
    """Test qtbot can click buttons."""

    def test_button_click(self, qtbot):
        """qtbot can click a button and verify state."""
        button = QtWidgets.QPushButton("Click Me")
        qtbot.addWidget(button)

        clicked = []
        button.clicked.connect(lambda: clicked.append(True))

        qtbot.click(button)
        assert len(clicked) == 1, "Button click should emit clicked signal"


class TestPyQtSignals:
    """Test PyQt5 signals work correctly."""

    def test_signal_emit_and_receive(self, qtbot):
        """Signals can be emitted and received."""
        received = []

        class Emitter(QtCore.QObject):
            my_signal = QtCore.pyqtSignal(str)

        emitter = Emitter()
        emitter.my_signal.connect(lambda s: received.append(s))

        emitter.my_signal.emit("test_value")

        assert received == ["test_value"], f"Expected ['test_value'], got {received}"

    def test_signal_with_qtbot_wait(self, qtbot):
        """Test signal with qtbot.waitFor."""
        label = QtWidgets.QLabel("Initial")
        qtbot.addWidget(label)

        def update_label():
            label.setText("Updated")

        # Schedule update
        QtCore.QTimer.singleShot(50, update_label)
        qtbot.wait(200)

        assert label.text() == "Updated", f"Label should be 'Updated', got '{label.text()}'"
