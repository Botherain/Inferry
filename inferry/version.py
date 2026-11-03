"""版本号的唯一来源与解析规则。

这个模块是全仓库**唯一的版本定义**：``pyproject.toml`` 通过
``dynamic = ["version"]`` 读它，``Inferry.spec`` 读它生成 exe 版本资源，
发布工作流用它校验 tag 与预发布通道。发版只改这里的 ``__version__``。

写法同时满足 PEP 440（Python 打包）与 SemVer 的可读部分::

    2.1.0                 正式版
    2.1.0rc1              预发布（PEP 440 规范写法，也是 tag 的写法）
    2.1.0-beta.2          SemVer 写法，解析时归一化成 2.1.0b2
    2.1.0.dev3            开发快照
    2.1.0+build.7         构建元数据（不参与大小比较）

排序按 PEP 440：``dev < aN < bN < rcN < 正式版 < postN``；同一预发布通道内
按序号比较（``rc1 < rc2``）；构建元数据不参与比较，所以
``1.3.0+build5`` 不高于 ``1.3.0``。

tag 一律是 ``v`` + 版本号（``v2.1.0`` / ``v2.1.0rc1``）；GitHub Release 的
``prerelease`` 标记由版本本身推导，不靠手工勾选。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 唯一需要手改的一行（发布号用 PEP 440 写法）
__version__ = "2.1.0"

#: 数字段 1~3 个（``1.4`` 视作 ``1.4.0``）；第 4 段起一律拒绝
_BASE_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")
#: 预发布 / 开发 / 后发布后缀：rc1、-rc.1、beta.2、a3、preview1、dev2、post1
#: 不加结尾锚点：`a1.dev1` 这类组合要靠循环分段吃掉
_SUFFIX_RE = re.compile(r"^(rc|beta|b|alpha|a|preview|pre|dev|post)[._\-]?(\d*)", re.IGNORECASE)
#: 本地构建元数据（PEP 440 local version）
_LOCAL_RE = re.compile(r"^[a-z0-9]+(?:[.\-][a-z0-9]+)*$", re.IGNORECASE)
_SUFFIX_LABEL = {"a": "a", "alpha": "a", "b": "b", "beta": "b",
                 "rc": "rc", "pre": "rc", "preview": "rc"}
_PRE_RANK = {"a": 1, "b": 2, "rc": 3}
_CHANNEL = {"a": "alpha", "b": "beta", "rc": "rc"}


@dataclass(frozen=True)
class Version:
    """一个可比较、可规范化的版本号。``pep440`` 是它的规范字符串。"""

    major: int
    minor: int
    patch: int
    label: str = ""      # "" / "a" / "b" / "rc"
    number: int = 0      # 预发布序号
    dev: int | None = None
    post: int | None = None
    local: str = ""

    @property
    def is_prerelease(self) -> bool:
        """预发布 / 开发快照；发布工作流据此决定是否标 GitHub prerelease。"""
        return bool(self.label) or self.dev is not None

    @property
    def channel(self) -> str:
        if self.dev is not None:
            return "dev"
        return _CHANNEL.get(self.label, "stable")

    @property
    def base(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def pep440(self) -> str:
        text = self.base
        if self.label:
            text += f"{self.label}{self.number}"
        if self.post is not None:
            text += f".post{self.post}"
        if self.dev is not None:
            text += f".dev{self.dev}"
        if self.local:
            text += f"+{self.local}"
        return text

    @property
    def tag(self) -> str:
        """GitHub 发布 tag：``v2.1.0`` / ``v2.1.0rc1``。"""
        return "v" + self.pep440

    def sort_key(self) -> tuple:
        """PEP 440 的优先级键；本地元数据刻意不参与比较。"""
        if self.label:
            pre = (_PRE_RANK[self.label], self.number)
        elif self.dev is not None and self.post is None:
            pre = (0, 0)  # 1.0.dev1：低于同号 alpha
        else:
            pre = (4, 0)  # 正式版（含 post 的底版）
        dev = 0 if self.dev is not None else 1
        post = self.post if self.post is not None else -1
        return (self.major, self.minor, self.patch, pre, dev, post)

    def __str__(self) -> str:
        return self.pep440


def parse(text: str | None) -> Version | None:
    """解析 ``v2.1.0`` / ``2.1`` / ``2.1.0-rc.2`` 等写法；看不懂返回 ``None``。"""
    raw = (text or "").strip()
    if not raw:
        return None
    raw = raw.lstrip("vV")

    local = ""
    if "+" in raw:
        raw, _, local = raw.partition("+")
        local = local.strip().lower()
        if not _LOCAL_RE.match(local):
            return None

    match = _BASE_RE.match(raw)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)

    label = ""
    number = 0
    dev = None
    post = None
    rest = raw[match.end():].strip()
    if rest and not rest.strip("-_. "):
        return None  # 只有分隔符（"2.1.0-" / "2.1.0."）
    while rest:
        rest = rest.lstrip("-_. ")
        if not rest:
            break
        suffix = _SUFFIX_RE.match(rest)
        if not suffix:
            return None
        word = suffix.group(1).lower()
        digits = suffix.group(2)
        value = int(digits) if digits else 0
        if word in _SUFFIX_LABEL:
            if label:
                return None
            label = _SUFFIX_LABEL[word]
            number = value
        elif word == "dev":
            if dev is not None:
                return None
            dev = value
        else:  # post
            if post is not None:
                return None
            post = value
        rest = rest[suffix.end():]
    return Version(major, minor, patch, label, number, dev, post, local)


def parse_tag(tag: str | None) -> Version | None:
    """发布 tag -> :class:`Version`（与 :func:`parse` 同义，语义更明确）。"""
    return parse(tag)


def compare(left: Version, right: Version) -> int:
    """``-1 / 0 / 1``；只比较优先级，忽略本地构建元数据。"""
    a, b = left.sort_key(), right.sort_key()
    return (a > b) - (a < b)


def is_newer(remote: str, local: str) -> bool:
    """``remote`` 是否严格高于 ``local``；任一边解析失败都算「不是」。"""
    left, right = parse(remote), parse(local)
    if left is None or right is None:
        return False
    return left.sort_key() > right.sort_key()


CURRENT_OR_NONE = parse(__version__)
if CURRENT_OR_NONE is None:
    raise RuntimeError(f"inferry/version.py 的 __version__ 无法解析：{__version__!r}")
CURRENT: Version = CURRENT_OR_NONE
if CURRENT.pep440 != __version__:
    raise RuntimeError(
        f"__version__ 请用规范写法（如 2.1.0 / 2.1.0rc1），当前为 {__version__!r}")

#: 发版 tag（发布工作流要求 tag 与它完全一致）
VERSION_TAG = CURRENT.tag


if __name__ == "__main__":
    print(f"{CURRENT.pep440} channel={CURRENT.channel} tag={CURRENT.tag}")
