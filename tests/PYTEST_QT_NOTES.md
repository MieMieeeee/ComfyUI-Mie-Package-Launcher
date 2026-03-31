# PyQt5 + pytest-qt Compatibility Notes

## Findings

### QApplication Singleton Pattern
- PyQt5 requires exactly ONE `QApplication` instance per process
- Pattern used in project: `QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)`
- pytest-qt manages QApplication lifecycle automatically via `qtbot` fixture
- Multiple tests can run in same process - QApplication is reused

### pytest-qt Integration
- `pytest-qt` plugin handles QApplication creation before tests
- `qtbot` fixture provides:
  - `qtbot.app` - access to QApplication instance
  - `qtbot.addWidget(widget)` - registers widget for cleanup
  - `qtbot.click(button)` - simulate button click
  - `qtbot.wait(ms)` - wait for event processing
- No manual QApplication management needed in tests

### Signal/Slot Compatibility
- `pyqtSignal` works correctly with pytest-qt event loop
- Signals can be emitted and received synchronously in tests
- `QtCore.QTimer.singleShot` works for deferred operations

### Key Test Patterns

```python
def test_example(qtbot):
    button = QtWidgets.QPushButton("Test")
    qtbot.addWidget(button)
    qtbot.click(button)
```

```python
def test_signal(qtbot):
    emitter = Emitter()
    received = []
    emitter.my_signal.connect(lambda s: received.append(s))
    emitter.my_signal.emit("value")
    assert received == ["value"]
```

## Requirements

```
pytest>=7.0.0
pytest-qt>=4.0.0
PyQt5>=5.15.0
```

## Running Tests

```bash
pytest tests/spike_pytest_qt.py -v
```

## Status

✅ COMPATIBLE - PyQt5 works with pytest-qt
