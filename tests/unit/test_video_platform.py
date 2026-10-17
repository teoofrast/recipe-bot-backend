import pytest

from receipt.domain.video import Platform, UnsupportedUrlError, detect_platform


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw", Platform.YOUTUBE),
        ("https://youtu.be/jNQXAC9IVRw", Platform.YOUTUBE),
        ("https://m.youtube.com/shorts/abc123", Platform.YOUTUBE),
        ("  https://youtube.com/shorts/abc123  ", Platform.YOUTUBE),
        ("https://www.tiktok.com/@chef/video/7300000000000000000", Platform.TIKTOK),
        ("https://vm.tiktok.com/ZMabc123/", Platform.TIKTOK),
        ("https://www.instagram.com/reel/Cabc123/", Platform.INSTAGRAM),
        ("https://instagram.com/p/Cabc123/", Platform.INSTAGRAM),
        ("HTTPS://WWW.YOUTUBE.COM/watch?v=x", Platform.YOUTUBE),
    ],
)
def test_detects_supported_platforms(url: str, platform: Platform) -> None:
    assert detect_platform(url) is platform


@pytest.mark.parametrize(
    "url",
    [
        "not a link",
        "",
        "youtube.com/watch?v=x",
        "ftp://youtube.com/watch?v=x",
        "https://vimeo.com/123",
        "https://notyoutube.com/watch?v=x",
        "https://youtube.com.evil.example/watch?v=x",
    ],
)
def test_rejects_unsupported_links(url: str) -> None:
    with pytest.raises(UnsupportedUrlError):
        detect_platform(url)
