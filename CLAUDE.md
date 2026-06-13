# MigBotMemory Project

## 当前状态

架构文档已定稿（ARCHITECTURE.md），代码还是旧版本——需要重写以对齐最终架构。

## 最终架构决策（历经多轮讨论确定）

1. **记忆单元 = feature 完整迁移周期**，对齐 a2h 5-stage pipeline
   - Phase: spec → plan → execute → verify → retrospect
   - 不是"编译错误 pattern"，也不是"session 事件"

2. **三层压缩（链条必须实线）**
   - **工具压缩**：PostToolUse(*) 捕获所有 tool call results → 从 Bash build output regex 提取编译错误 → 从 Edit 记录文件变更 → 从 Skill 调用标记 phase。客观数据，hook 保证执行。
   - **会话压缩**：Stop hook 自动处理 events → 合成 TaskRecord 骨架 + error_index.json + briefing.md。切分+摘要+索引，保证执行。
   - **任务压缩**：TaskRecord 保留完整 JSON → briefing 注入 ~200 tokens → mbm lookup 无损还原。

3. **数据来源分工**
   - 客观（hook 自动提取）：编译错误列表、build 是否通过、文件变更、pipeline phase
   - 主观（skill 大概率写入）：phase summaries、key decisions
   - **不追求 100% 保证写入，接受大概率 + 高质量 + 可复用**

4. **Hooks**
   - PostToolUse(*)：捕捉所有 tool call，不只是 Skill。编译错误在 Bash 输出里。
   - Stop：处理 events → 合成 TaskRecord + error_index + briefing

5. **CLI 只读不写**
   - briefing、lookup、search-error、search、list
   - 写入由 hook（客观）和 skill Write 工具（主观）完成
   - 去掉 mbm record、mbm phase、mbm event 这些写入 CLI

6. **质量分类替代置信度**
   - reference（success + compile_pass + verify_pass）→ 始终注入完整摘要
   - trial（partial/failed）→ 只注入索引行

7. **编译错误模式缓存 = error_index**
   - 从 TaskRecord.key_errors 自动提取
   - error keyword → [task_ids]
   - mbm search-error "ValuesBucket" → 查到哪些迁移遇到过这个错 → 看怎么修的

8. **Phase 对齐 a2h 5-stage**
   ```python
   "a2h-spec":       Phase.spec
   "a2h-plan":       Phase.plan
   "a2h-execute":    Phase.execute
   "a2h-verify":     Phase.verify
   "a2h-retrospect": Phase.retrospect
   ```
   没有 commit phase（提交在各阶段内部发生）

## 需要做的代码修改

1. **models.py**: Phase 枚举改为 spec/plan/execute/verify/retrospect（去掉 task/commit）
2. **config.py**: phase_map 对齐 a2h 5-stage skill 名
3. **store.py**: 加 error_index 生成逻辑，从 TaskRecord.key_errors 自动提取；去掉 SkillEvent（改为通用 tool call event）
4. **inject.py**: briefing 从 TaskRecord + error_index 生成
5. **cli.py**: 去掉 record/phase/event 写入命令；加 search-error 命令；只保留 init/briefing/lookup/search/search-error/list
6. **hooks**: PostToolUse 改为捕捉所有 tool call（不只是 Skill）；加 Bash 输出编译错误提取逻辑
7. **on_tool_use.sh**: 捕捉所有 tool call 的 name + input + output；识别 Bash build 命令提取编译错误
8. **on_stop.sh**: 处理 events → 合成 TaskRecord + error_index + briefing

## 参考系统

- **ECAT memory tree**: 分类树 + drill-down 渐进披露 + skill 5步写入协议 + taxonomy keyword 归类
- **claude-mem**: PostToolUse(*) 自动捕捉 + LLM 压缩 + 3层搜索(search→timeline→get_observations)
- **migbot**: a2h 5-stage pipeline + Stop hook checkpoint + a2h-retrospect 第5阶段记录经验

## 项目结构

- `src/mbm/models.py` — TaskRecord, Phase, Outcome, QualityMetrics, ErrorIndex
- `src/mbm/config.py` — MBMConfig with phase_map (a2h skill → phase)
- `src/mbm/store.py` — TaskStore (events, task CRUD, error_index, briefing generation)
- `src/mbm/inject.py` — BriefingGenerator (progressive disclosure, budget trimming)
- `src/mbm/cli.py` — typer CLI (init, briefing, lookup, search, search-error, list)
- `hooks/` — PostToolUse(*) and Stop hook scripts