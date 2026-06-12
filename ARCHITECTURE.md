# MigBotMemory 架构文档

## 为什么需要 MigBotMemory

代码迁移工具（migbot、ECAT、CATAROS）在处理编译错误时面临一个核心问题：**同一个错误反复出现，每次都需要 LLM 从零推理修复方案**。

MigBotMemory 将"错误模式缓存"从具体迁移工具中抽离，形成通用能力：
- **记住**见过什么错误、怎么修的
- **自动应用**高置信度的修复（不用每次问 LLM）
- **按需披露**低置信度的修复指引（保留完整信息但节省 token）
- **跨 session 持久化**（错误模式不会因 session 结束而丢失）

---

## 核心概念

### 三层渐进式披露

错误模式按 confidence 分三层存储，注入 prompt 时按 token 预算逐层披露：

```
┌─────────────────────────────────────────────┐
│ Tier 1 — Deterministic (confidence=1.0)     │
│ 始终注入完整 fix_template                    │
│ ≤500 tokens, auto_apply=true                 │
├─────────────────────────────────────────────┤
│ Tier 2 — Probabilistic (confidence=0.7~0.99)│
│ 签名匹配时注入 facts + fix_template          │
│ ≤1000 tokens                                 │
├─────────────────────────────────────────────┤
│ Tier 3 — Empirical (confidence=0.5~0.69)    │
│ 按需注入完整 example                          │
│ ≤2000 tokens                                 │
├─────────────────────────────────────────────┤
│ 索引层                                        │
│ 始终注入 Tier 2/3 的 id + title + category   │
│ ≤200 tokens                                  │
└─────────────────────────────────────────────┘
总预算 ≤4000 tokens，超预算裁剪 Tier3→2→索引层，永不裁剪 Tier1
```

**灵感来源**：
- migbot 的 4 层设计（去掉 ECAT 特有的 entropy_correlated 层）
- claude-mem 的"默认只注入索引，按需取详情"策略

### 无损压缩

Pattern 保留三层信息密度，不丢弃任何细节：

```
title (~15 token)  ─→ 索引层用
facts (~50 token)  ─→ Tier 2 注入
fix_template (完整) ─→ Tier 1 全量 / Tier 2/3 按需
```

LLM 需要时通过 `mbm lookup <signature>` 获取完整 pattern，不丢失信息。

### 模式生命周期

```
新错误 → Tier 3 Empirical (confidence=0.5)
  │
  ├─ 同 signature + 同 fix → 第 2 次 → Tier 2 Probabilistic (confidence=0.7)
  │     │
  │     ├─ 同 signature + 同 fix → 第 3 次 → Tier 1 Deterministic (confidence=1.0, auto_apply=true)
  │     │
  │     └─ fix 不一致 → 回退 Tier 3 (confidence=0.5)
  │
  └─ fix 不一致 → 留在 Tier 3, 累积更多 examples
```

---

## 数据模型

### Pattern

```json
{
  "id": "arkts-valuesbucket-bracket",
  "signature": "arkts-identifiers-as-prop-names.*ValuesBucket",
  "domain": "android-to-harmonyos",
  "category": "syntax_error",
  "title": "ArkTS computed property names forbidden in ValuesBucket",
  "facts": [
    "ValuesBucket 不允许 computed property names",
    "用 bracket assignment: bucket['key'] = value 代替 {[key]: value}"
  ],
  "fix_template": {
    "strategy": "bracket_assignment",
    "before": "let bucket: ValuesBucket = { [keyName]: value }",
    "after": "let bucket: ValuesBucket = {}\nbucket[keyName] = value",
    "description": "ArkTS禁止computed property names，改为bracket赋值"
  },
  "confidence": 1.0,
  "occurrences": 85,
  "auto_apply": true,
  "created_at": "2026-06-01T10:00:00Z",
  "last_seen_at": "2026-06-12T08:30:00Z"
}
```

### 错误分类

| category | 含义 | 示例 |
|---|---|---|
| `syntax_error` | 语法限制/禁止用法 | ArkTS computed property names |
| `type_mismatch` | 类型不匹配 | EventData double cast |
| `missing_import` | 缺失导入 | @ohos → @kit 替换 |
| `api_incompatibility` | API 不兼容 | Android API → HarmonyOS API |
| `missing_declaration` | 缺失声明/构建函数 | 缺少 build() |
| `duplicate_identifier` | 重复标识符 | @Prop/@Param 冲突 |

### Import/API 替换映射

```json
{
  "old": "@ohos.data.rdb",
  "new": "@kit.ArkData",
  "domain": "android-to-harmonyos",
  "strategy": "import_replacement"
}
```

