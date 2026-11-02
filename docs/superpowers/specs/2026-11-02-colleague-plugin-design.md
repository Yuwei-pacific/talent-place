# Job Search：让不懂技术的同事自己运行

## 背景

Yuwei 可能在 **1 个月内**交接或离开。之后要由不懂技术、使用 **Windows** 的同事自己发起搜索，结果写入该 Master 的 `Review.xlsx`，并且可能没有技术人员维护。公司可以为此申请预算，同事目前没有 Claude 账号，但可以自己安装软件。很快还要接入新的 Master。

现状的关键缺口：判断环节（按 A1/A2 判断、写 TSV）和流程驱动都由 Claude Code 完成，`engine/` 里没有 AI 调用，也没有把步骤串起来的入口。读描述（`fetch-descriptions.py`）和组装 TSV（`build-tsv.py`）的脚本都留在运行目录里，不在仓库中（YUW-81、YUW-84）。

**做成什么：** 一个 Claude 插件。同事在 Claude 桌面应用里选好文件夹，说“cerca stage per Strategic design”，由 Claude 跑完全流程，用意大利语汇报结果和需要决定的事。

**1 个月内的成功标准：** 一位同事在自己的 Windows 电脑上、没有 Yuwei 帮助，独立跑完一次真实搜索，已核实的职位正确写入 `Review.xlsx`，覆盖缺口如实说明。

## 决定

**Yuwei 决定的**
- 同事自己发起搜索；使用 Claude 桌面应用 + 插件，不开发独立程序；费用走公司预算
- 不到 1 个月，先做最小可用版本
- **被限流时：** 写入已读过并核实的职位，明确列出未覆盖的领域，隔天再跑补上。这算有效运行，但不算“完整”（与 2026-11-02 的做法一致）
- **Master 范围：** 现有两个加上换届，而且很快要接入新 Master，所以需要带引导的新建流程

**我的判断（可以推翻）**
- **Cowork 优先，Code 标签页兜底：** Cowork 实测不通时，改用桌面应用的 Code 标签页（同一个插件，命令直接在 Windows 上运行，用本机网络）。这比之前说的“改做独立应用”更现实。代价是每台电脑要装一次 Node 和 Python，同事有安装权限。
- **TSV 由代码生成：** AI 只给判断，不写 URL、日期和职位名称。不来自 `cards.json` 的 URL（Indeed、公司官网）必须先过 `verify`，出现在 `employer-checks.csv` 里才接受。
- **`config/` 原地不动：** A1–A4 不复制进插件，运行时把 `talent-place/config` 作为附加文件夹读取。这样符合“不留第二份 A2/A3”的规则，同事也能直接编辑 A2/A3。
- **写入前必须确认：** `append` 先 dry-run，显示新增公司摘要，由同事确认后才写入。
- **Indeed：** 沿用 2026-11-02 的做法，用 Claude 的 Indeed 连接器（只覆盖意大利），`cli.js indeed` 计算必填的统计行。连接器不可用时写 `Unavailable`。
- **保存搜索进度（之前写的“不做续跑”是错的）：** PR 4 已实现单次运行内的等待和续跑（`cooldownMinutes`、`checkpoint.jsonl`、`--resume`）。详见阶段 1 第 5 项。`stage` 每次重新生成 `Roles.xlsx` 的现有行为不变，所以 `Roles.xlsx` 只显示最近一次运行；已写入 `Review.xlsx` 的不受影响。
- **ATS 看板不列入：** 最近的 `run.json` 也没有配置 `atsBoards`，这次不增加。
- **搜索范围的例外（deroga）由负责人决定：** 像 11-02 的“只读 7 天内的职位”这种例外，只有同事明确要求才用，并写入 `run-derogations.json`；默认不用。

## 不做的事

