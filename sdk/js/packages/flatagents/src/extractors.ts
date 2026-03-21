/**
 * Response extractors.
 *
 * Ports Python SDK's FreeExtractor, StructuredExtractor, ToolsExtractor,
 * RegexExtractor, FreeThinkingExtractor from baseagent.py.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Extractor protocol
// ─────────────────────────────────────────────────────────────────────────────

export interface Extractor {
  extract(response: any): any;
}

// ─────────────────────────────────────────────────────────────────────────────
// Implementations
// ─────────────────────────────────────────────────────────────────────────────

function stripMarkdownJson(text: string): string {
  const match = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  return match ? match[1]!.trim() : text.trim();
}

/**
 * Returns raw response content as-is. No parsing.
 */
export class FreeExtractor implements Extractor {
  extract(response: any): string {
    if (typeof response === 'string') return response;
    return response?.text ?? response?.choices?.[0]?.message?.content ?? '';
  }
}

/**
 * Preserves reasoning/thinking from the response.
 * Returns { thinking, response }.
 */
export class FreeThinkingExtractor implements Extractor {
  extract(response: any): { thinking: string; response: string } {
    let content = '';
    let thinking = '';

    if (typeof response === 'string') {
      content = response;
    } else {
      const message = response?.choices?.[0]?.message;
      content = message?.content ?? response?.text ?? '';

      // Provider-specific thinking field
      if (message?.thinking) {
        thinking = message.thinking;
      } else if (message?.content_blocks) {
        for (const block of message.content_blocks) {
          if (block?.type === 'thinking') thinking = block.text ?? '';
          else if (block?.type === 'text') content = block.text ?? content;
        }
      }
    }

    // Fallback: <thinking> tags
    if (!thinking && content.includes('<thinking>') && content.includes('</thinking>')) {
      const m = content.match(/<thinking>([\s\S]*?)<\/thinking>/);
      if (m) {
        thinking = m[1]!.trim();
        content = content.replace(/<thinking>[\s\S]*?<\/thinking>/g, '').trim();
      }
    }

    return { thinking, response: content };
  }
}

/**
 * Extracts structured JSON output. Strips markdown fences.
 */
export class StructuredExtractor implements Extractor {
  constructor(private schema?: Record<string, any>) {}

  extract(response: any): any {
    if (response === null || response === undefined) return response;
    let content: string;
    if (typeof response === 'string') {
      content = response;
    } else {
      content = response?.text ?? response?.choices?.[0]?.message?.content ?? '';
    }
    if (content === '') return '';

    // Try stripping markdown fences first
    const stripped = stripMarkdownJson(content);
    try {
      return JSON.parse(stripped);
    } catch {
      // Try to find JSON object or array in the text
      const jsonMatch = content.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
      if (jsonMatch) {
        try { return JSON.parse(jsonMatch[1]!); } catch { /* fall through */ }
      }
      return { _raw: content, _error: 'Could not parse JSON' };
    }
  }
}

/**
 * Extracts tool calls from the response.
 * Returns { tool_calls, content }.
 */
export class ToolsExtractor implements Extractor {
  extract(response: any): { tool_calls: any[]; content: string } {
    const message = response?.choices?.[0]?.message;
    const content = message?.content ?? response?.text ?? '';
    const toolCalls: any[] = [];

    if (message?.tool_calls) {
      for (const tc of message.tool_calls) {
        const toolCall: any = {
          id: tc.id ?? null,
          type: tc.type ?? 'function',
          function: {
            name: tc.function?.name ?? null,
            arguments: tc.function?.arguments ?? null,
          },
        };
        if (typeof toolCall.function.arguments === 'string') {
          try {
            toolCall.function.arguments = JSON.parse(toolCall.function.arguments);
          } catch {
            // keep as string
          }
        }
        toolCalls.push(toolCall);
      }
    }

    return { tool_calls: toolCalls, content };
  }
}

/**
 * Extracts fields from response using regex patterns.
 * Patterns must have at least one capture group.
 */
export class RegexExtractor implements Extractor {
  private patterns: Map<string, RegExp>;
  private types: Record<string, string>;

  constructor(
    patterns: Record<string, string>,
    types?: Record<string, string>,
  ) {
    this.patterns = new Map(
      Object.entries(patterns).map(([k, v]) => [k, new RegExp(v)]),
    );
    this.types = types ?? {};
  }

  extract(response: any): Record<string, any> | null {
    let content: string;
    if (typeof response === 'string') {
      content = response;
    } else {
      content = response?.text ?? response?.choices?.[0]?.message?.content ?? '';
    }
    if (!content) return null;

    const result: Record<string, any> = {};
    for (const [fieldName, pattern] of this.patterns) {
      const match = pattern.exec(content);
      if (!match || match[1] === undefined) return null;

      const raw = match[1];
      const fieldType = this.types[fieldName] ?? 'str';

      try {
        switch (fieldType) {
          case 'json':
            result[fieldName] = JSON.parse(raw);
            break;
          case 'int':
            result[fieldName] = parseInt(raw, 10);
            if (isNaN(result[fieldName])) return null;
            break;
          case 'float':
            result[fieldName] = parseFloat(raw);
            if (isNaN(result[fieldName])) return null;
            break;
          case 'bool':
            result[fieldName] = ['true', '1', 'yes'].includes(raw.toLowerCase());
            break;
          default:
            result[fieldName] = raw;
        }
      } catch {
        return null;
      }
    }

    return result;
  }
}