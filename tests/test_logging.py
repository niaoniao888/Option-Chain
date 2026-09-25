from __future__ import annotations

import json
import logging
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from options_panel.logging import JsonFormatter, LOGGER, configure_logging, log_event


class LoggingTests(unittest.TestCase):
    def test_json_log_contains_fields_without_traceback_or_paths(self):
        try:
            raise OSError("private response marker")
        except OSError:
            record = logging.LogRecord("options_panel", logging.ERROR, __file__, 10, "failed", (), exc_info=__import__("sys").exc_info())
        record.event_name = "upstream_request"
        record.event_fields = {"result": "failed", "exception_type": "OSError"}
        text = JsonFormatter().format(record)
        value = json.loads(text)
        self.assertEqual(value["event"], "upstream_request")
        self.assertEqual(value["exception_type"], "OSError")
        self.assertTrue(value["time"].endswith("Z"))
        self.assertNotIn("private response marker", text)
        self.assertNotIn(str(__file__), text)

    def isolated_logger(self):
        previous = LOGGER.handlers[:]
        LOGGER.handlers.clear()
        def restore():
            for handler in LOGGER.handlers:
                handler.close()
            LOGGER.handlers[:] = previous
        self.addCleanup(restore)

    def test_unwritable_directory_uses_console(self):
        self.isolated_logger()
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as console:
            blocker = Path(directory) / 'file-not-directory'
            blocker.write_text('blocked', encoding='utf-8')
            configure_logging(blocker)
            log_event(logging.INFO, 'still_running')
            values = [json.loads(line) for line in console.getvalue().splitlines()]
            self.assertEqual(values[0]['event'], 'logging_console_fallback')
            self.assertEqual(values[-1]['event'], 'still_running')

    def test_rotation_preserves_bounded_json_lines(self):
        self.isolated_logger()
        with tempfile.TemporaryDirectory() as directory:
            configure_logging(Path(directory), max_bytes=250, backup_count=2)
            for index in range(20):
                log_event(logging.INFO, 'rotation', index=index)
            for handler in list(LOGGER.handlers):
                handler.close()
            LOGGER.handlers.clear()
            files = list(Path(directory).glob('options-panel.log*'))
            self.assertEqual(len(files), 3)
            for file in files:
                for line in file.read_text(encoding='utf-8').splitlines():
                    self.assertIn('time', json.loads(line))


if __name__ == "__main__":
    unittest.main()
