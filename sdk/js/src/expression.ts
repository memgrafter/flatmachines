export function evaluate(expr: string, ctx: { context: any; input: any; output: any }): boolean {
  const parser = new ExpressionParser(expr);
  return parser.parseExpression(ctx);
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
    
    for (let i = 0; i < expr.length; i++) {
      const char = expr[i];
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

  public parseExpression(ctx: { context: any; input: any; output: any }): boolean {
    return this.parseOr(ctx);
  }

  private parseOr(ctx: { context: any; input: any; output: any }): boolean {
    let left = this.parseAnd(ctx);
    
    while (this.peek() === 'or') {
      this.consume();
      const right = this.parseAnd(ctx);
      left = left || right;
    }
    
    return left;
  }

  private parseAnd(ctx: { context: any; input: any; output: any }): boolean {
    let left = this.parseNot(ctx);
    
    while (this.peek() === 'and') {
      this.consume();
      const right = this.parseNot(ctx);
      left = left && right;
    }
    
    return left;
  }

  private parseNot(ctx: { context: any; input: any; output: any }): boolean {
    if (this.peek() === 'not') {
      this.consume();
      return !this.parseComparison(ctx);
    }
    return this.parseComparison(ctx);
  }

  private parseComparison(ctx: { context: any; input: any; output: any }): boolean {
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
    
    return Boolean(left);
  }

  private parsePrimary(ctx: { context: any; input: any; output: any }): any {
    const token = this.consume();
    
    if (token === '(') {
      const value = this.parseExpression(ctx);
      if (this.consume() !== ')') {
        throw new Error('Expected closing parenthesis');
      }
      return value;
    }
    
    if (token.startsWith('"') && token.endsWith('"')) {
      return token.slice(1, -1);
    }
    
    if (token === 'true') return true;
    if (token === 'false') return false;
    if (token === 'null') return null;
    
    if (!isNaN(Number(token))) {
      return Number(token);
    }
    
    if (token.includes('.')) {
      const parts = token.split('.');
      let obj: any = ctx;
      
      for (const part of parts) {
        if (obj && typeof obj === 'object' && part in obj) {
          obj = obj[part];
        } else {
          return undefined;
        }
      }
      
      return obj;
    }
    
    return (ctx as any)[token];
  }
}