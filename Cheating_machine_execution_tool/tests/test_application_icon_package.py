"""Exercise the actual archive verifier using complete in-memory archive fixtures."""
from pathlib import Path
import hashlib
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import Mock, patch

from scripts import verify_slim_package as verifier
from src.ui.application_icon import ICON_RELATIVE_PATH
from scripts.create_portable_config import PORTABLE_CONFIG_NAMES


ROOT = Path(__file__).resolve().parents[1]
ICON = ICON_RELATIVE_PATH.as_posix()


class ApplicationIconPackageTests(unittest.TestCase):
    def portable_fixture(self, directory, *, root="DUTPilot_portable/", embedded_exe=None,
                         exe_checksum=None):
        exe = Path(directory) / "DUTPilot.exe"
        exe.write_bytes(b"fixture only; never executable")
        digest = hashlib.sha256(exe.read_bytes()).hexdigest()
        contents = {root + name: b"fixture" for name in (
            "VERSION_INFO.txt", "BUILD_INFO.txt", "PORTABLE_README.txt",
            "THIRD_PARTY_NOTICES.md", "CONFIRMED_CASES.json")}
        contents.update({root + "Auto_power_on_off_tool/config/" + name: b"fixture"
                         for name in PORTABLE_CONFIG_NAMES})
        contents[root + "DUTPilot.exe"] = exe.read_bytes() if embedded_exe is None else embedded_exe
        contents[root + "DUTPilot.exe.sha256.txt"] = (
            f"{exe_checksum or digest} *DUTPilot.exe\n").encode("ascii")
        bundle = Path(directory) / "DUTPilot_portable.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            for name, content in contents.items():
                archive.writestr(name, content)
        Path(str(exe) + ".sha256.txt").write_text(f"{digest} *DUTPilot.exe", encoding="ascii")
        zip_digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        Path(str(bundle) + ".sha256.txt").write_text(
            f"{zip_digest} *DUTPilot_portable.zip", encoding="ascii")
        return exe, bundle

    def test_dutpilot_portable_structure_and_hashes_pass_actual_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            exe, bundle = self.portable_fixture(directory)
            report = verifier.inspect_portable(exe, bundle)
            self.assertEqual(report["zip_crc"], "passed")
            self.assertEqual(report["zip_sha256"], hashlib.sha256(bundle.read_bytes()).hexdigest())

    def test_old_portable_root_cannot_pass_new_build_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            exe, bundle = self.portable_fixture(directory, root="LineCheckAssistant_portable/")
            with self.assertRaisesRegex(ValueError, "Incomplete portable ZIP"):
                verifier.inspect_portable(exe, bundle)

    def test_corrupt_exe_or_checksum_blocks_new_package(self):
        for options in ({"embedded_exe": b"wrong exe"}, {"exe_checksum": "0" * 64}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                exe, bundle = self.portable_fixture(directory, **options)
                with self.assertRaisesRegex(ValueError, "Portable EXE"):
                    verifier.inspect_portable(exe, bundle)

    def test_wrong_standalone_or_zip_hash_blocks_new_package(self):
        for filename in ("DUTPilot.exe", "DUTPilot_portable.zip"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                exe, bundle = self.portable_fixture(directory)
                (Path(directory) / (filename + ".sha256.txt")).write_text(
                    "0" * 64 + " *" + filename, encoding="ascii")
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    verifier.inspect_portable(exe, bundle)

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
