import tomllib
from pathlib import Path


def project_version() -> str:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    return pyproject["project"]["version"]


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


def test_release_please_workflow_exists_and_targets_main() -> None:
    workflow = Path(".github/workflows/release-please.yml").read_text()
    config = Path("release-please-config.json").read_text()
    manifest = Path(".release-please-manifest.json").read_text()

    assert "name: Release Please" in workflow
    assert "googleapis/release-please-action" in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert "config-file: release-please-config.json" in workflow
    assert "manifest-file: .release-please-manifest.json" in workflow
    assert "command:" not in workflow
    assert '"release-type": "python"' in config
    assert '"packages"' in config
    assert '"."' in manifest
    assert f'"{project_version()}"' in manifest


def test_cd_workflow_publishes_versioned_images_from_release() -> None:
    workflow = Path(".github/workflows/cd.yml").read_text()

    assert "on:" in workflow
    assert "release:" in workflow
    assert "types:" in workflow
    assert "- published" in workflow
    assert "docker/metadata-action" in workflow
    assert "type=semver,pattern={{version}}" in workflow
    assert "workflow_run:" not in workflow
    assert "github.event.workflow_run.head_sha" not in workflow
