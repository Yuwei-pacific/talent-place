# Windows 实测工具（阶段 0）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做一个可上传的 Claude 插件，在同事的 Windows 电脑上跑完阶段 0 的七项实测（重点是一条命令能否连续跑 2–3 小时），并产出一份能直接对照判定表的结果；同时修掉 PR 4 里 `read` 的计数问题，否则实测结果不可信。

**Architecture:** `spike/windows-probe/` 是一个一次性插件：一个 skill、一个只用标准库的 `probe.py`、一份当前引擎的副本。所有写入都限制在名字含 `TEST` 的文件夹里。阶段 0 结束、方向定下后，整个 `spike/` 删除。

**Tech Stack:** Python 3 标准库 + 随包携带的 openpyxl；现有 Node 引擎（`engine/lib`）；Claude 插件格式（`.claude-plugin/plugin.json`、`skills/<name>/SKILL.md`、`${CLAUDE_SKILL_DIR}`）。

**Spec:** `docs/superpowers/specs/2026-11-02-colleague-plugin-design.md`

**范围：** 只覆盖 spec 的阶段 0。阶段 1–3 另写计划；其中多数工作不取决于走 Cowork 还是 Code 标签页，可以在等 Team 方案审批时并行。

## Global Constraints

- 只用测试文件夹和 `Review.xlsx` 的副本。任何写入目标的文件夹名不含 `TEST` 时，脚本拒绝运行。
- 不绕过登录、CAPTCHA 或限流。收到 429 立刻停止对该站点的请求，不重试。
- 输出和文件读写一律显式 UTF-8。路径含空格和 `-`（真实 OneDrive 路径就是这样）。
- 插件顶层不能有 `bin/` 目录（否则 Cowork 拒绝安装）。上限 5,000 个文件、200 MB。
- 插件内脚本用 `${CLAUDE_SKILL_DIR}` 引用。插件目录视为只读，产出全部写到 TEST 文件夹。
- 脚本不读取、不打印 `Review.xlsx` 的单元格内容（含联系人）。
- 不提交、不推送，除非 Yuwei 明确要求。计划里的 Commit 步骤在获得同意后才执行。
- `spike/` 不进 `tsconfig`，也不进 `npm test` 链。

## Review Focus

1. **同事选错文件夹（选了正式的 Master 文件夹）：** 脚本必须拒绝，不写任何文件 → Task 3 `test_refuses_non_test_folder`。
2. **Windows 控制台不是 UTF-8：** 输出含 `è` 或 `—` 时不能因编码报错 → Task 3 `test_output_survives_cp1252`。
3. **报告把限流当成沙盒不通：** 429 是 `INCONCLUSIVE`（等 20 分钟再测），不是 `FAIL`，否则判定表会把人带到错误的分支 → Task 4 `test_429_is_inconclusive_and_stops`。
4. **沙盒代理的 403 被当成 LinkedIn 的 403：** 这两者的处理方式完全不同（前者由 Owner 配置域名）→ Task 4 `test_allowlist_403_named`。
5. **打包后的引擎跑不起来：** `lib/` 没有 `package.json` 时，Node 不按 ESM 解析，同事那边第一步就崩 → Task 5 `test_staged_engine_runs_from_other_cwd`。

---

## 文件结构

```
spike/
  build.py                          # 组装并打 zip（输出到 spike/dist/，加进 .gitignore）
  test_spike.py                     # probe 和 build 的离线测试
  GUIDA-collega.md                  # 给同事的一页意大利语操作说明
  RESULTS-template.md               # 结果表 + spec 的判定规则
  windows-probe/
    .claude-plugin/plugin.json
    skills/probe/
      SKILL.md
      references/full-run.md        # T6 的步骤
      scripts/probe.py
```

打包时写入 `skills/probe/engine/`：`lib/`、`python/`（不含 `test_*`）、`data/`、`package.json`，以及 `python/vendor/`（openpyxl、et_xmlfile）。

---

### Task 1: 让 `synced_fs` 能在 Windows 上工作

Code 标签页兜底路线直接在 Windows 上运行，不先修好，T5 必然崩溃，测出来的只是这个已知 bug。这也完成了 spec 阶段 1 第 1 项的前半部分（`doctor` 留到阶段 1）。

**Files:**
- Modify: `engine/python/synced_fs.py`（`is_dataless`、`describe`，新增常量）
- Test: `engine/python/test_sync_export.py`（`TestDataless` 类）