---

## 存储结构

工作目录 `.mbm/` 位于项目根目录：

```
.mbm/
├── config.json                 # domain, budget 配置
├── patterns/
│   ├── index.json              # 签名 → {tier, id} 映射（快速查找）
│   ├── deterministic.json      # Tier 1 patterns 数组
│   ├── probabilistic.json      # Tier 2 patterns 数组
│   ├── empirical.jsonl         # Tier 3 patterns（append-only）
│   └── mappings.json           # import/API 替换映射
├── sessions/
│   └── latest.json             # 最近 session 状态
└── context/
    └── briefing.md             # SessionStart hook 生成的注入上下文
```

**原子写入**：所有文件写入使用 `.tmp → rename` 策略，防 crash 损坏。

---

## Hooks 驻点

Claude Code hooks 保障 session 生命周期（不依赖 LLM "遵守指令")：

```json
{
  "hooks": {
    "SessionStart": [{"type": "command", "command": ".mbm/hooks/on_session_start.sh"}],
    "Stop": [{"type": "command", "command": ".mbm/hooks/on_stop.sh"}],
    "SessionEnd": [{"type": "command", "command": ".mbm/hooks/on_session_end.sh"}]
  }
}
```

| Hook | 脚本 | 功能 | 耗时 |
|---|---|---|---|
| SessionStart | `on_session_start.sh → mbm briefing --write` | 生成渐进式披露上下文 | <10s |
| Stop | `on_stop.sh → mbm checkpoint` | 持久化 pending patterns | <50ms |
| SessionEnd | `on_session_end.sh → mbm archive` | 压缩 + 清理 empirical | <15s |

---

## Briefing 注入格式

SessionStart hook 生成的 `briefing.md` 示例：

```markdown
## Error Pattern Memory (domain: android-to-harmonyos)

### Tier 1 — Deterministic (always apply)
- **arkts-valuesbucket-bracket** [syntax_error] [auto]: ValuesBucket computed property names → bracket_assignment
  - ValuesBucket 不允许 computed property names
  - 用 bracket assignment: bucket['key'] = value 代替 {[key]: value}
  - Fix: `let bucket = { [keyName]: value }` → `let bucket = {}; bucket[keyName] = value` (strategy: bracket_assignment)

### Import/API Mappings (always apply)
- `@ohos.data.rdb` → `@kit.ArkData`

### Available Patterns (index)
| ID | Category | Title | Tier |
|---|---|---|---|
| arkts-tabbar-fragment | syntax_error | TabBar-Fragment nesting pattern | prob |
| arkts-eventdata-double-cast | type_mismatch | EventData two-step cast | emp |

> Token budget: ~500/4000 | Tier1=1 Tier2=1 Tier3=1
> Use `mbm lookup <signature>` to fetch full pattern details on demand.
```

---

## CLI 命令

```bash
mbm init --domain <domain>        # 初始化 .mbm/ 目录
mbm briefing [--write]            # 生成/写入 briefing
mbm write --signature "..." ...   # 写入新 pattern
mbm promote <pattern_id>          # 提升 pattern tier
mbm lookup <signature>            # 查询 pattern 详情
mbm checkpoint                    # 持久化 session 状态
mbm archive                       # 压缩清理
mbm list [--tier --domain --cat]  # 列出 patterns
```

---

## 部署到迁移工具

三步集成：

1. `mbm init --domain <tool-domain>` 在项目目录初始化
2. 将 hooks.json 内容写入项目 `.claude/settings.json`
3. 在工具的 fix_build_errors 逻辑中调用 `mbm lookup` + `mbm write`

**优雅降级**：如果 `.mbm/` 目录不存在，hooks 脚本静默跳过，不影响原有工具运行。

---

## 与现有系统的对比

| 特性 | migbot (v2) | ECAT | MemoryCore | claude-mem | MigBotMemory |
|---|---|---|---|---|---|
| 层数 | 4 层 | 静态 | 热冷双层 | 3 层搜索 | 3 层 |
| 存储 | JSON + Go 二进制 | Python | SQLite + Vector | SQLite + Chroma | JSON 文件 |
| 依赖 | Go, shell | Python, LLM | SQLite, FAISS/vec | SQLite, Chroma, Bun | Python, typer |
| 渐进式披露 | 有 | 无 | schema投影 | 索引→详情 | 索引→按需 |
| hooks 驱动 | 有 | 无 | 无 | 有(5个) | 有(3个) |
| 通用性 | HarmonyOS 专属 | ECAT 专属 | 通用 | Claude Code 专属 | 通用(domain标签) |
| 复杂度 | 高 | 中 | 高 | 极高 | 低 |