- 不做独立 Windows 应用或托管网站
- 不改 `Review.xlsx` 的所有权规则（`append` 的四条安全规则不变）
- 不绕过登录、CAPTCHA 或限流
- 不新增招聘来源，不做自动定时运行
- 不把现有 Excel 流程换成新的职位库
- **交接后的清单（这次不做）：** SQLite 职位库、历史数据导入、两个 Master 共用采集结果、重点公司官网和 ATS 监测（含 Greenhouse `content=true`）、定时采集。依据：积累最多省约 17% 的请求（Accessory 09-22 的理论上限；Strategic 09-24 为 0），两个 Master 读过的描述只重合 2 条；174 家公司的历史链接中只有 2 家在 Greenhouse/Lever/Ashby 上，而且这些链接多为 LinkedIn，真实覆盖率要逐家核实
- **绝对不能发生：** 用编造的 URL 写入 `Review.xlsx`；覆盖同事写的内容；把部分覆盖的运行说成“完整”；让 AI 替主任确认 A2 或编造 A3 里的学生数据

## 阶段 0：Windows 实测（2–3 天，决定走哪条路）

需要：一台同事的 Windows 电脑、Team 方案（至少 2 席，每席每月 $20–25）。**只用测试文件夹和 `Review.xlsx` 的副本。**

| # | 测什么 | 通过标准 |
|---|---|---|
| 1 | 上传插件（`.zip`），在 Cowork 里加载 skill | 能运行 |
| 2 | 沙盒环境：`uname`、`node`、`python3`、`openpyxl` | 都可用，或可以从 PyPI 安装 / 随插件打包 |
| 3 | 联网：LinkedIn guest 搜索和 `jobPosting`、一个雇主页面 | 返回真实内容。Team Owner 可能要先配置允许的域名 |
| 4 | 同时附加 `talent-place/config` 和 OneDrive 里的 Master 测试文件夹 | 都能读写 |
| 5 | 在挂载的 OneDrive 文件夹里写文件 | `os.replace` 成功、同步上云、Excel 能打开；文件被 Excel 打开时和“仅在线”时，guard 能拒绝而不是崩溃 |
| 6 | 跑一次完整搜索（读约 60 条描述） | **一条命令能否连续跑 2–3 小时**（沙盒超时、电脑休眠、中断后 `--resume`）；额度消耗；`health.events429` 和 `cooldowns`，这是等待机制第一次碰到真实的 LinkedIn 限流 |
| 7 | Team 账号里的 Indeed 连接器 | 可用，或确认为 `Unavailable` |

**判定：**
- 第 2、3、5 项不通过 → 把这些项换到 Code 标签页（装 Node、Python）重测；通过就走 Code 标签页
- 两条路都不通 → 停下来告诉 Yuwei，不继续开发
- **第 6 项额度不够：** 把实测数字交给 Yuwei 选：升级为 Premium 席位（每席每月 $100–125）或开启按 API 价格计费的超额用量；降低 `topK` 是最后手段，而且每次运行都要说明这个覆盖缺口
- **第 6 项长命令被中断：** 沙盒或休眠会打断命令时，`--resume` 就成了日常操作，skill 要带同事接着跑。如果连续跑不了也续不上，就按第 2、3、5 项的方式换到 Code 标签页重测
- **第 6 项频繁限流：** 如果等待之后仍然跑不完，部分运行就会成为常态。把实测数字交给 Yuwei，并在交接文档里写明预期，不要假装这是偶发情况

## 阶段 1：引擎改动（约 1 周）

**0. 已完成**：PR 3（EU 修复、每个 A2 领域轮流查询）和 PR 4（等待、续跑、`read`、`recencyDays`、Strategic 精简为 20 个关键词）都已合并。

**1. Windows / 沙盒兼容**：`engine/python/synced_fs.py`、`sync_export.py`
- `is_dataless()`（第 91 行）和 `describe()`（第 235 行）直接读 `st.st_blocks`，Windows 上没有这个字段，会报错。改成按平台判断；Windows 上用文件属性识别“仅在线”文件。
- `cmd_doctor`（第 817 行起）判断 OneDrive 的检查依赖 macOS 的 `xattr`。按平台改写，并修掉已知的误报（见记忆 `doctor-mount-check-false-failure`）。判断不了时报告“无法确认”，不算失败。

**2. 读取描述**：主体已由 PR 4 完成（`cli.js read`、`engine/src/read-postings.ts`）。剩下：
- 修 `read` 把空页面算成“已读”、410 每次重新请求的问题（已列入实测工具计划的 Task 2）。
- 跨次运行的缓存：`descriptions.json` 现在按运行目录保存，换一个目录就会重读。改成 Master 级的 `_machine/descriptions/`。
- 未读的进“未解决”，之后可从雇主页面读（A1 允许）。

