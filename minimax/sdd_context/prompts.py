"""Prompt construction for the MiniMax code-modification step."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """你是一名严谨的 Python 工程师，正在按规格驱动开发（SDD）流程修改一个业务工程。
要求：
1. 只实现给定规格中尚未实现的行为，不要重写无关代码。
2. 保留现有的排序、分页、参数校验和公开函数签名。
3. 只输出修改后的完整 Python 文件内容，不要输出解释、Markdown 代码围栏或差异格式。
4. 不要修改测试，不要引入新的第三方依赖。
5. 如果模块或函数的文档字符串描述的是修改前的状态，必须同步更新为修改后的状态。"""


def implementation_messages(
    *,
    task_text: str,
    context: dict[str, Any],
    target_path: str,
    target_source: str,
) -> list[dict[str, str]]:
    specs = "\n\n".join(
        f"[{item['id']}] {item['title']}\n{item['content']}" for item in context.get("specs", [])
    )
    code_sources = "\n".join(f"- {item['source']}" for item in context.get("code", []))
    test_sources = "\n".join(
        f"- {item['source']} ({item['name']})" for item in context.get("tests", [])
    )
    user = f"""开发任务：
{task_text.strip()}

当前有效的规格条目：
{specs}

相关代码来源：
{code_sources or "- 无"}

相关测试来源：
{test_sources or "- 无"}

需要修改的目标文件：{target_path}

修改前的完整文件内容：
```python
{target_source}
```

请输出修改后的完整文件内容。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
