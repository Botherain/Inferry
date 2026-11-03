"""抓取自检：覆盖度、落点与编号一致性。

为什么需要它：同名同大小的文件可能早就躺在课程目录的**另一层**（例如自己整理的
``2.Tutorial session/Tutorial4/`` 工作副本）。只按「名字 + 大小」判断「已经抓过」
会让画布结构里的 ``2026/tutorials/T4`` 整层缺失，后面的 T5 / T6 看起来就像整体
前移了一格。这里把三类问题显式列出来：

* **覆盖**：画布上的文件 / 页面 / 讨论有没有进计划（为什么没进）；
* **落点**：计划里的「已存在」是不是落在画布位置，而不是课程目录的别处；
* **编号**：模块名 / 画布文件夹 / 文件名三处编号是否互相打架，计划里有没有缺号。

只读、纯函数：输入是采集到的 :class:`Item` 与生成的 :class:`CoursePlan`，
不联网、不写盘，源码运行与打包版都能直接跑。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .canvas_api import Item
from .classify import category_of, plan_item
from .filesync import CoursePlan, same_tree

#: 编号来源：`Lecture 4 - xxx` / `Tutorial4.ipynb` / `Week 2`
_UNIT_RE = re.compile(
    r"\b(?:tutorials?|lectures?|lecs?|weeks?|wk|chapters?|chap|ch|topics?|units?"
    r"|sessions?|assignments?)\s*[_\-]?0?(\d{1,2})\b",
    re.IGNORECASE,
)
#: 画布文件夹 / 简称：`T4` / `A1` / `HW2`
_CODE_RE = re.compile(r"^[A-Za-z]{1,2}[\s_\-]?0?(\d{1,2})$")
#: 纯数字开头：`1.Review of Algorithms` / `3.2 Gradient descent`
_LEAD_RE = re.compile(r"^0?(\d{1,2})(?=[\s._\-])")

_CATEGORY_CN = {
    "lecture": "讲义",
    "tutorial": "习题",
    "assignment": "作业",
    "project": "项目",
    "book": "参考书",
    "other": "其他",
}


@dataclass
class Finding:
    """一条自检结果。``level`` 为 error / warn / info。"""

    level: str
    kind: str  # coverage / path / numbering / gap / missing / size
    message: str


@dataclass
class Report:
    """一门课（或合并后）的自检报告。"""

    checked: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def problems(self) -> list[Finding]:
        return [f for f in self.findings if f.level in ("error", "warn")]

    @property
    def ok(self) -> bool:
        return not self.problems

    def text(self, limit: int = 12) -> str:
        """渲染成给人看的几行；info 级（无正文、沿用旧名等）不计入问题数。"""
        problems = self.problems
        if not problems:
            return f"校验：{self.checked} 项计划，未发现漏抓、落点偏移或编号冲突"
        lines = [f"校验：{self.checked} 项计划，{len(problems)} 处需要留意"]
        lines += [f"  · {f.message}" for f in problems[:limit]]
        if len(problems) > limit:
            lines.append(f"  … 另有 {len(problems) - limit} 条")
        return "\n".join(lines)


def merge(reports: list[Report]) -> Report:
    """把多门课的报告合成一份。"""
    return Report(
        checked=sum(r.checked for r in reports),
        findings=[f for r in reports for f in r.findings],
    )


# ---------------- 编号提取 ----------------

def unit_number(text: str | None) -> int | None:
    """从模块名 / 文件夹段 / 文件名里取单元编号，取不到返回 ``None``。

    只认出「有语义的编号」：``Tutorial 4``、``T4``、``A1``、``Lecture9a.pdf``、
    ``3.2 Gradient descent``；``2026``、``1502.03167.pdf`` 这类不会被当成编号。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    for regex in (_UNIT_RE, _CODE_RE):
        match = regex.search(raw) if regex is _UNIT_RE else regex.match(raw)
        if match:
            return int(match.group(1))
    # `1.Review of Algorithms.pptx` 这种「编号 + 正文」才算编号；
    # `0.jpg` / `98.npy` 这类纯数字名是数据集样本，不能当成单元编号
    match = _LEAD_RE.match(raw)
    if match:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", raw)
        if re.search(r"[A-Za-z]", stem):
            return int(match.group(1))
    return None


def folder_unit_number(folder_path: str | None) -> int | None:
    """画布文件夹里的单元编号：``course files/2026/tutorials/T4`` -> 4。"""
    parts = [p for p in (folder_path or "").replace("\\", "/").split("/") if p]
    for part in reversed(parts):
        number = unit_number(part)
        if number is not None:
            return number
    return None


def _canonical(folder: Path, item: Item) -> Path:
    """按当前分类规则算出的画布落点（页面类补 .html）。"""
    target = plan_item(folder, item)
    if item.kind in ("Page", "Discussion") and not target.name.lower().endswith((".html", ".htm")):
        target = target.with_suffix(".html")
    return target


