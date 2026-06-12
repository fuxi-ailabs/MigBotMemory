# MigBotMemory 架构文档

## 问题定义

代码迁移工具面临的核心挑战不是"记住某个编译错误怎么修"，而是**记住一个 feature 的完整迁移周期**——从功能定义到设计、实现、测试、提交的全流程经验。

每次迁移一个新 feature 时，工具应该能回忆：
- 类似 feature 之前是怎么迁移的（设计决策、实现路径）
- 遇到了什么问题、怎么解决的（错误和修复）
- 最终结果如何（编译通过了吗？测试通过了？）
- 哪些决策是关键的（避免重复踩坑）

---

## 核心概念

### 记忆单元 = Feature 完整迁移周期

```
task(功能定义) → plan(设计) → execute(实现) → verify(测试) → commit(提交)
```

每个阶段产生的事件（skill 调用、工具输出、编译结果）构成完整的生命周期记录。

### 三层压缩

| 层 | 压缩对象 | 压缩方式 | 存储 |
|---|---|---|---|
| **工具压缩** | 单次工具/skill 的输出 | 结构化编码（build输出→错误列表） | `raw/events.jsonl` |
| **会话压缩** | 一轮 session 的所有事件 | 切分(按phase) + 摘要(每phase~50tokens) + 索引(task_id→outcome) | `tasks/index.json` |
| **任务压缩** | 完整迁移生命周期 | 5个phase summary + key artifacts (~200tokens) | `tasks/{reference,trial}/<id>.json` |

**会话压缩 = 切分 + 摘要 + 索引**：
- 切分：按 skill 调用切分 session 为 task/plan/execute/verify/commit 阶段
- 摘要：每个阶段提炼为 ~50 token 的总结
- 索引：task_id → {feature, outcome, quality} 映射表，用于快速检索

**任务压缩 = 完整生命周期压缩**：
- 原始过程可能 5000+ tokens（多轮编译修复、大量代码变更）
- 压缩后 ~200 tokens（5个phase summary + key decisions/errors/fixes）
- 完整信息保留在 JSON 文件中，`mbm lookup` 按需还原（**无损**）

### 任务级 Hook = 监听 Skill 调用

```
PostToolUse(Skill) → 捕获 skill 调用 → 记录为 lifecycle event
Stop               → 处理 events → 生成 briefing
```

Hook 触发点是 **skill 被调用**（任务级），不是 session 开始/结束（session级）。

`config.phase_map` 定义 skill → lifecycle phase 的映射：
```python
"a2h-spec":     Phase.task     # 功能定义
"a2h-plan":     Phase.plan     # 设计
"a2h-execute":  Phase.execute  # 实现
"a2h-verify":   Phase.verify   # 测试
"commit":       Phase.commit   # 提交
```

### 质量分类（替代置信度）

```
reference — outcome=success, compile_pass=true, verify_pass=true, lint_errors=0
           → 始终注入完整生命周期摘要（其他迁移可以学习）

trial     — outcome=partial/failed
           → 只注入索引行（feature + outcome + what went wrong）
           → 完整信息通过 mbm lookup 按需获取
```

**不用置信度数字**：质量由实际结果衡量（编译、lint、测试），不是出现频率。

---

## 数据模型

### TaskRecord（记忆单元）

```json
{
  "id": "login-page-migration",
  "domain": "android-to-harmonyos",
  "feature": "LoginActivity",
  "source": "LoginActivity.java",
  "target": "LoginPage.ets",

  "task_summary": "迁移登录页面，保留表单验证逻辑",
  "plan_summary": "用 Column + TextInput，验证逻辑提取为独立函数",
  "execute_summary": "XML布局转Column，validation抽为pure function",
  "verify_summary": "编译通过，视觉匹配95%",
  "commit_summary": "5 files committed",

  "key_decisions": ["使用Column而非LinearLayout", "验证逻辑抽为pure function"],
  "key_errors": ["ValuesBucket computed property names被禁止"],
  "key_fixes": ["bracket assignment: bucket['key'] = value"],
  "outcome": "success",
  "quality": {"compile_pass": true, "lint_errors": 0, "verify_pass": true}
}
```

三层信息密度：
- **phase summaries** (~50 tokens each) → 注入到 prompt（会话级）
- **key artifacts** (decisions/errors/fixes) → 注入到 prompt（任务级）
- **完整 JSON 文件** → `mbm lookup` 按需还原（无损）

### SkillEvent（工具压缩层）

