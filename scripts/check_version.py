"""版本号一致性检查：唯一来源、打包接线、CHANGELOG 与发布 tag。

用法::

    python scripts/check_version.py                 # 本地 / CI 的常规检查
    python scripts/check_version.py --allow-unreleased
    python scripts/check_version.py --tag v2.1.0    # 发版前 / 工作流里校验 tag

检查项（任何一条不满足就退出码 1）：

1. ``inferry/version.py`` 的 ``__version__`` 能解析，且是规范写法；
2. ``pyproject.toml`` 用 ``dynamic = ["version"]`` 读它，没有第二份硬编码版本；
3. ``setup.py`` 与 ``Inferry.spec`` 都从 ``inferry/version.py`` 取版本；
4. ``CHANGELOG.md`` 有对应版本小节（或开发期允许的 ``[Unreleased]``）；
5. 传入 ``--tag`` 时，tag 必须等于 ``v`` + 版本号（预发布同样按规范写法）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inferry.version import CURRENT, __version__, parse_tag  # noqa: E402

PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
SETUP = ROOT / "setup.py"
SPEC = ROOT / "Inferry.spec"


def _check_packaging(problems: list[str]) -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8") if PYPROJECT.is_file() else ""
    if 'dynamic = ["version"]' not in pyproject:
        problems.append('pyproject.toml 缺少 dynamic = ["version"]')
    if "inferry.version.__version__" not in pyproject:
        problems.append("pyproject.toml 未从 inferry.version 读取版本")
    if re.search(r'^version\s*=\s*"', pyproject, re.MULTILINE):
        problems.append("pyproject.toml 里仍有硬编码的 version（版本应只有一处）")
    if "inferry" not in (SETUP.read_text(encoding="utf-8") if SETUP.is_file() else ""):
        problems.append("setup.py 缺失或未引用 inferry/version.py")
    elif "version.py" not in SETUP.read_text(encoding="utf-8"):
        problems.append("setup.py 未从 inferry/version.py 读版本")
    spec = SPEC.read_text(encoding="utf-8") if SPEC.is_file() else ""
    if "version.py" not in spec:
        problems.append("Inferry.spec 未从 inferry/version.py 读版本资源")


def _check_changelog(problems: list[str], allow_unreleased: bool) -> None:
    changelog = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.is_file() else ""
    has_version = re.search(rf"^## \[{re.escape(__version__)}\]", changelog,
                            re.MULTILINE) is not None
    has_unreleased = re.search(r"^## \[Unreleased\]", changelog,
                               re.MULTILINE) is not None
    if not has_version and not (allow_unreleased and has_unreleased):
        problems.append(f"CHANGELOG.md 缺少 ## [{__version__}] 小节")


def _check_tag(problems: list[str], tag: str) -> None:
    parsed = parse_tag(tag)
    if parsed is None:
        problems.append(f"tag 不是合法版本号：{tag!r}")
        return
    if not tag.startswith("v"):
        problems.append(f"tag 必须以 v 开头：{tag!r}")
    if parsed.pep440 != __version__:
        problems.append(f"tag {tag} 与 inferry/version.py 的 {__version__} 不一致")
    elif tag != parsed.tag:
        problems.append(f"tag 请用规范写法 {parsed.tag}（不要写成 {tag}）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查版本号架构的一致性")
    parser.add_argument("--tag", default="", help="发布 tag（如 v2.1.0），校验与代码版本一致")
    parser.add_argument("--allow-unreleased", action="store_true",
                        help="允许 CHANGELOG 里只有 [Unreleased]（开发期用）")
    args = parser.parse_args(argv)

    problems: list[str] = []
    _check_packaging(problems)
    _check_changelog(problems, args.allow_unreleased)
    if args.tag:
        _check_tag(problems, args.tag)

    print(f"version={CURRENT.pep440} channel={CURRENT.channel} tag={CURRENT.tag}")
    for problem in problems:
        print(f"  ! {problem}")
    if problems:
        print(f"版本号检查失败：{len(problems)} 项")
        return 1
    print("版本号检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
