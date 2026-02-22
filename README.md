# LivingMemory_手动记忆注入

LivingMemory 手动记忆注入伴生插件。

在聊天中使用 `/lmadd` 命令，将你想要 AI 永远记住的事情手动写入 LivingMemory 的记忆库。

---

## 为什么需要这个插件

LivingMemory 的自动记忆系统会在对话达到一定轮数后，由后台 LLM 自动总结并存储记忆。但有些事情——比如重要的偏好、关键的约定、不想被遗忘的细节——你可能希望**立刻、精确地**写入记忆库，而不是等待自动总结，也不想依赖 LLM 的理解和概括。

这个插件就是你的"后门"：直接绕过 LLM 总结环节，把你写的原文一字不差地存入记忆。

---

## 使用方法

在聊天中发送：

```
/lmadd <你想记住的内容>
```

**用 `< >` 尖括号包裹记忆内容。**

### 示例

```
/lmadd <Felis Abyssalis喜欢在深夜调试代码>
/lmadd <Felis Abyssalis养了一只叫诺瓦（Noir）>
```

插件会返回确认消息，包含记忆 ID 和重要性。

### 插入后的记忆长什么样

你不需要写那些复杂的 JSON。你只需要写一句话，插件会自动处理所有底层细节：

```
你输入：/lmadd <Felis Abyssalis养了一只叫诺瓦（Noir）的赛博小猫。>

插件为你生成：
  content = "Felis Abyssalis养了一只叫诺瓦（Noir）的赛博小猫。"
  session_id = (自动获取当前会话)
  persona_id = (自动获取当前人格)
  importance = 0.8
  + BM25 关键词索引（自动）
  + Faiss 向量索引（自动）
  + SQLite 文档记录（自动）
```

那些 `topics`、`key_facts`、`canonical_summary` 等复杂字段，是 LivingMemory **自动总结**时由 LLM 额外生成的。手动插入不需要这些——你的原文会被直接存储，并且在语义搜索和关键词搜索中都能被检索到。

---

## 安装

1. 将 `livingmemory_manual` 文件夹放入 AstrBot 的 `data/plugins/` 目录
2. 确保 [LivingMemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory) 插件已安装并正常运行
3. 重启 AstrBot 或重载插件

### 依赖

无额外依赖。本插件直接借用 LivingMemory 的 MemoryEngine 实例。

---

## 配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `default_importance` | 手动插入记忆的默认重要性（0-1） | `0.8` |

> 手动插入的记忆默认重要性为 0.8，高于自动总结的 0.5。
> 如果启用了 LivingMemory 的重要性衰减机制，更高的初始重要性意味着这条记忆会"活"得更久。

---

## 工作原理

```
/lmadd <text>
    │
    ▼
LivingMemoryManual 插件
    │  运行时发现同进程中的 LivingMemoryPlugin 实例
    │  获取 plugin.initializer.memory_engine
    ▼
MemoryEngine.add_memory(content, session_id, persona_id, importance)
    │  内部自动处理：
    ├─ jieba 分词 → BM25 FTS5 索引
    ├─ Embedding 向量化 → Faiss 向量索引
    └─ SQLite documents 表写入
```

### 与验证

插入记忆后，可使用 LivingMemory 的搜索命令验证：

```
/lmem search Felis Abyssalis养了一只叫诺瓦（Noir）的赛博小猫。
```

或在 LivingMemory 的 WebUI 管理面板中查看。
