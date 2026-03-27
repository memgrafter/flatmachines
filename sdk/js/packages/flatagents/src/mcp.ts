import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import type { MCPServer, ToolFilter } from './types';

export class MCPToolProvider {
  private clients = new Map<string, Client>();

  async connect(servers: Record<string, MCPServer>): Promise<void> {
    if (!servers || typeof servers !== 'object') {
      return;
    }

    for (const [name, server] of Object.entries(servers)) {
      if (!name || !server || typeof server !== 'object') {
        continue;
      }

      const command = typeof server.command === 'string' ? server.command.trim() : '';
      if (!command) {
        continue;
      }

      try {
        const transport = new StdioClientTransport({
          command,
          args: server.args || [],
          env: server.env
        });
        const client = new Client({ name, version: "1.0.0" });
        await client.connect(transport);
        this.clients.set(name, client);
      } catch {
        // Swallow connection failures to allow best-effort startup.
      }
    }
  }

  async listTools(filter?: ToolFilter): Promise<any[]> {
    const tools: any[] = [];
    for (const [serverName, client] of this.clients) {
      const { tools: serverTools } = await client.listTools();
      for (const tool of serverTools) {
        const name = `${serverName}:${tool.name}`;
        if (this.matchesFilter(name, filter)) tools.push({ ...tool, name });
      }
    }
    return tools;
  }

  async callTool(name: string, args: any): Promise<any> {
    const [server, tool] = name.split(":");
    const client = this.clients.get(server);
    if (!client) {
      throw new Error(`MCP server '${server}' not found`);
    }
    return client.callTool({ name: tool, arguments: args });
  }

  private matchesFilter(name: string, filter?: ToolFilter): boolean {
    if (filter?.deny?.some(p => this.match(name, p))) return false;
    if (filter?.allow && !filter.allow.some(p => this.match(name, p))) return false;
    return true;
  }

  private match(name: string, pattern: string): boolean {
    if (pattern.includes("*")) {
      return new RegExp(pattern.replace(/\*/g, ".*")).test(name);
    }
    return name === pattern;
  }
}