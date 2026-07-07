## lm-mem 使用规则

**新会话首轮**涉及代码/行为决策 → 加载 `Skill(lm-mem:memory)` 调 `get_user_context`。

**触发加载**：
- 用户表达持久信息（"记住/喜欢/习惯/总是/我之前说过/还记得吗"）
- 写/改代码（先检索风格偏好）
- 增删改记忆

**不触发**：纯技术问答、一次性指令（"这次/仅本次"）、用户说"不用记忆"。

**红线**（不存）：密钥、未脱敏 PII、临时状态与情绪、代码/git log/CLAUDE.md 已有的事实。

**作用域别只填 `user_id`**：
- 全局偏好 → `user_id`
- 项目相关 → 加 `app_id = <group>_<repo>`（`git remote get-url origin` 解析，无 remote 用目录名）
- Agent 策略 → `agent_id`；本次会话 → `run_id`

**存储语言 = 用户对话语言**（中/英）。

> 完整细节（category、metadata、TTL、检索/更新/删除）见 SKILL.md。
