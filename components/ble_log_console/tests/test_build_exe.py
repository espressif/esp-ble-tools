from build_exe import PROJECT_VERSION_RE, _replace_document_versions


def test_replace_document_versions() -> None:
    text = """Version: v9.8.7
ble_log_console_windows_v9.8.7.exe
ble_log_console_ubuntu_v9.8.7
"""

    assert _replace_document_versions(text, "1.0.5") == """Version: v1.0.5
ble_log_console_windows_v1.0.5.exe
ble_log_console_ubuntu_v1.0.5
"""
    assert PROJECT_VERSION_RE.sub('version = "1.0.5"', 'version = "9.8.7"') == 'version = "1.0.5"'