**Interfaces:**
- Produces: `is_dataless(path) -> bool` 和 `describe(path) -> dict` 在没有 `st_blocks` 的 `stat` 结果上不抛异常；`describe` 的 `"blocks"` 在这种情况下为 `None`。

- [ ] **Step 1: 写失败的测试**

在 `TestDataless` 里加 `WinStat`（没有 `st_blocks`、`st_flags`，有 `st_file_attributes`），沿用现有 `patch_stat_for` 的打补丁方式：

```python
class WinStat:
    def __init__(self, size=100, attrs=0x20, mode=0o100644):
        self.st_size, self.st_file_attributes, self.st_mode = size, attrs, mode
        self.st_mtime_ns, self.st_mtime = 1, 0.0

def test_windows_local_file_is_not_dataless(self):       # attrs=0x20 → False
def test_windows_recall_on_data_access_is_dataless(self): # attrs=0x20|0x400000 → True
def test_windows_recall_on_open_is_dataless(self):        # attrs=0x20|0x40000 → True
def test_windows_offline_is_dataless(self):               # attrs=0x20|0x1000 → True
def test_describe_without_st_blocks(self):                # describe(f)["blocks"] is None, ["dataless"] is False
```

`patch_stat_for` 现在只构造 `FakeStat`，给它加一个可选的 `stat_result=` 参数以传入 `WinStat`。

- [ ] **Step 2: 确认测试失败**

Run: `cd engine && python3 python/test_sync_export.py TestDataless`
Expected: FAIL，`AttributeError: ... 'st_blocks'`

- [ ] **Step 3: 实现**

在 `synced_fs.py` 增加 `WIN_ONLINE_ONLY_ATTRS = 0x1000 | 0x40000 | 0x400000`（OFFLINE、RECALL_ON_OPEN、RECALL_ON_DATA_ACCESS）。`is_dataless`：有 `st_file_attributes` 时按这个掩码判断；否则走现有的 `st_flags` 判断；`st_blocks` 用 `getattr(st, "st_blocks", None)`，为 `None` 时跳过“零 block”判断。`describe` 同样用 `getattr`。更新模块 docstring 第一句，说明它现在也覆盖 Windows。

- [ ] **Step 4: 确认全部通过**

Run: `cd engine && python3 python/test_sync_export.py`
Expected: `OK`（原有 macOS 用例不变）

- [ ] **Step 5: Commit**

```bash
git add engine/python/synced_fs.py engine/python/test_sync_export.py
git commit -m "Recognise online-only files on Windows instead of crashing on st_blocks"
```

---

### Task 2: `read` 如实报告没读到内容的页面

PR 4 的 `read` 把没有职位内容的 200 页面算成“已读”（已复现：`read 3 new`，3 条描述长度都是 0）。LinkedIn 改版或返回登录页时，T6 会显示成功，其实什么都没读到。410 的职位也会每次重新请求。

**Files:**
- Modify: `engine/src/read-postings.ts`、`engine/src/cli.ts`（`cmdRead` 的输出）
- Test: `engine/test/unattended-smoke.mjs`

**Interfaces:**
- Produces: `ReadReport` 增加 `empty: number`。`read` 只计 `desc` 非空的页面；200 但 `desc` 为空的计入 `empty`，下次运行重新请求。CLI 输出变为 `read N new, E empty, ...`。Task 5 的 `references/full-run.md` 依赖这个输出。

- [ ] **Step 1: 写失败的测试**

在 `unattended-smoke.mjs` 的 read 用例旁边，沿用其中的本地服务器和 `guardWith`：

```js
// A 200 with no posting in it is not a read: a sign-in wall must not look like success.
// report.read === 0, report.empty === 3；再跑一次：服务器又收到 3 个请求
// A posting that is gone stays gone: 410 的卡片第二次运行不发请求，report.alreadyRead === 3
```

- [ ] **Step 2: 确认测试失败**

Run: `cd engine && npm run build && node test/unattended-smoke.mjs`
Expected: 断言失败（`report.read` 是 3）

- [ ] **Step 3: 实现**

`readPostings` 里 `res.ok` 分支按 `desc` 是否为空分别计数；“已读”判断改成 `desc` 非空或 `http` 为 404、410。`cmdRead` 输出加上 `empty`。

- [ ] **Step 4: 确认通过**

Run: `cd engine && npm test`
Expected: 全部通过（`employer-smoke` 需要联网）

- [ ] **Step 5: Commit**

