"""Exercise the actual archive verifier using complete in-memory archive fixtures."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import verify_slim_package as verifier
from src.ui.application_icon import ICON_RELATIVE_PATH


ROOT = Path(__file__).resolve().parents[1]
ICON = ICON_RELATIVE_PATH.as_posix()


class ApplicationIconPackageTests(unittest.TestCase):
    def archive(self, separator="/"):
        entries = {name.replace("/", separator): (0, 1) for name in verifier.REQUIRED_FILES}
        entries.update({name: (0, 1) for name in (
            "pyi_rth__tkinter", "cryptography/hazmat/bindings/_rust.pyd",
            "bcrypt/_bcrypt.pyd", "nacl/_sodium.pyd", "psutil/_psutil_windows.pyd")})
        archive = Mock()
        archive.toc = entries
        archive.open_embedded_archive.return_value = SimpleNamespace(
            toc=dict.fromkeys(verifier.REQUIRED_MODULES))
        contents = {
            "VERSION_INFO.txt": (ROOT / "line_check_assistant/packaging_assets/VERSION_INFO.txt").read_bytes(),
            ICON.replace("/", separator): (ROOT / ICON_RELATIVE_PATH).read_bytes(),
        }
        archive.extract.side_effect = contents.__getitem__
        return archive

    def inspect(self, archive):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / "fixture.exe"
            exe.write_bytes(b"archive fixture; not executable")
            with patch.object(verifier, "CArchiveReader", return_value=archive):
                return verifier.inspect_archive(exe, [])

    def test_matching_runtime_icon_passes_with_either_archive_separator(self):
        for separator in ("/", "\\"):
            with self.subTest(separator=separator):
                report = self.inspect(self.archive(separator))
                self.assertIn(ICON, report["required_files"])
                self.assertIn("src.ui.application_icon", report["required_modules"])

    def test_missing_runtime_icon_blocks_package_verification(self):
        archive = self.archive()
        del archive.toc[ICON]
        with self.assertRaisesRegex(ValueError, "Missing required archive entries:.*ico"):
            self.inspect(archive)

    def test_different_embedded_icon_blocks_package_verification(self):
        archive = self.archive()
        original = archive.extract.side_effect
        archive.extract.side_effect = lambda name: b"old or corrupt icon" if name == ICON else original(name)
        with self.assertRaisesRegex(ValueError, "application icon differs"):
            self.inspect(archive)


if __name__ == "__main__":
    unittest.main()
