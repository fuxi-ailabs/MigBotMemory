# MigBotMemory 架构文档

## 核心问题

代码迁移中，同一个编译错误反复出现，每次都要从零推理修复方案。
MigBotMemory 记录 feature 的完整迁移周期（a2h 5-stage），从中提取编译错误模式，让后续迁移能复用已有经验。

---

## 记忆单元

一个 feature 的完整迁移周期，对齐 a2h 5-stage pipeline：

```
a2h-spec(功能定义) → a2h-plan(设计) → a2h-execute(实现) → a2h-verify(测试) → a2h-retrospect(回顾)
```

---

## 三层压缩

### 1. 工具压缩：tool call results → 结构化数据

**来源**：PostToolUse(*) hook 捕获所有 tool call 的结果（客观数据，hook 保证执行）

| tool call | 提取什么 | 怎么提取 |
|---|---|---|
| Bash(hvigorw assembleHap) | 编译错误列表 | regex 提取 ERROR 行 → `{file, line, message}` |
| Bash(hvigorw) 返回码 | build 是否通过 | returncode=0 → compile_pass=true |
| Edit / Write | 改了什么文件 | 记录 `{file_path, change_type}` |
| Skill(a2h-*) | 当前 pipeline phase | phase_map 映射 skill → phase |

**不需要 LLM 介入**：编译错误从 build output 直接提取，build 是否通过从返回码判断。

### 2. 会话压缩：events → TaskRecord + 累引 + error_index

**Stop hook 保证执行**，自动完成三步：

- **切分**：按 Skill 调用的 phase_map 把 events 分到 spec/plan/execute/verify/retrospect 阶段
- **摘要**：合并同 task_id 的碎片 → 完整 TaskRecord
  - key_errors：从 Bash build output 自动提取（工具压缩的结果）
  - quality：从 Bash 返回码自动判断
  - phase summaries：skill 写入（主观内容，大概率写入）
- **索引**：
  - `index.json`：task_id → {feature, outcome, quality}
  - `error_index.json`：error keyword → [task_ids]（编译错误模式缓存的核心）
  - `briefing.md`：渐进式披露注入上下文

### 3. 任务压缩：TaskRecord 保留完整信息，按需还原

- briefing 注入 ~200 tokens（phase summaries + key errors/fixes）
- `mbm lookup` 还原完整 JSON（无损）
- `mbm search-error "ValuesBucket"` → 从 error_index 查到哪些 task 遇过这个错

**三层链条**：

```
tool call results（客观，hook自动）
  → 工具压缩：提取编译错误/文件变更/phase
  → 会话压缩：合成 TaskRecord + error_index + briefing
  → 任务压缩：briefing注入 + lookup还原
```

---

## 数据模型

### TaskRecord

```json
{
  "id": "login-page",
  "domain": "android-to-harmonyos",
  "feature": "LoginActivity",
  "source": "LoginActivity.java",
  "target": "LoginPage.ets",

  "spec_summary": "迁移登录页面，保留表单验证逻辑",
  "plan_summary": "用 Column + TextInput，验证逻辑提取为独立函数",
  "execute_summary": "XML布局转Column，validation抽为pure function",
  "verify_summary": "编译通过，视觉匹配95%",
  "retrospect_summary": "5 files committed，经验已记录",

  "key_decisions": ["使用Column而非LinearLayout"],
  "key_errors": ["arkts-identifiers-as-prop-names in ValuesBucket"],
  "key_fixes": ["bracket assignment: bucket['key'] = value"],
  "outcome": "success",
  "quality": {"compile_pass": true, "lint_errors": 0, "verify_pass": true}
}
```

- **phase summaries**（主观）：由 skill 在执行过程中写入，大概率执行
- **key_errors / key_fixes / quality**（客观）：由 Stop hook 从 Bash 输出自动提取，保证执行
- **完整 JSON**：`mbm lookup` 无损还原

### error_index

```json
{
  "ValuesBucket computed property": ["login-page", "settings-page"],
  "EventData double cast": ["login-page"],
  "RecyclerView adapter incompatible": ["chat-page"]
}
```

从 TaskRecord 的 key_errors 自动提取。`mbm search-error "ValuesBucket"` → 查到相关迁移记录 → 看它们怎么修的。

---

## 存储结构

```
.mbm/
├── config.json                  # domain, budget, phase_map
├── raw/
│   └── events.jsonl              # tool call 事件（工具压缩的输入）
├── tasks/
│   ├── index.json                # task_id → outcome/quality（会话压缩：索引）
│   ├── error_index.json          # error keyword → [task_ids]（错误模式缓存）
│   ├── reference/                # outcome=success（始终注入完整摘要）
│   │   └── login-page.json
│   └── trial/                    # outcome=partial/failed（只注入索引行）
│       └── chat-page.json
└── context/
    └── briefing.md               # 渐进式披露注入上下文
```

---

## Hooks

```json
{
  "hooks": {
    "PostToolUse": [
      {"type": "command", "command": ".mbm/hooks/on_tool_use.sh", "timeout": 3}
    ],
    "Stop": [
      {"type": "command", "command": ".mbm/hooks/on_stop.sh", "timeout": 5}
    ]
  }
}
```

| Hook | 触发时机 | 做什么 |
|---|---|---|
| PostToolUse(*) | 任何 tool call 后 | 捕捉 tool call 结果 → 写入 events.jsonl |
| Stop | 每轮 Claude 回复后 | 处理 events → 合成 TaskRecord + error_index + briefing |

**PostToolUse 捕捉所有 tool call**（不只 Skill），因为编译错误在 Bash 输出里，文件变更在 Edit 里。

---

## 渐进式披露

| 类别 | 注入内容 | token 预算 |
|---|---|---|
| reference (success) | phase summaries + key errors/fixes | ≤500 |
| trial (partial/failed) | 索引表 1行/条 | ≤300 |
| 完整记录 | 全部 JSON | mbm lookup 按需 |

总预算 ≤4000 tokens。

---

## 数据来源分工

| 数据类型 | 来源 | 保证级别 |
|---|---|---|
| 编译错误列表 | Bash build output → regex 提取 | **保证**（hook 自动） |
| build 是否通过 | Bash 返回码 | **保证**（hook 自动） |
| 文件变更记录 | Edit/Write tool call | **保证**（hook 自动） |
| 当前 pipeline phase | Skill 调用 → phase_map | **保证**（hook 自动） |
| phase summaries | skill 在工作流中 Write | **大概率**（skill 自然步骤） |
| key decisions | retrospect skill 写入 | **大概率** |

---

## CLI 命令（只读 + 注入，不写入）

```bash
mbm init --domain <domain>          # 初始化 .mbm/
mbm briefing [--write]              # 渐进式披露（Stop hook 调）
mbm lookup <task_id>                # 查询完整生命周期（无损还原）
mbm search-error <keyword>          # 从 error_index 查编译错误模式
mbm search <feature>                # 搜索相似迁移任务
mbm list [--outcome --domain]       # 列出任务
```

写入由 hook（客观数据）和 skill（主观数据）完成，不需要 CLI。

---

## 与 a2h pipeline 的对齐

Phase 映射：

```python
"a2h-spec":       Phase.spec
"a2h-plan":       Phase.plan
"a2h-execute":    Phase.execute
"a2h-verify":     Phase.verify
"a2h-retrospect": Phase.retrospect
```

集成方式：各 a2h skill 在 SKILL.md 中加一步"往 .mbm/ 写 phase summary"，使用 Claude Code 原生 Write 工具，不需要调 mbm CLI。