```bash
git add engine/src/read-postings.ts engine/src/cli.ts engine/test/unattended-smoke.mjs
git commit -m "Stop counting a page with no posting in it as a read"
```

---

### Task 3: `probe.py` 的 env、fs、state 子命令（T2、T4、T5）

**Files:**
- Create: `spike/windows-probe/skills/probe/scripts/probe.py`
- Test: `spike/test_spike.py`

**Interfaces:**
- Consumes: `synced_fs.write_atomically`、`assert_writable`、`is_dataless`、`excel_lock_present`、`GuardFailure`。
- Produces（Task 4、5 依赖）：
  - CLI：`probe.py {env,net,fs,state} --master DIR ...`，退出码 0 = 已记录（结果可以是 FAIL）；2 = 拒绝运行。
  - `require_test_folder(path: str) -> Path`：文件夹不存在或名字不含 `TEST` 时 `SystemExit(2)`。
  - `record(master: Path, test_id: str, status: str, detail: dict) -> None`：追加到 `<master>/probe-report.jsonl`，并打印一行 `T5 PASS ...`。`status` 取值：`PASS`、`FAIL`、`INCONCLUSIVE`。
  - `engine_python_dir() -> Path`：优先 `<skill>/engine/python`，不存在时回退到仓库的 `engine/python`（供测试用）；存在 `vendor/` 时也加入 `sys.path`。

**子命令：**

| 命令 | 记录 | 判定 |
|---|---|---|
| `env --master D` | `T2`：平台、`uname`、Python 版本、`node --version`、openpyxl 版本及来源（vendor/系统）、skill 目录是否可写、`node <skill>/engine/lib/cli.js` 和 `python sync_export.py --help` 能否运行 | Python ≥ 3.10、Node 可用、openpyxl 可导入、两个引擎命令都能运行时 `PASS`。缺哪项写进 `detail.missing`，不抛异常 |
| `fs --master D --config C` | `T4`：`C/A1-regole-ricerca.md` 和 `A4-regole-registrazione.md` 可读，`D` 可写（写入 `probe-marker-<UTC时间>.txt`）。`T5-write`：用 `write_atomically` 写 `probe-atomic.txt`；把 `Review.xlsx` 复制为 `probe-roundtrip.xlsx`，用 openpyxl 打开再保存（不读单元格） | 各自 `PASS`/`FAIL`。`Review.xlsx` 缺失时 `T5-write` 为 `FAIL`，理由写明 |
| `state --master D --label L` | `T5-L`，`L` 为 `normal`、`excel-open`、`online-only`：记录 `Review.xlsx` 的原始 `stat` 字段（有什么记什么）、目录里的 `~$` 文件名、`assert_writable` 的结果（`allowed`、`refused:<reason>`、`crashed:<异常类型>`）。仅 `excel-open` 时再用 `write_atomically(guard=False)` 写回原字节，记录是被操作系统拒绝还是成功了 | `normal`：`allowed` 时 `PASS`。其余两种：`refused:*` 时 `PASS`。`crashed:*` 永远 `FAIL` |

入口处执行 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。目录只做一次非递归 `os.listdir`（遍历 OneDrive 挂载很慢，见 `synced_fs.py` 开头）。

- [ ] **Step 1: 写失败的测试**

`spike/test_spike.py` 用 `unittest`，用 `subprocess` 调 `probe.py`，临时目录命名为 `"TEST probe - spaced"`（含空格和 `-`）：

```python
def test_refuses_non_test_folder(self):      # 文件夹名 "Strategic design ED.28"：退出码 2，目录仍为空
def test_output_survives_cp1252(self):       # env={"PYTHONIOENCODING":"cp1252"}：退出码 0，无 UnicodeEncodeError
def test_env_records_t2(self):               # jsonl 有 T2，detail 含 python_version、node_version、openpyxl_source
def test_env_missing_node_is_fail_not_crash(self):  # PATH 去掉 node：T2 FAIL，"node" in detail["missing"]，退出码 0
def test_fs_passes_on_good_folders(self):    # 有 config 和 Review.xlsx：T4、T5-write PASS；probe-roundtrip.xlsx 可被 openpyxl 打开
def test_fs_missing_review_is_reported(self):# 无 Review.xlsx：T5-write FAIL，退出码 0
def test_fs_never_touches_review(self):      # Review.xlsx 的字节和 mtime 不变
def test_state_excel_lock_refused(self):     # 放一个 "~$Review.xlsx"，--label excel-open：T5-excel-open PASS，detail 含 refused:excel_lock
def test_state_normal_allowed(self):         # --label normal：PASS
def test_state_lock_undetected_is_fail(self):# 没有 ~$，--label excel-open：FAIL（guard 没看到锁）
```

