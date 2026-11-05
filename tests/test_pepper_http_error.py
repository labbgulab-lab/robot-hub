from pepper_app.speech import _http_error


def test_401_is_plain():
    out = _http_error(401, '{\n "error": {\n "message": "Incorrect API key sk-x"}}')
    assert "\n" not in out and "key rejected" in out


def test_other_error_one_line():
    out = _http_error(500, '{"error": {"message": "boom\n  bad"}}')
    assert out == "OpenAI speech failed (HTTP 500): boom bad"
    assert "\n" not in _http_error(502, "x\ny\n" * 100)