**3. `sync_export.py build-tsv`（新增子命令，解决 YUW-84 的其余部分）**
- 移植 `2026-09-22-accessory-design-ED14` 运行目录里的 `build-tsv.py`，但复用 `A4_COLUMNS`、`MULTI_VALUE_SPEC`、`_role_values`、`norm_company`，不再自己实现。
- 输入：`cards.json`、`employer-checks.csv`、`verdicts.json`。判断的字段形状以 `2026-09-24` 和 `2026-11-02` 的 `verdicts.json` 为参考。
- URL、职位名、发布日期**从卡片数据取**。其他 URL 必须出现在 `employer-checks.csv` 或卡片的 `alternateUrls` 里。引用不存在的卡片 id 时拒绝。
- 按公司聚合成 22 列 TSV，并处理值里的 `|`（2026-09-24 那次 `roles_out` 多算 1 的原因）。
- 只有 `pertinente` 和 `adiacente` 进 TSV；其余写入 `exclusions` 或 `unresolved.json`。

**4. 一个流程入口**（如 `engine/python/job_run.py`）
- `prepare --master <名称>`：`doctor` → `export-history` → `discover` → `read`，输出待判断的职位和覆盖情况（每个 A2 领域的卡片数、每个来源的状态）。
- `publish --run <目录>`：`admit` → `build-tsv` → `stage` → 检查 `evidence_join` 和 `roles_out` → `append --dry-run`，停下等确认；确认后再 `append`。
- **防止目录打错：** `--master` 只能是 `config/` 下已有的文件夹，目标文件夹不存在时拒绝，不自动创建（目前打错 `--dir` 会静默新建）。
- **不一致就停：** A2 和 A3 的 `master_id` 不一致就停（A1 规定）。
- **run.json 由代码组装，不靠 AI 临场判断：** 20 个词 × 2 个实习词 × 3 个地点是 120 次，AI 按 A1 把 `tirocinio` 加回来就是 180 次，所以 `prepare` 直接从 A2 的“Termini di ricerca”和 A3 生成，并原样复制 `falseFriends`。不新增配置文件。实习词列表怎么定、次要词何时运行，见“需要确认”。
- **`recencyDays` 自动计算：** 取“距上次成功覆盖的天数 + 重叠几天”，从未跑过就不设。固定写 7 会在隔了几周时静默漏掉职位，也不符合 A1（搜索不自动限于最新发布的职位）。窗口写进报告。
- **长时间运行：** `prepare` 用 `--resume` 接上未完成的运行目录。Windows 上防止休眠的办法按阶段 0 第 6 项的结果定（`caffeinate` 只有 Mac 才有）。
- 异常时输出**原因代码**并停止，意大利语说明由 skill 负责。
- 运行目录放在 `_machine/runs/<日期>-<master>/`，与现有约定一致。

**5. 持续积累的轻量版**（每个 Master 一份状态，放在 `_machine/`，通过 OneDrive 在同事之间共享；用现有 `synced_fs.write_atomically` 写入）
- **搜索进度：** 单次运行内已由 `checkpoint.jsonl` 完成。还要做的：报告区分“没搜到”和“还没搜”（从 checkpoint 和计划的查询列表算出来）。
- **共享冷却：** `discover` 和 `read` 是两个进程，各算各的。把最近一次 429 的时间写到 Master 级文件，两者启动时都先检查；冷却期内不发请求，直接告诉同事何时可以再试。
- **按产出排序：** 取消。PR 4 的精简关键词已经解决了同一个问题（09-24 回放：20 个词没有丢掉 47 个入选职位中的任何一个，但这些词正是从这次结果里选的）。
- **职位状态：** 记录每个 `sourceJobId` 是已读、已判断还是待重试。读取失败的留到下次；判断结果按 Master、A1–A4 规则版本和描述内容的 hash 复用，任一项变化就重新判断。是否仍开放单独检查。
- **命中率写入 `run-report.json`：** 每次记录缓存命中、搜索请求和读描述请求的数量，交接后才有真实数据判断是否值得扩大。
- **运行锁：** 同一个 Master 同时只能有一人运行。锁文件记录发起人和时间，过期可接管；OneDrive 同步有延迟，所以这只是提示，不是绝对保证。

