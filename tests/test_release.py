import argparse
import os
from pathlib import Path
import posixpath
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mark_4/engine"))
import runtime
runner = runtime.load_shared("excel_runner")


class ReleaseTests(unittest.TestCase):
    def args(self, output):
        return argparse.Namespace(workbook=str(ROOT / "Backtest_Model_Runner.xlsm"),
            project_root=str(ROOT), output_root=str(output), output_workbook=None,
            mode="write", activate=True, official_oos=False,
            disable_news_filter=False, disable_news_forced_close=False)

    def test_default_root_is_this_copy(self):
        self.assertEqual(runner.DEFAULT_PROJECT_ROOT, ROOT)
        self.assertEqual(runtime.REPOSITORY, ROOT)

    def test_external_data_does_not_change_strategy_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder)
            args.price_data_root = folder
            args.news_data_root = folder
            out = runner.build_engine_args(args)
            self.assertEqual(out.price_data_root, str(Path(folder).resolve()))
            self.assertTrue(out.run_strategy and out.validate_price_data and out.scan_price_data)
            self.assertFalse(out.disable_news_filter or out.disable_news_forced_close)
            self.assertIsNone(out.max_scan_rows)

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.xlsm"
            path.touch()
            args = self.args(folder)
            args.output_workbook = str(path)
            with self.assertRaisesRegex(runner.backtest_engine.EngineError, "overwrite"):
                runner.build_engine_args(args)

    def test_archive_is_isolated_and_collision_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(folder)
            args.output_workbook = str(Path(folder) / "result.xlsm")
            out = runner.build_engine_args(args)
            self.assertEqual(Path(out.archive_root), Path(folder).resolve() / "archive/result")
            Path(out.archive_root).mkdir(parents=True)
            with self.assertRaisesRegex(runner.backtest_engine.EngineError, "archive"):
                runner.build_engine_args(args)

    def test_legacy_imports_resolve_locally(self):
        code = "import base_setup_engine, base_setup_engine.setup_logic, base_setup_engine.obstacle_logic; from pathlib import Path; assert Path(base_setup_engine.__file__).resolve().is_relative_to(Path.cwd())"
        subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                       env=dict(os.environ, PYTHONPATH=str(ROOT)), check=True)

    def test_template_has_mark4_and_no_previous_run_paths(self):
        book = load_workbook(ROOT / "Backtest_Model_Runner.xlsm", read_only=True, data_only=True)
        try:
            config = {row[0]: row[1] for row in book["Config"].values if row[0]}
            self.assertEqual(config["Engine_Profile"], "MARK_4_CURRENT_ENGINE")
            self.assertEqual(config["Rule_Version"], "Mark4-0.1.0")
            self.assertIsNone(book["Runner"]["B6"].value)
            self.assertIsNone(book["Runner"]["B7"].value)
        finally:
            book.close()

    def test_workbook_relationships_and_buttons(self):
        with ZipFile(ROOT / "Backtest_Model_Runner.xlsm") as archive:
            names = set(archive.namelist())
            self.assertIn("xl/vbaProject.bin", names)
            controls = b"".join(archive.read(n) for n in names if "vmlDrawing" in n)
            self.assertIn(b"Run_Backtest_Write", controls)
            self.assertIn(b"Dry_Run_Backtest", controls)
            for name in names:
                if not name.endswith(".rels"):
                    continue
                for relation in ET.fromstring(archive.read(name)):
                    if relation.get("TargetMode") == "External":
                        continue
                    target = relation.get("Target", "")
                    resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                        posixpath.join(posixpath.dirname(posixpath.dirname(name)), target))
                    self.assertIn(resolved, names, (name, resolved))


if __name__ == "__main__":
    unittest.main()