```json
{
  "timestamp": "2026-06-12T08:00:00Z",
  "skill_name": "a2h-execute",
  "skill_args": "login-page",
  "phase": "execute",
  "output_summary": "3 files converted, 2 compile errors fixed"
}
```

---

## 存储结构

```
.mbm/
├── config.json              # domain, budget, phase_map
├── raw/
│   ├── events.jsonl          # skill调用事件（工具压缩层）
│   └── checkpoint.json       # Stop hook产生的session元数据
├── tasks/
│   ├── index.json            # task_id → {feature, outcome, quality}（会话压缩：索引层）
│   ├── reference/            # 成功迁移记录（始终注入）
│   │   └── login-page.json
│   └── trial/                # 部分/失败记录（按需 lookup）
│       └── chat-page.json
└── context/
    └── briefing.md           # 渐进式披露注入上下文
```

原子写入：所有文件写入使用 `.tmp → rename` 策略。

---

## Hooks

```json
{
  "hooks": {
    "PostToolUse": [
      {"type": "command", "command": ".mbm/hooks/on_skill_use.sh", "matcher": "Skill", "timeout": 3}
    ],
    "Stop": [
      {"type": "command", "command": ".mbm/hooks/on_stop.sh", "timeout": 5}
    ]
  }
}
```

| Hook | 触发时机 | 功能 |
|---|---|---|
| PostToolUse(Skill) | 任何 skill 被调用时 | 记录 skill 调用为 lifecycle event |
| Stop | 每轮 Claude 回复后 | 处理 events → checkpoint → 更新 briefing |

**不使用 SessionStart/SessionEnd**：session 级 hook 对任务生命周期没有意义。任务发生在 skill 调用时，不是 session 边界。

---

## Briefing 注入示例

```markdown
## Migration Memory (domain: android-to-harmonyos)

### Reference Migrations (success — learn from these)
**login-page-migration** — LoginActivity: LoginActivity.java → LoginPage.ets
  - Task: 迁移登录页面，保留表单验证逻辑
  - Plan: 用 Column + TextInput，验证逻辑提取为独立函数
  - Exec: XML布局转Column，validation抽为pure function
  - Verify: 编译通过，视觉匹配95%
  - Decisions: 使用Column而非LinearLayout; 验证逻辑抽为pure function
  - Fixes: bracket assignment: bucket['key'] = value

### Trial Migrations (partial/failed — what went wrong)
| ID | Feature | Outcome | What went wrong |
|---|---|---|---|
| chat-page | ChatActivity | partial | RecyclerView adapter incompatible; 15 compile errors initially |

> Budget: ~500/4000 | ref=1 trial=1
> Use `mbm lookup <task_id>` for full lifecycle details.
```

---

## CLI 命令

```bash
mbm init --domain <domain>         # 初始化
mbm record --id <id> --feature ... # 记录完整迁移任务
mbm event --skill-name <name>      # 记录 skill 调用（PostToolUse hook用）
mbm briefing [--write]             # 生成/写入 briefing
mbm lookup <task_id>               # 查询完整生命周期（无损还原）
mbm search <feature>               # 搜索相似迁移任务
mbm checkpoint                     # Stop hook：处理 events
mbm archive                        # 压缩清理 raw events
mbm list [--outcome --domain]      # 列出任务
```

---

## 渐进式披露策略

| 类别 | 注入内容 | token预算 | 何时注入 |
|---|---|---|---|
| reference (success) | 5个phase summary + key decisions/fixes | ≤500 | 始终 |
| trial (partial/failed) | 索引表：1行/条 | ≤300 | 始终（仅索引） |
| 完整记录 | 全部JSON | — | `mbm lookup` 按需 |

总预算 ≤4000 tokens。超预算裁剪 trial→reference摘要精简，永不完全删除。

---

## 与旧设计的对比

| 维度 | 旧设计 (Pattern-based) | 新设计 (Task-based) |
|---|---|---|
| 记忆单元 | 编译错误 pattern | Feature 完整迁移周期 |
| 核心关注 | 错误怎么修 | 迁移怎么做 |
| 分类依据 | 置信度 (0.5→0.7→1.0) | 任务质量 (success/partial/failed) |
| 压缩层次 | title→facts→fix (选择显示) | 工具→会话→任务 (真正的压缩) |
| Hook 级别 | Session (SessionStart/End) | Skill调用 (PostToolUse) |
| 无损还原 | 没有真正的压缩机制 | phase summaries + key artifacts + 完整JSON |
| 价值 | 减少重复修同一个错 | 减少重复迁移同类feature的弯路 |