- [ ] **Step 2: 确认测试失败**

Run: `python3 spike/test_spike.py`
Expected: FAIL（`probe.py` 不存在）

- [ ] **Step 3: 按上表实现 `probe.py`**（只用标准库，openpyxl 按需导入）

- [ ] **Step 4: 确认测试通过**

Run: `python3 spike/test_spike.py`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add spike/test_spike.py spike/windows-probe/skills/probe/scripts/probe.py
git commit -m "Probe the sandbox's runtime and its behaviour on the mounted OneDrive folder"
```

---

### Task 4: `probe.py net`（T3）

**Files:**
- Modify: `spike/windows-probe/skills/probe/scripts/probe.py`
- Test: `spike/test_spike.py`

**Interfaces:**
- Consumes: Task 3 的 `record`、`require_test_folder`。
- Produces：
  - `classify_response(status: int | None, body: str, error: str | None) -> str`，返回 `ok`、`rate_limited`、`allowlist_blocked`、`forbidden`、`challenge`、`network_error`、`http_error` 之一。
  - CLI：`probe.py net --master D [--linkedin-base URL] [--employer-url URL] [--pause SEC]`。默认 `https://www.linkedin.com`、`https://www.re-lab.it/career-archive/career-single?career=service-design-intern-157064`（2026-11-02 `employer-checks.csv` 中验证过的页面）、10 秒。

**规则：**
- `User-Agent` 和 `Accept-Language` 与 `engine/src/discovery/http.ts` 相同。超时 25 秒。
- 顺序：LinkedIn 搜索（`/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=design+internship&location=Milan&start=0`）→ 等 `--pause` → 用返回中第一个 `urn:li:jobPosting:(\d+)` 请求 `/jobs-guest/jobs/api/jobPosting/<id>` → 雇主页面。**LinkedIn 最多两个请求。**
- `allowlist_blocked`：状态 403 且正文含 `blocked-by-allowlist`（Cowork 代理的已知文案，见 spec 来源的问题报告）。
- `challenge`：正文前 20,000 字符含 `http.ts` 里 `BLOCKED_MARKERS` 中的任一项（复制这份列表，不要扩充）。
- 判定：
  - 三个请求都 `ok`，且搜索结果有职位 id、详情页含 `show-more-less-html__markup` → `T3 PASS`
  - 任一 LinkedIn 请求 `rate_limited` → **跳过剩余的 LinkedIn 请求**，雇主页面照测；`T3 INCONCLUSIVE`，`detail.retry_after_minutes = 20`
  - 其他 → `T3 FAIL`，`detail` 按 URL 列出分类结果

- [ ] **Step 1: 写失败的测试**

用 `http.server` 在本地起假服务（参照 `engine/test` 的离线风格）：

```python
def test_all_ok_is_pass(self):                 # 三个路径都返回预期内容 → T3 PASS
def test_429_is_inconclusive_and_stops(self):  # 搜索返回 429 → T3 INCONCLUSIVE；服务端收到的 LinkedIn 请求数 == 1；雇主页仍被请求
def test_allowlist_403_named(self):            # 403 + "blocked-by-allowlist" → FAIL，detail 含 allowlist_blocked
def test_plain_403_is_forbidden(self):         # 403 无该文案 → classify_response 返回 forbidden
def test_empty_results_is_fail(self):          # 200 但没有 urn → FAIL，不请求详情页
def test_connection_refused_is_network_error(self):  # 端口没服务 → FAIL，退出码 0
```

- [ ] **Step 2: 确认测试失败**

Run: `python3 spike/test_spike.py`
Expected: FAIL（没有 `net` 子命令）

- [ ] **Step 3: 实现 `classify_response` 和 `net`**

- [ ] **Step 4: 确认测试通过**

