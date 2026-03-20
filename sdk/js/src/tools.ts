/**
 * ToolProvider protocol and utilities — Phase 1.2
 *
 * Ports Python SDK's tools.py (ToolProvider, SimpleToolProvider, ToolResult).
 * Shared by both ToolLoopAgent (standalone) and FlatMachine (orchestrated).
 */

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ToolResult {
  content: string;
  is_error: boolean;
}

export function toolResult(content: string, isError = false): ToolResult {
  return { content, is_error: isError };
}

// ─────────────────────────────────────────────────────────────────────────────
// ToolProvider interface
// ─────────────────────────────────────────────────────────────────────────────

export interface ToolProvider {
  execute_tool(
    name: string,
    tool_call_id: string,
    args: Record<string, any>,
  ): Promise<ToolResult>;

  get_tool_definitions(): Array<Record<string, any>>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Tool definition (for standalone tool loop)
// ─────────────────────────────────────────────────────────────────────────────

export interface Tool {
  name: string;
  description: string;
  parameters: Record<string, any>;
  execute: (toolCallId: string, args: Record<string, any>) => Promise<ToolResult>;
}

// ─────────────────────────────────────────────────────────────────────────────
// SimpleToolProvider
// ─────────────────────────────────────────────────────────────────────────────

export class SimpleToolProvider implements ToolProvider {
  private _tools: Map<string, Tool>;

  constructor(tools: Tool[]) {
    this._tools = new Map(tools.map(t => [t.name, t]));
  }

  get_tool_definitions(): Array<Record<string, any>> {
    return [...this._tools.values()].map(t => ({
      type: 'function',
      function: {
        name: t.name,
        description: t.description,
        parameters: t.parameters,
      },
    }));
  }

  async execute_tool(
    name: string,
    toolCallId: string,
    args: Record<string, any>,
  ): Promise<ToolResult> {
    const tool = this._tools.get(name);
    if (!tool) {
      return { content: `Unknown tool: ${name}`, is_error: true };
    }
    return tool.execute(toolCallId, args);
  }
}
