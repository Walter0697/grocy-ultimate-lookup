import tomllib
from pathlib import Path


def test_pyproject_packages_only_app_package() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]

    assert package_find["include"] == ["app*"]
    assert "data*" in package_find["exclude"]
    assert "plugin*" in package_find["exclude"]


def test_dockerfile_copies_app_before_installing_project() -> None:
    lines = Path("Dockerfile").read_text().splitlines()

    copy_app_index = next(index for index, line in enumerate(lines) if line == "COPY app ./app")
    install_index = next(index for index, line in enumerate(lines) if line == "RUN pip install --no-cache-dir .")

    assert copy_app_index < install_index


def test_dockerignore_excludes_local_runtime_artifacts() -> None:
    patterns = set(Path(".dockerignore").read_text().splitlines())

    assert ".git" in patterns
    assert ".venv" in patterns
    assert "data" in patterns
    assert "__pycache__" in patterns