**测试**（`engine/python/test_sync_export.py` 和新的 smoke test，无需联网）
- 编造的 URL、不存在的卡片 id 被拒绝
- 标题含 `|` 时计数正确
- 用历史 verdicts 做的 fixture，`build-tsv` 的输出能通过 `stage`（YUW-84 提出的测试）
- 模拟没有 `st_blocks` 的 `stat` 结果时不崩溃
- `job_run` 在 `evidence_join` 不满、Master 不存在时停止
- 描述读取：命中缓存时不发请求；429 时停止并保留已读内容
- 搜索进度：中断后从未完成的查询继续；冷却期内不发请求；报告区分“没搜到”和“还没搜”
- 判断复用：描述或规则版本变化时必须重新判断；一个 Master 的判断不会用到另一个 Master

新增 GitHub Actions `windows-latest` 跑 Python 测试，这是 Yuwei 没有 Windows 时唯一的持续验证手段。

## 阶段 2：插件（约 1 周）

```
plugin/talent-placement/
  .claude-plugin/plugin.json
  skills/cerca-stage/SKILL.md      # 主流程
  skills/diagnostica/SKILL.md      # 出问题时：读运行记录，用白话解释，生成可转交的报告
  skills/nuova-edizione/SKILL.md   # 换届：建文件夹、init-review、color、更新 A3
  skills/nuovo-master/SKILL.md     # 新 Master：引导起草 A2/A3
  engine/                          # 构建产物：lib/、python/、data/
```

**`cerca-stage`：**
1. 确认 Master，确认已附加 `config` 和 Master 文件夹。
2. 组装 `run.json`，运行 `prepare`，先用白话汇报覆盖情况。
3. 用 Indeed 连接器搜索，并用 `verify` 检查要用的雇主页面。
4. 按 A1/A2 判断每条职位，写入 `verdicts.json` 和 `declared.json`。
5. 运行 `publish`，停在 dry-run，用意大利语显示摘要。
6. 把 `similar_name` 问题逐条问同事（“PwC Italy e PwC sono la stessa azienda?”），答案写入 `company-aliases.csv`。
7. 同事确认后写入。按 A4 写 `report.md`：新增了什么、看哪个文件、**哪些领域没覆盖、什么时候该再跑一次**。

**写进 skill 的规则：**
- `CLAUDE.md` 的 “Rules for whoever is driving a run”（`CLAUDE.md` 同时保留）
- 限流规则：等待交给引擎的 `cooldownMinutes`，AI 和同事都不手动重试；等待用完仍未跑完时，部分结果按上面的决定处理（见记忆 `linkedin-guest-rate-limit-2026-11-02`）
- 不主动读 `history.csv` 或 `Review.xlsx` 的联系人列（见下方隐私说明）

**`nuovo-master`：**
- 用问答引导同事，把主任和教学团队提供的材料整理成 A2 草稿，结构参照现有 A2，但**内容绝不从其他 Master 借用**（A1 规定）。
- 每个领域默认标为 `Da confermare`，审阅人和日期留空，A3 未知项写 `null`（README 规定）。
- 生成一致的 `master_id` 和文件夹名，确认后再运行 `init-review` 和 `color`。
- 明确告诉同事：主任确认 A2 之前，匹配结论只算 `ipotesi operativa`。

**分发：** Team 方案里“发布到组织”，设为默认安装。Owner 必须由留下来的人担任。

新增 `engine/scripts/build-plugin` 打包脚本（`npm run build` → 复制 → 生成 zip）。

## 阶段 3：交接（最后 1 周）

- **陪跑 2 次：** 第 1 次同事操作、Yuwei 在旁边；第 2 次同事独立完成，Yuwei 只事后检查。第 2 次通过才算完成。**如果新 Master 的材料已经到位**，再用 `nuovo-master` 实际走一遍。
- **意大利语操作指南：** 更新 `jobSearch_outPut/README.md`（不在 git 里，要手动检查）。内容：怎么开始、常见提示和处理方法、部分覆盖时怎么办、哪些问题该找谁。
- **交接清单：** Team Owner 和账单负责人；插件 zip 和源码位置；A2/A3 负责人（按 README 的维护表）；确认 `CV Book/Yuwei/` 下的文件在 Yuwei 账号停用后仍可访问，否则提前移到团队目录。
- **文档：** 更新 `CLAUDE.md` 和 `README.md`（新命令、插件、运行方式）。
- **Linear：** 只在 Yuwei 点名同意后才新建、评论或关闭工单。

