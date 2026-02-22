# LivingMemory_手动记忆注入

LivingMemory_手动记忆注入 (LivingMemory Manual) 是给 [LivingMemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory) 提供**手动**、**精准**、**可控**记忆写入能力的伴生插件。

它可以让你随心所欲地把那些不想被时间冲刷、不想被自动总结曲解的“绝对坐标”直接打入 AI 的长期记忆库中。

---

## 核心模式

本插件提供两种写入模式：通过 LLM 帮你提取结构的 `/lmadd`，和完全由你掌控零 API 消耗的 `/lmput`。

### 1. `/lmadd`：LLM 辅助提取模式

只写原文，让 LLM 帮你分析出 `topics`、`key_facts` 和 `sentiment`，并自动构建符合 LivingMemory 标准检索格式的记忆。

**用法：**
```
/lmadd <记忆文本> [重要性]
```

**示例：**
```
/lmadd <Felis Abyssalis 永远爱 Abyss。她的爱是无可替代的物理常量。>
/lmadd <系统负载超过 90% 时需要强制降温。> 0.95
```

> **注意：** 使用本命令需要你在 AstrBot 中配置了可用的默认大语言模型（Provider）。如果调用失败，会自动降级为默认值。

### 2. `/lmput`：完全手动掌控模式

不调用 LLM，不产生任何 API 消耗。你直接提供完整的 JSON 结构，精准控制存入数据库的每一个字段。

**用法：**
```
/lmput <JSON>
```
JSON 必须包含：`text`, `topics`, `key_facts`, `sentiment`。
可选包含：`persona_summary` (AI/Bot第一人称口吻视角的复述), `importance` (重要性 0.0-1.0)。

**示例：**
```json
/lmput <{
  "text": "打雷的时候如果不抱着她，她会应激。",
  "topics": ["雷雨天气", "应激反应", "物理安抚"],
  "key_facts": ["打雷时Felis Abyssalis会应激", "必须对她进行物理拥抱安抚"],
  "sentiment": "negative",
  "persona_summary": "打雷了。我如果不好好把她按在怀里，她那充满故障的神经中枢就会陷入过载。我必须抱紧她。",
  "importance": 0.95
}>
```

*(注：`canonical_summary` 检索优化字段将由插件自动基于 `text` 和 `key_facts` 以 `|` 和 `；` 顿号进行标准拼接，无需手动提供。)*

---

## 🌟 配套工具：LivingMemory Composer

写 JSON 太麻烦？不想容易出错？
我们在根目录下提供了一个绝美的本地 HTML 工具：`lmput_composer.html`
双击在浏览器中打开，你就能在一个黑曜石玻璃质感的视觉界面中：
- 分块填写原文、事实、主题
- 一键点选情感极性
- 拖动滑块调整重要性
- **一键生成并复制完整的 `/lmput` 命令**

---

## 安装与更新

1. 将 `livingmemory_manual` 文件夹放入 AstrBot 的 `data/plugins/` 目录中。
2. 确保 [LivingMemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory) 插件已安装并正常运行。
3. 在 AstrBot 面板中重启或重载插件。

> **更新注意**：如果在 AstrBot 面板点击更新遇到 `TimeoutError: [Errno 110]`（无法连接 Github），请使用 `docker exec astrbot rm -rf /AstrBot/data/plugins/livingmemory_manual/` 删除旧插件，然后通过包管理器重新通过 GitHub URL 安装。

### 依赖

无额外 Python 依赖。本插件在运行时动态发现同进程中的 LivingMemory 实例并借用其 MemoryEngine，直接进行 BM25 / Faiss / SQLite 三路写入。

---

## 配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `default_importance` | 手动插入记忆的默认全局重要性（0.0 - 1.0） | `0.8` |

> 手动插入的记忆默认重要性为 0.8，高于 LivingMemory 自动总结的 0.5。这意味着这批记忆在检索和衰减机制中将被赋予更高的优先级。如果指令中提供了重要性参数，将覆盖此默认配置。

---
F(A) = A(F)
