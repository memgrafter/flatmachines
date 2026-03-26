/**
 * Simple expression evaluator (default engine).
 *
 * ## Supported Operations
 *
 * - **Dot-access**: `context.score`, `output.items.length`
 * - **Bracket indexing**: `context.items[0]`, `context.items[0].name`
 * - **Comparisons**: `==`, `!=`, `<`, `<=`, `>`, `>=`
 * - **Boolean logic**: `and`, `or`, `not`
 * - **Parenthesized grouping**: `(context.a or context.b) and context.c`
 * - **Literals**: strings (`"hello"`, `'hello'`), numbers, `true`, `false`, `null`
 *
 * ## NOT Supported (use CEL engine instead)
 *
 * - `x in list` — membership testing
 * - `len(items)` — function calls of any kind
 * - Arithmetic: `+`, `-`, `*`, `/`, `%`
 * - String concatenation
 * - Ternary/conditional expressions
 * - List/map construction
 *
 * To use the CEL engine (which supports all of the above), set
 * `expression_engine: cel` in your machine config and install `cel-js`:
 *
 * ```yaml
 * data:
 *   expression_engine: cel
 * ```
 *
 * ```bash
 * npm install cel-js
 * ```
 */
export function evaluate(expr: string, ctx: { context: any; input: any; output: any }): any {
  const trimmed = expr.trim();
  if (!trimmed) {
    throw new Error('Empty expression');
  }
  const parser = new ExpressionParser(trimmed);
  const result = parser.parse(ctx);
  return result;
}

class ExpressionParser {
  private tokens: string[] = [];
  private pos = 0;

  constructor(expr: string) {
    this.tokens = this.tokenize(expr);
  }

  private tokenize(expr: string): string[] {
    const tokens: string[] = [];
    let current = '';
    let inString = false;
    let stringChar = '';

    for (let i = 0; i < expr.length; i++) {
      const char = expr[i];

      // Handle string literals
      if ((char === '"' || char === "'") && !inString) {
        if (current) tokens.push(current);
        current = char;
        inString = true;
        stringChar = char;
        continue;
      }

      if (inString) {
        current += char;
        if (char === stringChar) {
          tokens.push(current);
          current = '';
          inString = false;
        }
        continue;
      }

      const char2 = expr.slice(i, i + 2);

      if (char2 === '==' || char2 === '!=' || char2 === '<=' || char2 === '>=') {
        if (current) tokens.push(current);
        tokens.push(char2);
        current = '';
        i++;
      } else if ('<>()'.includes(char)) {
        if (current) tokens.push(current);
        tokens.push(char);
        current = '';
      } else if (' \t\n'.includes(char)) {
        if (current) tokens.push(current);
        current = '';
      } else {
        current += char;
      }
    }

    if (current) tokens.push(current);
    return tokens;
  }

  private peek(): string | undefined {
    return this.tokens[this.pos];
  }

  private consume(): string {
    return this.tokens[this.pos++];
  }

  public parse(ctx: { context: any; input: any; output: any }): any {
    const result = this.parseExpression(ctx);
    // Ensure all tokens consumed (catches unbalanced parens and trailing syntax)
    if (this.pos < this.tokens.length) {
      throw new Error(`Unexpected token: ${this.tokens[this.pos]}`);
    }
    return result;
  }

  private parseExpression(ctx: { context: any; input: any; output: any }): any {
    return this.parseOr(ctx);
  }

  private parseOr(ctx: { context: any; input: any; output: any }): any {
    let left = this.parseAnd(ctx);

    while (this.peek() === 'or') {
      this.consume();
      const right = this.parseAnd(ctx);
      left = left || right;
    }

    return left;
  }

  private parseAnd(ctx: { context: any; input: any; output: any }): any {
    let left = this.parseNot(ctx);

    while (this.peek() === 'and') {
      this.consume();
      const right = this.parseNot(ctx);
      left = left && right;
    }

    return left;
  }

  private parseNot(ctx: { context: any; input: any; output: any }): any {
    if (this.peek() === 'not') {
      this.consume();
      return !this.parseComparison(ctx);
    }
    return this.parseComparison(ctx);
  }

  private parseComparison(ctx: { context: any; input: any; output: any }): any {
    const left = this.parsePrimary(ctx);

    const op = this.peek();
    if (op && ['==', '!=', '<', '<=', '>', '>='].includes(op)) {
      this.consume();
      const right = this.parsePrimary(ctx);

      switch (op) {
        case '==': return left === right;
        case '!=': return left !== right;
        case '<': return left < right;
        case '<=': return left <= right;
        case '>': return left > right;
        case '>=': return left >= right;
        default: throw new Error(`Unknown operator: ${op}`);
      }
    }

    return left;
  }

  private parsePrimary(ctx: { context: any; input: any; output: any }): any {
    const token = this.consume();

    if (token === undefined) {
      throw new Error('Unexpected end of expression');
    }

    if (token === ')') {
      throw new Error('Unexpected token: )');
    }

    if (token === '(') {
      const value = this.parseExpression(ctx);
      if (this.consume() !== ')') {
        throw new Error('Expected closing parenthesis');
      }
      return value;
    }

    if ((token.startsWith('"') && token.endsWith('"')) ||
        (token.startsWith("'") && token.endsWith("'"))) {
      return token.slice(1, -1);
    }

    if (token === 'true') return true;
    if (token === 'false') return false;
    if (token === 'null') return null;

    if (!isNaN(Number(token))) {
      return Number(token);
    }

    if (token.includes('.') || token.includes('[')) {
      // Split on dots, then handle bracket indexing within each segment
      // e.g. "context.items[0].name" → ["context", "items", 0, "name"]
      const segments: (string | number)[] = [];
      for (const dotPart of token.split('.')) {
        // Split bracket indices: "items[0]" → "items", 0
        const bracketMatch = dotPart.match(/^([^\[]*)((?:\[\d+\])*)$/);
        if (bracketMatch) {
          const base = bracketMatch[1]!;
          const indices = bracketMatch[2]!;
          if (base) segments.push(base);
          // Extract all [N] indices
          const idxMatches = indices.matchAll(/\[(\d+)\]/g);
          for (const m of idxMatches) {
            segments.push(Number(m[1]));
          }
        } else {
          segments.push(dotPart);
        }
      }

      let obj: any = ctx;
      for (const seg of segments) {
        if (obj == null) return undefined;
        if (typeof seg === 'number') {
          // Array/string indexing
          if (typeof obj === 'string' || Array.isArray(obj)) {
            obj = obj[seg];
          } else {
            return undefined;
          }
        } else {
          if (typeof obj === 'object' && seg in obj) {
            obj = obj[seg];
          } else {
            return undefined;
          }
        }
      }

      return obj;
    }

    return (ctx as any)[token];
  }
}