Run: `python3 spike/test_spike.py`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add spike/test_spike.py spike/windows-probe/skills/probe/scripts/probe.py
git commit -m "Probe LinkedIn and an employer page, telling a sandbox block from a rate limit"
```

---

### Task 5: 插件内容和打包

**Files:**
- Create: `spike/windows-probe/.claude-plugin/plugin.json`
- Create: `spike/windows-probe/skills/probe/SKILL.md`
- Create: `spike/windows-probe/skills/probe/references/full-run.md`
- Create: `spike/build.py`
- Modify: `.gitignore`（加 `spike/dist/`）
- Test: `spike/test_spike.py`

**Interfaces:**
- Consumes: Task 3、4 的 `probe.py` CLI；Task 2 的 `read` 输出。
- Produces: `python3 spike/build.py` 生成 `spike/dist/talent-placement-probe.zip`，同事上传这个文件。用户运行的命令是 `/talent-placement-probe:probe`。

**`plugin.json`：** `name` = `talent-placement-probe`，`displayName` = `Talent Placement Probe`，`version` = `0.1.0`，`description` 说明这是一次性环境测试工具。

**`build.py`：**
- 先在 `engine/` 运行 `npm run build`。
- 复制插件到 `spike/dist/talent-placement-probe/`，再写入 `skills/probe/engine/`：`lib/`、`data/`、`package.json`、`python/`（去掉 `test_*.py`、`__pycache__`）。
- 把当前 Python 环境里的 `openpyxl`、`et_xmlfile` 复制到 `python/vendor/`（纯 Python，PyPI 被封时也能用）。
- 打 zip，插件文件夹作为唯一顶层条目。

**`SKILL.md`（说明用意大利语面向同事，指令用英语面向 Claude）：**
1. `description` 写明触发场景：运行 Talent Placement 环境测试。
2. 确认同事已附加两个文件夹：`talent-place/config` 和名字含 `TEST` 的测试文件夹；缺哪个就请同事添加。
3. Python 命令依次尝试 `python3`、`python`、`py -3`。
4. 依次运行 `env`、`net`、`fs`、`state --label normal`，每次运行后原样显示 `probe.py` 打印的结果行。
5. 请同事用 Excel 打开测试文件夹的 `Review.xlsx`，等确认后运行 `state --label excel-open`；请同事关闭。
6. 请同事右键 `Review.xlsx` 选“释放空间”（*Libera spazio*），等确认后运行 `state --label online-only`。
7. 请同事做两项人工检查并记入结果表：在 Excel 里打开 `probe-roundtrip.xlsx`；在 OneDrive 网页上找到 `probe-marker-*.txt`（确认已同步上云）。
8. T7：如果有 Indeed 连接器的工具，用“stage design / Milano”搜索一次，告诉同事工具名和是否返回结果，由同事记入结果表；没有就报告 `Unavailable`。
9. T6 只在同事明确要求时才开始：读 `references/full-run.md`。

**写进 `SKILL.md` 的硬规则：**
- 结果行原样转述，不解释、不美化。
- 不读 `Review.xlsx` 或 `history.csv` 的内容。
- 收到 429 不手动重试：等待由引擎的 `cooldownMinutes` 负责；`probe.py net` 报 `INCONCLUSIVE` 时至少等 20 分钟再测。
- 只在 TEST 文件夹里写文件。
- 报错就原样显示，不自行修改脚本后再试。

**`references/full-run.md`（T6，产出放 `<TEST>/_probe-run/`）：**
1. 请同事先记下 Claude 用量页面（Settings → Usage）的数字。
2. 读 A1、A4、所选 Master 的 A2 和 A3。
3. `sync_export.py export-history --dir <TEST> --out _probe-run/history.csv`。
4. 按 A1 组装 `_probe-run/run.json`，字段参照 `engine/src/pipeline.ts` 的 `PipelineConfig`：`topK` 200，`cooldownMinutes` 20，`maxCooldowns` 12，不设 `recencyDays`，不用任何 deroga。
5. 在后台运行 `node engine/lib/cli.js discover --config ... --out _probe-run --history ...`，输出重定向到 `_probe-run/discover.log`。预计 2 小时左右。**这是这次实测的重点：** 记下开始和结束时间，以及命令有没有被 shell 超时、沙盒或电脑休眠打断。被打断就用同样的参数加 `--resume` 接着跑，并记下接了几次。
6. 同样在后台运行 `node engine/lib/cli.js read --cards _probe-run/cards.json --out _probe-run --top 60 --cooldown-minutes 20`，预计约 1 小时。输出里的 `empty` 不为 0 时要报告。
7. 按 A1/A2 判断已读的每条职位，写入 `_probe-run/verdicts.json`。
8. **不运行 `stage` 和 `append`。**
9. 报告：`run-report.json` 的 `sources`（含 `health.events429`、`cooldowns`）和 `counters`、`read-report.json`、中断和续跑次数，请同事再记一次用量。

- [ ] **Step 1: 写失败的测试**

```python
def test_zip_layout(self):                     # 唯一顶层目录；含 .claude-plugin/plugin.json 和 skills/probe/SKILL.md；顶层没有 bin/
def test_zip_limits(self):                     # 文件数 < 5000，总大小 < 200 MB
def test_no_test_files_shipped(self):          # 没有 test_sync_export.py、__pycache__
def test_staged_engine_runs_from_other_cwd(self):  # 在临时 cwd 下运行解压后的 node engine/lib/cli.js：输出含 "discover"
def test_vendored_openpyxl_imports(self):      # python3 -I -c，sys.path 只加 vendor 目录，import openpyxl 成功
def test_probe_uses_staged_engine(self):       # 解压后的 probe.py env：T2 的 openpyxl_source == "vendor"
def test_skill_frontmatter(self):              # SKILL.md 的 name == "probe"，description 长度 ≤ 1024
```

`build` 测试只运行一次（`setUpClass`），因为它会调用 `npm run build`。

- [ ] **Step 2: 确认测试失败**

Run: `python3 spike/test_spike.py`
Expected: FAIL（`build.py` 不存在）

- [ ] **Step 3: 按上面的说明写所有文件**

- [ ] **Step 4: 确认测试通过并校验插件**

Run: `python3 spike/test_spike.py && claude plugin validate spike/dist/talent-placement-probe`
Expected: `OK`，以及 `✔ Validation passed`

- [ ] **Step 5: Commit**

```bash
git add .gitignore spike/build.py spike/test_spike.py spike/windows-probe
git commit -m "Package the Windows probe as an uploadable Claude plugin"
```

---

### Task 6: 操作文档和 Mac 预演

**Files:**
- Create: `spike/GUIDA-collega.md`
- Create: `spike/RESULTS-template.md`

**Interfaces:**
- Consumes: Task 5 的 zip 和命令名。

**`GUIDA-collega.md`（意大利语，一页，不出现命令行）：** 安装 Claude 桌面应用并登录 Team 账号 → *Customize > Plugins > Add > Upload plugin* 上传 zip → 新建 Cowork 任务 → 附加两个文件夹 → 输入 `/talent-placement-probe:probe` → 按提示操作 → 把 `probe-report.jsonl` 发给 Yuwei。再加一段：如果 Cowork 不通，切到 Code 标签页重复（Yuwei 会先说明如何安装 Node 和 Python）。

**`RESULTS-template.md`：**
- 一张表：T1–T7，每项一列 Cowork、一列 Code 标签页，附备注。
- T6 单独记录：开始和结束时间、是否被打断（超时、沙盒、休眠）及 `--resume` 次数、用量前后数字、`events429` 和 `cooldowns`。
- 原样抄录 spec 阶段 0 的“判定”四条，最后一行写结论和日期。

**测试文件夹由 Yuwei 准备：** 在 `jobSearch_outPut/` 下新建 `TEST-probe/`，把一个 Master 的 `Review.xlsx` 复制进去。这个文件含真实联系人，用完就删除。

- [ ] **Step 1: 写这两个文件**

- [ ] **Step 2: 自动化检查（本机模拟）**

用真实路径模拟同事的操作，但目标是 `jobSearch_outPut/TEST-probe/`：解压 zip，依次运行 `probe.py env`、`fs`、`state --label normal`。

Expected: `T2`、`T4`、`T5-write`、`T5-normal` 都是 `PASS`；`probe-marker-*.txt` 出现在 OneDrive 网页上。**`net` 只在 Yuwei 同意后才运行**，它会向 LinkedIn 发请求。

- [ ] **Step 3: Mac 上的 Cowork 预演（需要 Yuwei 操作）**

Yuwei 用自己的账号上传 zip，在 Cowork 里跑一遍。这不能替代 Windows 实测，但不需要等 Team 预算，当天就能知道 T1（插件能否加载）和 T3（沙盒能否连上 LinkedIn）的初步情况。把结果记入 `RESULTS-template.md` 的备注。

Expected: 同事照着说明能走通；发现说明不清楚的地方就改。

- [ ] **Step 4: Commit**

```bash
git add spike/GUIDA-collega.md spike/RESULTS-template.md
git commit -m "Write the colleague's guide and the results sheet for the Windows probe"
```

---

## 完成之后

1. Yuwei 把 zip、说明和结果表交给同事，在 Windows 上跑 T1–T7。
2. 按判定表决定走 Cowork 还是 Code 标签页，结果写回 spec。
3. 写阶段 1–3 的实施计划，然后删除 `spike/`。