def _short(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _target_numbers(root: Path, target: Path) -> set[int]:
    """落点里出现的编号（跳过第一层分类目录，它自带 ``1.`` / ``2.`` 前缀）。"""
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        parts = target.parts
    return {n for n in (unit_number(p) for p in parts[1:]) if n is not None}


# ---------------- 各项检查 ----------------

def _check_coverage(plan: CoursePlan, items: list[Item], prefix: str) -> list[Finding]:
    """画布上能下载 / 能存快照的条目，是不是都进了计划。"""
    planned = {(p.item.kind, p.item.file_id, p.item.title) for p in plan.files}
    out: list[Finding] = []
    for item in items:
        if item.kind not in ("File", "Page", "Discussion"):
            continue
        if (item.kind, item.file_id, item.title) in planned:
            continue
        if item.kind == "File":
            out.append(Finding(
                "warn", "coverage", f"{prefix}未抓取：{item.display_name}（没有可用的下载地址）"))
        else:
            out.append(Finding(
                "info", "coverage", f"{prefix}未保存：{item.title}（正文为空）"))
    return out


def _check_paths(plan: CoursePlan, prefix: str) -> list[Finding]:
    """计划里的「已存在」是否落在画布位置上。"""
    out: list[Finding] = []
    for pf in plan.files:
        canonical = _canonical(plan.folder, pf.item)
        if pf.action == "exists" and pf.target != canonical:
            if same_tree(pf.target.parent, canonical.parent):
                out.append(Finding(
                    "info", "path",
                    f"{prefix}沿用同一分类里的本地副本：{_short(plan.folder, pf.target)}"))
            else:
                out.append(Finding(
                    "warn", "path",
                    f"{prefix}未落到画布位置：{_short(plan.folder, canonical)}"
                    f"（实际使用了 {_short(plan.folder, pf.target)}）"))
        elif pf.action == "rename" and pf.target != canonical:
            out.append(Finding(
                "info", "path",
                f"{prefix}目标已占用，改存 {_short(plan.folder, pf.target)}"))
    return out


def _check_numbering(items: list[Item], prefix: str) -> list[Finding]:
    """模块名 / 画布文件夹 / 文件名三处编号互相打架时报警。"""
    out: list[Finding] = []
    for item in items:
        if item.kind != "File":
            continue
        module = unit_number(item.module_name)
        folder = folder_unit_number(item.folder_path)
        name = unit_number(item.display_name)
        numbers = {n for n in (module, folder, name) if n is not None}
        if len(numbers) <= 1:
            continue
        out.append(Finding(
            "warn", "numbering",
            f"{prefix}编号不一致：{item.display_name}"
            f"（模块 {_fmt_number(module)} / 画布文件夹 {_fmt_number(folder)}"
            f" / 文件名 {_fmt_number(name)}）"))
    return out


def _check_gaps(plan: CoursePlan, items: list[Item], prefix: str) -> list[Finding]:
    """画布上有编号 N 的内容，计划里是否有带编号 N 的落点。"""
    canvas: dict[str, set[int]] = {}
    for item in items:
        if item.kind not in ("File", "Page", "Discussion"):
            continue
        number = folder_unit_number(item.folder_path)
        if number is None:
            continue
        key = category_of(item.folder_path, item.display_name, item.kind, item.module_name)
        canvas.setdefault(key, set()).add(number)

    planned: dict[str, set[int]] = {}
    for pf in plan.files:
        key = category_of(pf.item.folder_path, pf.item.display_name,
                          pf.item.kind, pf.item.module_name)
        planned.setdefault(key, set()).update(_target_numbers(plan.folder, pf.target))

    out: list[Finding] = []
    for key, numbers in sorted(canvas.items()):
        out.extend(
            Finding(
                "warn", "gap",
                f"{prefix}{_CATEGORY_CN.get(key, key)}：画布上有编号 {number}，"
                f"计划里没有带此编号的落点（可能被平铺或归到了别的目录）")
            for number in sorted(numbers - planned.get(key, set()))
        )
    return out


def check_local(plan: CoursePlan, prefix: str = "") -> list[Finding]:
    """同步之后核对磁盘：该写的都写了没有、大小对不对。"""
    out: list[Finding] = []
    for pf in plan.files:
        if pf.action in ("download", "copy", "rename", "page"):
            if not pf.target.exists():
                out.append(Finding(
                    "error", "missing",
                    f"{prefix}同步后仍不存在：{_short(plan.folder, pf.target)}"))
                continue
            if (pf.action in ("download", "copy") and pf.size
                    and pf.target.stat().st_size != pf.size):
                out.append(Finding(
                    "warn", "size",
                    f"{prefix}大小与画布不一致：{_short(plan.folder, pf.target)}"
                    f"（本地 {pf.target.stat().st_size} / 画布 {pf.size}）"))
        elif pf.action == "exists" and not pf.target.exists():
            out.append(Finding(
                "warn", "missing",
                f"{prefix}本地副本已被移动或删除：{_short(plan.folder, pf.target)}"))
    return out


def check(plan: CoursePlan, items: list[Item], *, executed: bool = False) -> Report:
    """跑一遍全部检查；``executed=True`` 时额外核对磁盘结果。"""
    prefix = f"{plan.course.short}："
    findings: list[Finding] = []
    findings += _check_coverage(plan, items, prefix)
    findings += _check_paths(plan, prefix)
    findings += _check_numbering(items, prefix)
    findings += _check_gaps(plan, items, prefix)
    if executed:
        findings += check_local(plan, prefix)
    return Report(checked=len(plan.files), findings=findings)


def _fmt_number(number: int | None) -> str:
    return "—" if number is None else str(number)
