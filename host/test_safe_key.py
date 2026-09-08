import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from safe_key import make_vault, relock_vault, safe_extract, unlock_vault, verify_vault


class SafeKeyTests(unittest.TestCase):
    def test_round_trip_nested_unicode_files(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            source = root / "源资料"
            (source / "子目录").mkdir(parents=True)
            (source / "子目录" / "说明.txt").write_text("SafeKey 测试", encoding="utf-8")
            vault = root / "demo.safevault"
            make_vault(source, vault)
            restored = unlock_vault(vault)
            try:
                self.assertEqual(
                    (restored / "子目录" / "说明.txt").read_text(encoding="utf-8"),
                    "SafeKey 测试",
                )
            finally:
                shutil.rmtree(restored, ignore_errors=True)

    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            archive = root / "evil.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../outside.txt", "blocked")
            with zipfile.ZipFile(archive) as zf:
                with self.assertRaises(ValueError):
                    safe_extract(zf, root / "out")

    def test_modify_and_relock(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            source = root / "source"
            source.mkdir()
            (source / "note.txt").write_text("before", encoding="utf-8")
            vault = root / "demo.safevault"
            make_vault(source, vault)
            restored = unlock_vault(vault)
            try:
                (restored / "note.txt").write_text("after", encoding="utf-8")
                relock_vault(restored, vault)
            finally:
                shutil.rmtree(restored, ignore_errors=True)
            restored_again = unlock_vault(vault)
            try:
                self.assertEqual((restored_again / "note.txt").read_text(encoding="utf-8"), "after")
            finally:
                shutil.rmtree(restored_again, ignore_errors=True)

    def test_integrity_check_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            source = root / "source"
            source.mkdir()
            (source / "note.txt").write_text("protected", encoding="utf-8")
            vault = root / "demo.safevault"
            make_vault(source, vault)
            raw = bytearray(vault.read_bytes())
            raw[-1] ^= 0x01
            vault.write_bytes(raw)
            with self.assertRaises(Exception):
                verify_vault(vault)


if __name__ == "__main__":
    unittest.main()
