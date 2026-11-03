"""版本号解析与排序的单元测试（纯函数，不碰网络与磁盘）。"""

from __future__ import annotations

from inferry.version import CURRENT, VERSION_TAG, Version, compare, is_newer, parse, parse_tag


def test_current_is_canonical() -> None:
    assert CURRENT.pep440 == CURRENT.tag[1:]
    assert f"v{CURRENT.pep440}" == VERSION_TAG
    assert parse(CURRENT.pep440) == CURRENT
    assert parse(VERSION_TAG) == CURRENT


def test_parse_forms() -> None:
    cases = {
        "2.1.0": (2, 1, 0, "", 0, None, None),
        "v2.1": (2, 1, 0, "", 0, None, None),
        "2.1.0rc1": (2, 1, 0, "rc", 1, None, None),
        "2.1.0-rc.2": (2, 1, 0, "rc", 2, None, None),
        "2.1.0-beta.3": (2, 1, 0, "b", 3, None, None),
        "2.1.0alpha2": (2, 1, 0, "a", 2, None, None),
        "2.1.0-preview1": (2, 1, 0, "rc", 1, None, None),
        "2.1.0.dev4": (2, 1, 0, "", 0, 4, None),
        "2.1.0.post2": (2, 1, 0, "", 0, None, 2),
    }
    for text, want in cases.items():
        got = parse(text)
        assert got is not None, text
        assert (got.major, got.minor, got.patch, got.label, got.number,
                got.dev, got.post) == want, text


def test_parse_local_and_whitespace() -> None:
    got = parse("  v2.1.0+build.7  ")
    assert got is not None
    assert got.local == "build.7"
    assert got.pep440 == "2.1.0+build.7"
    mixed = parse("2.1.0rc1+sha.abc123")
    assert mixed is not None
    assert mixed.pep440 == "2.1.0rc1+sha.abc123"


def test_parse_rejects_garbage() -> None:
    for text in ("", "   ", "abc", "latest", "2.1.0.1", "2.1.0-", "2.1.0-xyz",
                 "2.1.0+", "release-2.1.0", "2.1.0rc1rc2"):
        assert parse(text) is None, text


def test_semver_spellings_normalized() -> None:
    assert parse("2.1.0-rc.1").pep440 == "2.1.0rc1"  # type: ignore[union-attr]
    assert parse("2.1.0-beta.2").pep440 == "2.1.0b2"  # type: ignore[union-attr]
    assert parse("2.1.0-alpha.3").pep440 == "2.1.0a3"  # type: ignore[union-attr]
    assert parse("2.1.0-preview.4").pep440 == "2.1.0rc4"  # type: ignore[union-attr]


def test_channel_and_prerelease() -> None:
    assert parse("2.1.0").channel == "stable"  # type: ignore[union-attr]
    assert parse("2.1.0rc1").channel == "rc"  # type: ignore[union-attr]
    assert parse("2.1.0b1").channel == "beta"  # type: ignore[union-attr]
    assert parse("2.1.0a1").channel == "alpha"  # type: ignore[union-attr]
    assert parse("2.1.0.dev1").channel == "dev"  # type: ignore[union-attr]
    assert parse("2.1.0rc1").is_prerelease  # type: ignore[union-attr]
    assert not parse("2.1.0").is_prerelease  # type: ignore[union-attr]
    assert parse("2.1.0.post1").is_prerelease is False  # type: ignore[union-attr]


def test_ordering() -> None:
    chain = ["2.1.0.dev1", "2.1.0a1.dev1", "2.1.0a1", "2.1.0a2",
             "2.1.0b1", "2.1.0rc1", "2.1.0rc2", "2.1.0", "2.1.0.post1"]
    versions = [parse(x) for x in chain]
    assert all(v is not None for v in versions)
    for left, right in zip(versions, versions[1:]):
        assert compare(left, right) < 0, (left, right)  # type: ignore[arg-type]
        assert is_newer(right.pep440, left.pep440)  # type: ignore[union-attr]


def test_cross_segment_order() -> None:
    assert is_newer("2.1.0", "2.0.99")
    assert is_newer("2.10.0", "2.9.9")
    assert is_newer("2.1.0rc2", "2.1.0rc1")
    assert is_newer("2.1.0", "2.1.0rc9")


def test_local_ignored_for_precedence() -> None:
    base = parse("2.1.0")
    local = parse("2.1.0+build.9")
    assert base is not None and local is not None
    assert compare(base, local) == 0
    assert not is_newer("2.1.0+build.9", "2.1.0")
    assert not is_newer("2.1.0", "2.1.0+build.9")


def test_parse_tag_and_sort_key() -> None:
    assert parse_tag("v2.1.0") == parse("2.1.0")
    assert parse_tag("2.1.0") == parse("2.1.0")
    assert parse_tag("nope") is None
    assert Version(2, 1, 0).sort_key() == parse("2.1.0").sort_key()  # type: ignore[union-attr]
