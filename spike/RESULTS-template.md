# 实测结果（Yuwei 汇总用）

同事填意大利语的 `FOGLIO-risultati.md`，并发回 `probe-report.jsonl`。汇总到这里。

**`INCONCLUSIVE` 不等于“不通过”：** T3 是 LinkedIn 限流，等 20 分钟后重测。T3 的 `allowlist_blocked` 先找 Team Owner 配置域名，再判定。

日期： 电脑 / Windows 版本： 账号方案： 网络（公司网、热点等）：

| # | 测什么 | Cowork | Code 标签页 | 备注 |
|---|---|---|---|---|
| T1 | 插件能上传，skill 能运行 | | | |
| T2 | 运行环境（`env`） | | | |
| T3 | 联网（`net`） | | | |
| T4 | 同时附加两个文件夹（`fs`） | | | |
| T5-write | 在 OneDrive 文件夹里写文件（`fs`） | | | |
| T5-人工 | `probe-roundtrip.xlsx` 能在 Excel 打开；`probe-marker-*.txt` 出现在 OneDrive 网页上 | | | |
| T5-normal | 正常状态下允许写入 | | | |
| T5-excel-open | Excel 打开时拒绝写入 | | | |
| T5-online-only | “仅在线”时拒绝写入 | | | |
| T6-timer | 不联网的 3 小时计时器能否跑完 | | | |
| T6 | 完整搜索（见下） | | | |
| T7 | Indeed 连接器（工具名，或 `Unavailable`） | | | |

## T6 完整搜索

- `discover`：开始 / 结束时间
- `read`：开始 / 结束时间，`empty` 数量
- `T6-*` 的 `elapsed_seconds` 和 `max_gap_seconds`（间隔很大说明电脑休眠过；有 `-start` 没有结束行说明被杀掉了）
- 是否被打断（shell 超时、沙盒、电脑休眠），以及 `--resume` 次数
- 判断了多少条职位
- 用量：开始前 / 结束后
- `run-report.json` 的 `sources`：请求数、429 次数、`cooldowns`、`events429`
- 是否跑完所有查询；没跑完时，哪些 A2 领域没有覆盖

## 判定（抄自方案阶段 0）

- 第 2、3、5 项不通过 → 把这些项换到 Code 标签页（装 Node、Python）重测；通过就走 Code 标签页
- 两条路都不通 → 停下来告诉 Yuwei，不继续开发
- **第 6 项额度不够：** 把实测数字交给 Yuwei 选：升级为 Premium 席位（每席每月 $100–125）或开启按 API 价格计费的超额用量；降低 `topK` 是最后手段，而且每次运行都要说明这个覆盖缺口
- **第 6 项长命令被中断：** 沙盒或休眠会打断命令时，`--resume` 就成了日常操作，skill 要带同事接着跑。如果连续跑不了也续不上，就按第 2、3、5 项的方式换到 Code 标签页重测
- **第 6 项频繁限流：** 如果等待之后仍然跑不完，部分运行就会成为常态。把实测数字交给 Yuwei，并在交接文档里写明预期，不要假装这是偶发情况

## 结论

走 Cowork / 走 Code 标签页 / 都不通： 决定人和日期：
