import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[3]
SCRATCH = ROOT / "workstreams/po03/control/units/a4/test-scratch"


def extract_clean_head(destination: Path):
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream.getmembers():
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not (member.isfile() or member.isdir())
            ):
                raise AssertionError(f"unsafe clean archive member: {member.name}")
            output = destination.joinpath(*relative.parts)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                source = stream.extractfile(member)
                if source is None:
                    raise AssertionError(f"cannot extract {member.name}")
                output.write_bytes(source.read())


class CleanDispositionReproductionTests(unittest.TestCase):
    def test_clean_archive_emits_byte_identical_disposition(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            checkout = Path(temporary) / "checkout"
            checkout.mkdir()
            extract_clean_head(checkout)
            generated = Path(temporary) / "repository-disposition.json"
            process = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(
                        checkout
                        / "workstreams/po03/packverify/disposition.py"
                    ),
                    "--root",
                    str(checkout),
                    "--output",
                    str(generated),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            expected = (
                checkout
                / "workstreams/po03/evidence/repository-disposition.json"
            )
            self.assertEqual(generated.read_bytes(), expected.read_bytes())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(SCRATCH, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
