import pytest

from apps.core.sanitize import sanitize_html


def test_plain_formatting_survives():
    html = "<p>Soft <strong>cotton</strong> and <em>linen</em></p><ul><li>one</li></ul>"
    assert sanitize_html(html) == html


def test_scripts_and_event_handlers_are_removed():
    dirty = '<p onclick="steal()">Hi</p><script>alert(1)</script><img src="x.png" onerror="steal()">'
    clean = sanitize_html(dirty)
    assert "script" not in clean
    assert "onclick" not in clean
    assert "onerror" not in clean
    assert "Hi" in clean
    assert '<img src="x.png">' in clean


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html;base64,AAAA", "vbscript:x"])
def test_dangerous_url_schemes_are_removed(url):
    assert url not in sanitize_html(f'<a href="{url}">x</a><img src="{url}">')


def test_links_get_a_safe_rel_and_keep_https_urls():
    clean = sanitize_html('<a href="https://example.com/a">x</a>')
    assert 'href="https://example.com/a"' in clean
    assert 'rel="noopener noreferrer nofollow"' in clean


def test_styles_iframes_and_forms_are_removed():
    clean = sanitize_html('<p style="x">a</p><iframe src="https://e.com"></iframe><form><input></form>')
    assert clean == "<p>a</p>"


@pytest.mark.parametrize("empty", ["", None])
def test_empty_input_gives_an_empty_string(empty):
    assert sanitize_html(empty) == ""
