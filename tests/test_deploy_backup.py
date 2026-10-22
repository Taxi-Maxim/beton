import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class DeploymentBackupTests(unittest.TestCase):
    def backup_program(self):
        script = (Path(__file__).resolve().parent.parent / "update.sh").read_text(encoding="utf-8")
        return script.split("<<'PYBACKUP'\n", 1)[1].split("\nPYBACKUP", 1)[0]

    def test_streamed_backup_contains_committed_wal_data(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "source.sqlite3"
            source = sqlite3.connect(database)
            try:
                source.execute("PRAGMA journal_mode=WAL")
                source.execute("CREATE TABLE players (balance TEXT)")
                source.execute("INSERT INTO players VALUES (?)", (str(10**100),))
                source.commit()
                result = subprocess.run([sys.executable, "-c", self.backup_program()],
                    env={**os.environ, "BETON_DATABASE": str(database)}, capture_output=True, check=True)
                snapshot = Path(directory) / "restored.sqlite3"
                snapshot.write_bytes(result.stdout)
                restored = sqlite3.connect(snapshot)
                try:
                    self.assertEqual(restored.execute("PRAGMA quick_check").fetchone(), ("ok",))
                    self.assertEqual(restored.execute("SELECT balance FROM players").fetchone(), (str(10**100),))
                finally:
                    restored.close()
            finally:
                source.close()

    def test_missing_database_fails_without_creating_empty_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.sqlite3"
            result = subprocess.run([sys.executable, "-c", self.backup_program()],
                env={**os.environ, "BETON_DATABASE": str(database)}, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertFalse(database.exists())
