# 版本号与发布架构

本文只讲一件事：**版本号从哪里来、什么时候升哪一位、它怎样一路流到 wheel / exe /
GitHub Release**。发布操作步骤见 [`RELEASING.md`](RELEASING.md)，这里不重复。

## 1. 唯一来源

```
inferry/version.py  ──┬─→ pyproject.toml（dynamic = ["version"]）──→ wheel / sdist
   __version__        ├─→ setup.py（旧 pip 的 editable 垫片）
                      ├─→ Inferry.spec（exe 文件属性）
                      ├─→ inferry.__init__ / --version / 更新检查
                      ├─→ scripts/check_version.py ──→ CI / 发布工作流
                      └─→ CHANGELOG 的版本小节（人工对照）
```

- **只改 `inferry/version.py` 的 `__version__`**，别的地方一律不写死版本。
- `pyproject.toml` 用 PEP 621 的动态版本读取它；`pip install .` / `python -m build`
  产出的包版本自动跟随，不再需要「改两处、再靠自检发现不一致」。
- 发版前跑一次：

  ```bash
  python scripts/check_version.py                 # 常规一致性
  python scripts/check_version.py --tag v2.1.0    # 校验 tag 与代码版本
  ```

## 2. 版本号格式

规范写法（`__version__` 与 tag 都用它）：

```
MAJOR.MINOR.PATCH[-预发布][+构建元数据]
```

| 场景 | `__version__` | GitHub tag | 说明 |
| --- | --- | --- | --- |
| 正式版 | `2.1.0` | `v2.1.0` | 默认通道 |
| Release Candidate | `2.1.0rc1` | `v2.1.0rc1` | 只缺最后一轮验证 |
| Beta | `2.1.0b2` | `v2.1.0b2` | 功能已齐，仍可能改 |
| Alpha | `2.1.0a1` | `v2.1.0a1` | 内部试用 |
| 开发快照 | `2.1.0.dev3` | 不打 tag | 本地 / CI 实验用 |
| 构建元数据 | `2.1.0+build.7` | 不打 tag | 不参与大小比较 |

- **tag 永远是 `v` + 版本号**；`V2.1.0`、`v2.1`、`release-2.1.0` 都会被
  `check_version.py` 拦下。
- 解析器也接受 SemVer 风格的 `2.1.0-rc.1`、`2.1.0-beta.2`，但**入库前会归一化**成
  `2.1.0rc1` / `2.1.0b2`；`__version__` 本身必须是规范写法，避免缓存里并存两种字符串。
- 兼容性排序（PEP 440）：

  ```
  2.1.0.dev3 < 2.1.0a1 < 2.1.0a2 < 2.1.0b1 < 2.1.0rc1 < 2.1.0rc2 < 2.1.0 < 2.1.0.post1
  ```

  构建元数据不参与比较：`1.3.0+build5` 不高于 `1.3.0`（更新检查不会把它当成新版本）。
  同一预发布通道内按序号比较，所以 `rc2 > rc1`，而不会像旧实现那样把两者视为同号。

## 3. 什么时候升哪一位

