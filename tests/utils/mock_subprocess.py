from unittest.mock import MagicMock


class MockPopen:
    def __init__(
        self,
        args=None,
        returncode=0,
        stdout_lines=None,
        stderr_lines=None,
    ):
        self.args = args or []
        self.returncode = returncode
        self.pid = 12345
        self._stdout_lines = stdout_lines or []
        self._stderr_lines = stderr_lines or []
        self._stdout_buffer = '\n'.join(self._stdout_lines)
        self._stderr_buffer = '\n'.join(self._stderr_lines)
    
    @property
    def stdout(self):
        mock = MagicMock()
        mock.read.return_value = self._stdout_buffer
        mock.readline.side_effect = self._make_readline()
        return mock
    
    @property
    def stderr(self):
        mock = MagicMock()
        mock.read.return_value = self._stderr_buffer
        return mock
    
    def _make_readline(self):
        lines = list(self._stdout_lines)
        idx = [0]
        def readline():
            if idx[0] < len(lines):
                result = lines[idx[0]]
                idx[0] += 1
                return result
            return ''
        return readline
    
    def poll(self):
        return self.returncode
    
    def wait(self, timeout=None):
        return self.returncode
    
    def communicate(self):
        return (self._stdout_buffer, self._stderr_buffer)
