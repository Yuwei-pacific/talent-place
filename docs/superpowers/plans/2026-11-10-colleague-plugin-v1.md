# 同事插件第一版 Implementation Plan

**Goal:** 一个可上传的 Claude 插件，同事在 Code 标签页里说一句话就能跑完一次搜索，并在确认后写入 `Review.xlsx`。

**Spec:** `docs/superpowers/specs/2026-11-02-colleague-plugin-design.md`（阶段 2，按 2026-11-05 实测改走 Code 标签页）

**范围：** `cerca-stage` 和 `diagnostica` 两个 skill、打包脚本、让入口在打包后和 Windows 上能运行的引擎改动。`nuovo-master`、`nuova-edizione`、跨次运行的缓存、Indeed 接入都不在这一版。

## Global Constraints

- 引擎随插件打包；`config/` 留在 OneDrive 原处，不复制（A4：不留第二份 A2/A3）。
- 只有 `publish --confirm` 会写 `Review.xlsx`，而且必须在同事明确同意之后。
- URL、日期、职位名只能来自运行数据；skill 不让 Claude 手写卡片内容。
- 不绕过限流：等待交给引擎，Claude 和同事都不手动重试。
- 插件顶层没有 `bin/`；不提交构建产物。

## Review Focus

1. 打包后的引擎找不到 `config/`（它不再是引擎的上级目录）→ Task 1。
2. Windows 的输出编码不是 UTF-8，公司名里的字符让子进程崩溃 → Task 1。
3. 搜索跑一两个小时，电脑休眠 → Task 1。
4. 同事在错误的文件夹里打开会话 → Task 1 的 `masters` 给出明确的停止原因。
5. Claude 手抄卡片生成 shortlist 时改动了 URL → Task 2 的 `shortlist` 子命令。

## Task 1：入口能在打包后和 Windows 上运行（`engine/python/job_run.py`，测试在 `test_run_entry.py`）

- `find_config_root(start: Path) -> Path`：从 `start` 向上找含 `A1-regole-ricerca.md` 的 `config/`，也接受 `talent-place/config`；找不到时 `Stop("config_not_found")`。
- 所有子命令接受 `--config-root`；不给时用 `find_config_root(cwd)`，仓库内运行时仍回退到 `ENGINE.parent / "config"`。
- `masters` 子命令：列出每个 Master 及其输出文件夹是否存在。
- `run_step`：子进程用 UTF-8（`PYTHONUTF8=1`、`encoding="utf-8"`），并把 `python/vendor` 加进 `PYTHONPATH`；`main` 把自己的输出设为 UTF-8。
- `keep_awake()`：Windows 上用 `SetThreadExecutionState` 在运行期间阻止休眠；macOS 继续用 `caffeinate`。
- `sync_export.py doctor`：非 macOS 时不再把“OneDrive 挂载”报成失败，改为跳过并说明。

## Task 2：`shortlist` 子命令

- `job_run.py shortlist --master M --run R --ids id…`：从 `cards.json` 按 `sourceJobId` 原样复制卡片到 `shortlist.json`；未知 id 时 `Stop("card_unknown")`，什么都不写。
- `job_run.py cards --master M --run R`：打印紧凑的卡片列表（id、标题、公司、地点、发布时间、领域），供 Claude 挑选，不用自己解析大文件。

## Task 3：插件和打包（`plugin/`）

- `plugin/talent-placement/.claude-plugin/plugin.json`、`skills/cerca-stage/SKILL.md`（含 `references/verdetti.md`）、`skills/diagnostica/SKILL.md`。
- `plugin/build.py`：`npm run build`，把 `lib/`、`data/`、`python/`（不含测试）、`package.json` 和 vendored openpyxl 放进 `skills/cerca-stage/engine/`，生成 `plugin/dist/talent-placement.zip`。
- `plugin/test_plugin.py`：zip 结构、无 `bin/`、打包后的 `job_run.py masters` 能从另一个目录对着临时 config 运行、SKILL 里的命令和停止代码与 `job_run.py` 一致。

## Task 4：文档

- `CLAUDE.md`：新增插件一节和 “Where changes go” 的两行。
- spec：记录第一版范围和仍未验证的项目。

## 验证

`cd engine && npm test`、`python3 plugin/test_plugin.py`、`claude plugin validate plugin/dist/talent-placement`。Windows 上的真实运行由 Yuwei 操作，它同时就是 T6。
