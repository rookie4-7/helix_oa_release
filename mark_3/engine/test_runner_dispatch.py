import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock


class Dispatched(Exception):
    pass


class RunnerDispatch(unittest.TestCase):
    def load(self):
        path = Path(__file__).resolve().parents[2] / 'runner_update_20261010/excel_runner.py'
        if not path.exists():
            import runtime
            path = runtime.SHARED / 'excel_runner.py'
        spec = importlib.util.spec_from_file_location('mark3_dispatch_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def workbook(self, profile, version='Mark3-0.1.0'):
        book = Mock()
        book.__getitem__ = Mock(return_value=Mock())
        book['Config'].iter_rows.return_value = [('Engine_Profile',profile), ('Rule_Version',version)]
        return book

    def test_mark3_routes_to_own_entrypoint(self):
        module = self.load()
        with patch.object(sys, 'argv', ['runner','--workbook','input.xlsm']), \
             patch('openpyxl.load_workbook', return_value=self.workbook('MARK_3_CURRENT_ENGINE')), \
             patch.object(Path, 'is_file', return_value=True), \
             patch('os.execv', side_effect=Dispatched) as call:
            with self.assertRaises(Dispatched):
                module.dispatch_versioned_engine()
            self.assertTrue(call.call_args.args[1][2].endswith('/mark_3/engine/excel_runner.py'))

    def test_mark2_still_routes_to_frozen_entrypoint(self):
        module = self.load()
        with patch.object(sys, 'argv', ['runner','--workbook','input.xlsm']), \
             patch('openpyxl.load_workbook', return_value=self.workbook('MARK_2_CURRENT_ENGINE','Mark2-0.2.0')), \
             patch.object(Path, 'is_file', return_value=True), \
             patch('os.execv', side_effect=Dispatched) as call:
            with self.assertRaises(Dispatched):
                module.dispatch_versioned_engine()
            self.assertTrue(call.call_args.args[1][2].endswith('/mark_2/engine/excel_runner.py'))

    def test_missing_profile_cannot_silently_run_legacy_engine(self):
        module = self.load()
        with patch.object(sys, 'argv', ['runner','--workbook','input.xlsm']), \
             patch('openpyxl.load_workbook', return_value=self.workbook(None)):
            with self.assertRaisesRegex(SystemExit, 'wrong engine'):
                module.dispatch_versioned_engine()

    def test_missing_engine_fails_clearly(self):
        module = self.load()
        with patch.object(sys, 'argv', ['runner','--workbook','input.xlsm']), \
             patch('openpyxl.load_workbook', return_value=self.workbook('MARK_3_CURRENT_ENGINE')), \
             patch.object(Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(SystemExit, 'engine is missing'):
                module.dispatch_versioned_engine()


if __name__ == '__main__':
    unittest.main()
