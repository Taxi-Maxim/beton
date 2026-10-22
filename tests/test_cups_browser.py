import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from flask import send_file
from werkzeug.serving import make_server
from backend.app import create_app


@unittest.skipUnless(os.environ.get("BETON_CHROME") and os.environ.get("BETON_NODE"), "Set BETON_CHROME and BETON_NODE for browser checks")
class CupsBrowserTests(unittest.TestCase):
    def test_preview_tracking_results_resize_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({"TESTING": True, "DATABASE": str(Path(directory) / "test.sqlite3"),
                              "COOKIE_SECURE": False, "PUBLIC_ORIGIN": ""})
            app.add_url_rule("/__cups_check", view_func=lambda: send_file(Path(__file__).with_name("cups_browser.html")))
            # The test harness embeds the real page; production keeps X-Frame-Options: DENY.
            def allow_test_frame(response):
                response.headers.pop("X-Frame-Options", None)
                return response
            app.after_request_funcs[None].insert(0, allow_test_frame)
            server = make_server("127.0.0.1", 0, app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run([os.environ["BETON_NODE"], str(Path(__file__).with_name("run_cups_browser.cjs")),
                    os.environ["BETON_CHROME"], str(Path(directory) / "chrome"),
                    f"http://127.0.0.1:{server.server_port}/__cups_check"], capture_output=True, timeout=60,
                    encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                self.assertNotEqual(result.stdout.strip(), "RUNNING", "Browser check did not complete")
                report = json.loads(result.stdout.strip())
                self.assertTrue(report.get("ok"), report)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
