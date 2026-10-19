import logging

from app.log_filter import HideSecretsFilter


def _access_line(path: str) -> str:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "POST", path, "1.1", 204),
        None,
    )
    HideSecretsFilter().filter(record)
    return record.getMessage()


def test_upload_token_is_masked():
    line = _access_line("/api/uploads/s3cr3t-token/complete")
    assert "s3cr3t-token" not in line
    assert "/api/uploads/***/complete" in line


def test_token_only_path_is_masked():
    assert "/api/uploads/***" in _access_line("/api/uploads/s3cr3t-token")


def test_query_string_is_dropped():
    line = _access_line("/_local/masked/videos/17/clips/1.mp4?exp=1760331600&sig=abc123")
    assert "sig" not in line and "exp" not in line
    assert "/_local/masked/videos/17/clips/1.mp4" in line


def test_other_paths_are_unchanged():
    assert "/api/health" in _access_line("/api/health")


def test_filter_is_installed_on_uvicorn_access_logger():
    import app.main  # noqa: F401 - import하면 create_app()이 필터를 붙인다

    access = logging.getLogger("uvicorn.access")
    assert any(isinstance(f, HideSecretsFilter) for f in access.filters)