按 [语义化版本](https://semver.org/lang/zh-CN/) 的常见解读，结合本项目的发布形态：

| 变化 | 升位 | 例子 |
| --- | --- | --- |
| 破坏兼容 | **MAJOR** | 数据目录 / 包名 / 命令行再改名；删除旧命令别名；配置或 `state.json` 需要迁移；提高 Python 地板 |
| 向后兼容的新功能 | **MINOR** | 新增子命令、页面、配置项（默认值保持旧行为）；新增可选能力 |
| 只修 bug | **PATCH** | 修抓取、排序、登录过期提示等，不引入新入口 |
| 预发布 | 在目标版本后加后缀 | 计划发 `2.2.0`，先发 `2.2.0rc1`；`rc` 不带新功能 |
| 文档 / 注释 / CI | 不升 | 随下一次功能或修复一起发 |

判断口径：

- **用户能不能感知到「多了东西」**：能 → MINOR；只是「原来不对，现在对了」→ PATCH。
- **老配置 / 老数据能否直接继续用**：不能 → MAJOR，并且必须写迁移。
- 预发布不单独占升位：`2.1.0rc1` 与 `2.1.0` 是同一个 MINOR 版本的两个阶段。

示例（本仓库的真实决定）：

- `2.0.0`：包名、数据目录、计划任务、命令行全部改名 → MAJOR；
- `2.1.0`：新增 `inferry verify`、抓取补齐行为 → MINOR；
- 只修一个排序 bug → `2.1.1`。

## 4. 预发布通道

- Alpha / Beta / RC 用同一个版本号 + 后缀递增（`a1 → a2 → b1 → rc1 → rc2 → 正式版`），
  **不要**为了「再测一轮」另起一个版本号。
- 更新检查默认忽略预发布；用户在配置里打开 `update.include_prerelease` 才会收到。
  **以版本号本身判定**：即使 GitHub Release 忘了勾 `prerelease`，`rc/beta/alpha/dev`
  也不会推给稳定版用户。
- 发布工作流会根据版本自动设置 GitHub 的 `prerelease` 标记，无需手工勾选。
- 预发布之间可以覆盖安装；退回正式版时若数据格式没变，直接装回上一正式版即可。

## 5. 发布流程

1. 平时改动只记在 `CHANGELOG.md` 的 `## [Unreleased]`。
2. 决定发版时，按第 3 节选升位，改 `inferry/version.py`。
3. 把 `[Unreleased]` 改成 `## [X.Y.Z] - YYYY-MM-DD`（预发布同样写规范版本号），
   并按 Keep a Changelog 归类（新增 / 修复 / 改动 / 升级须知）。
4. 本地检查：

   ```bash
   python scripts/check_version.py --tag vX.Y.Z
   python -m pytest
   python tests/smoke.py
   python -m inferry --selftest
   ```

5. 提交后打**附注** tag 并推送：

   ```bash
   git tag -a vX.Y.Z -m "Inferry vX.Y.Z"
   git push origin vX.Y.Z
   ```

6. CI 会：校验 tag 与 `inferry/version.py` 一致 → 构建 wheel / sdist / 单目录 exe →
   跑 `--selftest` → 打 zip → 从 CHANGELOG 抽取本节生成 Release 说明 → 发布
   （预发布自动带 `--prerelease`）。
7. 发布后不要改回旧版本号；下一个改动继续进新的 `[Unreleased]`。

## 6. 产物命名

| 产物 | 名称 | 来源 |
| --- | --- | --- |
| GitHub tag | `v2.1.0` / `v2.1.0rc1` | `Version.tag` |
| Windows 绿色包 | `Inferry-v2.1.0-win64.zip` | tag + 固定后缀 |
| wheel | `inferry-2.1.0-py3-none-any.whl` | `pyproject.toml` 动态版本 |
| sdist | `inferry-2.1.0.tar.gz` | 同上 |
| Release 标题 | `Inferry v2.1.0` | 工作流 |

预发布产物同样带后缀（`Inferry-v2.1.0rc1-win64.zip`），文件名与版本一一对应，便于回滚。

## 7. 兼容性约定

- **应用版本 ≠ 数据格式版本。** `config.json` / `state.json` 不写死应用版本号；迁移逻辑
  必须**幂等**（重复执行无副作用），并按「观察到旧结构」触发，而不是按 `__version__`
  判断。MAJOR 版本允许附带一次性迁移，迁移失败必须保留原数据。
- **配置新增项要给默认值**，并且默认行为与旧版一致；删配置项要至少保留一个大版本。
- **更新器只做「向前兼容」**：旧客户端看不懂新 tag 时应当跳过，而不是误报更新；
  新客户端必须能比较旧版本号（`v1.4` 补齐为 `1.4.0`，`rc1 < 正式版`）。
- **回滚**：预发布阶段可以直接装回上一个正式版；正式版回滚到旧 MAJOR 时，若数据目录
  改过名，按 CHANGELOG 的「升级须知」把数据目录改回去——不要依赖程序自动倒推。

## 8. 不要做的事

- 不要在 `pyproject.toml`、spec、工作流里再写一份版本号字面量。
- 不要用 `2.1.0-rc1` 这种非规范写法当 `__version__` 或 tag（解析器能读，但入库会归一化，
  容易让缓存和比较出现两套字符串）。
- 不要为了触发一次 CI 就改版本号；`workflow_dispatch` 可以手动构建。
- 不要把预发布版本当成 PATCH：`2.1.0rc1` 与 `2.1.0` 是同一个 MINOR 的两步。
- 不要在 tag 之后继续改 `version.py` 再推同一 tag；打错就删 tag 重打，并确认没有已发布资产。