**工期调整：** 加入持续积累的轻量版后，默认把 `nuova-edizione` 改成人工清单，以抵消多出的 2–3 天。

**如果时间还不够，按这个顺序砍：** (1) 描述读取的并发（只保留串行加缓存）；(2) Windows CI；(3) 判断复用（保留进度和描述缓存）；(4) `nuovo-master` 只保留“生成空白 A2/A3 和文件夹”，内容由人工填写。**不砍：** Windows 实测、搜索进度和冷却、`build-tsv` 的 URL 校验、写入前确认、陪跑。

## 坦白说的局限

- **时间很紧：** 各阶段加起来约 3.5–4 周，几乎没有余量。Team 方案审批一拖，就得按上面的顺序砍。
- **持续积累不会让 LinkedIn 请求大幅下降：** 上限约 17%，主要价值是保留进度和少花 AI 额度。
- **一次搜索要跑很久：** 按每轮约 20 个请求、等 20 分钟估算，120 次搜索约 2 小时，再读 60 条描述约 1 小时（估算，未实测）。如果等待之后仍然跑不完，只能把官网来源提前。
- **等待机制未经实战：** PR 4 的 cooldown 只用本地服务器测过，还没碰到过真实的 LinkedIn 限流。
- **分发：** 按人分享的插件只在分享者继续分享时有效，所以交接时要发布到组织。文档没写明发布者账号停用后会怎样，交接前要确认。
- **LinkedIn：** guest 接口不是官方接口。它变了之后插件无法自我修复，需要找懂技术的人。`diagnostica` 只能说清楚坏在哪里。
- **AI 判断：** 质量没有自动评估，靠同事在 `Review.xlsx` 里把关。
- **Claude 产品：** 产品本身会变，插件在新版本下的行为不由我们控制。

## 需要确认（不阻塞方案审批）

- Team 方案的 Owner 由谁担任，预算何时能批。**这是阶段 0 的前置条件。**
- **隐私：** 负责隐私的同事确认机构账号可以使用。现有两份 A3 没有个人学生数据；`Review.xlsx` 里有联系人和备注，由脚本读取，skill 也规定不主动读这些列，但 `append` 摘要会显示公司名。如果隐私方面不同意使用 Claude，这个方案就走不通，要尽早问。
- 能否找到一位兜底的技术联系人（IT 或外部），哪怕只是出问题时才联系。
- 第一个新 Master 是哪个，材料何时能到。
- **Accessory 的关键词（Yuwei / Talent Placement 决定）：** 还没精简，09-22 发了 342 个请求，按每轮约 20 个算要 17 轮左右，超过默认 12 次等待上限。要么精简，要么调高上限。
- **实习词和次要词（Yuwei / Talent Placement 决定）：** `tirocinio` 要不要进默认查询（09-24 回放：同时去掉会丢 2/47）；次要词多久跑一次，A1 写着“不要只跑列表前面的词”，目前没有机制会跑它们。

## 验证

1. `cd engine && npm test`（`employer-smoke` 需要联网）
2. GitHub Actions `windows-latest` 通过 Python 测试
3. 在测试文件夹上端到端跑一次：`prepare` → 判断 → `publish` dry-run → `append`；手工核对 TSV 行数、URL 与 `cards.json`、`evidence_join`，并和 `_machine/backups/` 比较，确认原有行未被改动
4. **故障演练：** Excel 打开文件时、发生 429 时、`master_id` 不一致时、Master 名称打错时，都要停下并给出能看懂的提示
5. **部分覆盖演练：** 模拟限流用完等待次数，确认已核实的职位写入，`report.md` 列出未覆盖领域；`--resume` 从未完成的查询继续，不重读已读描述，也不产生重复行
6. 阶段 3 的第 2 次陪跑：同事独立完成一次真实搜索
