"""
Memory Consolidation Prompt 模板
"""

# save_memory 工具定义
SAVE_MEMORY_TOOL = [{
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": "Save the memory consolidation result to persistent storage.",
        "parameters": {
            "type": "object",
            "properties": {
                "history_entry": {
                    "type": "string",
                    "description": "A paragraph summarizing key events/decisions/topics. "
                                    "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                },
                "memory_update": {
                    "type": "string",
                    "description": "Full updated long-term memory as markdown. Include all existing "
                                   "facts plus new ones. Return unchanged if nothing new. "
                                   "IMPORTANT: keep total under the specified token budget.",
                },
            },
            "required": ["history_entry", "memory_update"],
        },
    }
}]


def build_consolidation_prompt(current_memory: str, formatted_messages: str,
                               max_memory_tokens: int = 0) -> str:
    budget_line = (
        f"\n**MEMORY.md TOKEN BUDGET: {max_memory_tokens} tokens max.** "
        f"Compress if the updated content exceeds this limit.\n"
        if max_memory_tokens > 0 else ""
    )
    return f"""You are a memory consolidation agent. Analyze the conversation and extract important information.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{formatted_messages}
{budget_line}
## CRITICAL INSTRUCTION
You MUST call the `save_memory` tool now. Do NOT respond with text only.
Call the tool with history_entry and memory_update parameters.

Parameters:
- history_entry: [YYYY-MM-DD HH:MM] Summary of conversation with key details
- memory_update: Full updated MEMORY.md content (include all existing facts plus new ones)"""
