from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from test_ashare_io import build_ashare_root
from test_index_io import build_index_root


def test_initialize_cache_script_extracts_archives_to_cache(tmp_path: Path) -> None:
    ashare_root = build_ashare_root(tmp_path / "ashare")
    index_root = build_index_root(tmp_path / "index")
    cache_root = tmp_path / "cache"
    script = Path("scripts/initialize_cache.py")

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--ashare-dir",
            str(ashare_root),
            "--index-dir",
            str(index_root),
            "--cache-dir",
            str(cache_root),
            "--validation",
            "sample",
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "A-share daily cache" in result.stdout
    assert "Index bars cache" in result.stdout
    assert "Industry daily cache" in result.stdout
    assert "Index constituents manifest" in result.stdout
    assert (cache_root / "finfact_io" / "ashare_daily").is_dir()
    assert (cache_root / "finfact_io" / "index_data").is_dir()
    assert (cache_root / "finfact_io" / "industry_data").is_dir()
    assert not (ashare_root / "finfact_io").exists()
    assert not (index_root / "finfact_io").exists()


def test_initialize_cache_script_defaults_to_project_cache(tmp_path: Path) -> None:
    ashare_root = build_ashare_root(tmp_path / "ashare-default")
    index_root = build_index_root(tmp_path / "index-default")
    project_root = Path(__file__).resolve().parents[1]
    project_cache = project_root / ".cache"
    script = project_root / "scripts" / "initialize_cache.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--ashare-dir",
            str(ashare_root),
            "--index-dir",
            str(index_root),
            "--validation",
            "sample",
        ],
        check=False,
        cwd=project_root,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"Cache root: {project_cache.resolve()}" in result.stdout
    assert (project_cache / "finfact_io" / "ashare_daily").is_dir()
    assert (project_cache / "finfact_io" / "index_data").is_dir()
    assert (project_cache / "finfact_io" / "industry_data").is_dir()
