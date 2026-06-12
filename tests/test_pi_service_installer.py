from pathlib import Path
from subprocess import run


def test_pi_service_installer_dry_run_outputs_both_units() -> None:
    script = Path("scripts/install_pi_scanner_services.sh")

    result = run(
        [
            "bash",
            str(script),
            "--dry-run",
            "--install-dir",
            "/opt/grocy-ultimate-lookup",
            "--server",
            "http://lookup.local:9290",
            "--device-id",
            "kitchen-pi",
            "--token",
            "secret-token",
            "--scanner-tty",
            "/dev/tty1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "grocy-device-scanner.service" in result.stdout
    assert "grocy-gpio-state-controller.service" in result.stdout
    assert "--device-id kitchen-pi" in result.stdout
    assert "--token secret-token" in result.stdout
    assert "--server http://lookup.local:9290" in result.stdout
    assert "TTYPath=/dev/tty1" in result.stdout
