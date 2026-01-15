// mcp.integration.test.ts
// Integration tests for Model Context Protocol (MCP) functionality

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { FlatAgent } from '../src/flatagent';
import { MCPToolProvider } from '../src/mcp';
import * as yaml from 'yaml';

const parseAgentConfig = (config: string) => yaml.parse(config);

// TODO: Tests need rewrite - AI SDK mocking issues
describe.skip('MCP Integration Tests', () => {
  let flatAgent: FlatAgent;
  let listToolsSpy: ReturnType<typeof vi.spyOn>;
  let callToolSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(MCPToolProvider.prototype, 'connect').mockResolvedValue();
    listToolsSpy = vi.spyOn(MCPToolProvider.prototype, 'listTools').mockResolvedValue([]);
    callToolSpy = vi.spyOn(MCPToolProvider.prototype, 'callTool').mockResolvedValue({});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('MCP Server Connection and Discovery', () => {
    it('should connect to and discover tools from multiple MCP servers', async () => {
      const mcpConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "mcp-multi-server-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "You have access to computational and filesystem tools"
  user: "{{ input.query }}"
  mcp:
    servers:
      calculator:
        command: "python"
        args: ["-m", "mcp.calculator"]
      filesystem:
        command: "python"
        args: ["-m", "mcp.filesystem"]
      web_search:
        command: "npm"
        args: ["run", "mcp:web-search"]
      database:
        command: "python"
        args: ["-m", "mcp.database"]
    tool_filter:
      allow: ["*", "!dangerous_operation"]
    tool_prompt: "Use the available tools to help answer the user's question."
  output:
    result:
      type: "str"
      description: "Answer using available tools"
    tools_used:
      type: "list"
      description: "List of tools that were used"
      items:
        type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(mcpConfig));

      // Mock MCP server discovery
      const mockToolDiscovery = listToolsSpy.mockResolvedValue([
        { name: 'calculator', description: 'Perform mathematical calculations', server: 'calculator' },
        { name: 'read_file', description: 'Read file contents', server: 'filesystem' },
        { name: 'web_search', description: 'Search the web', server: 'web_search' },
        { name: 'query_db', description: 'Query database', server: 'database' }
      ]);

      // Mock agent execution with tool calls
      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              result: 'I calculated 5 * 7 = 35 using the calculator tool',
              tools_used: ['calculator']
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        query: 'What is 5 multiplied by 7?'
      });

      expect(result.output.result).toContain('35');
      expect(result.output.tools_used).toContain('calculator');
      expect(mockToolDiscovery).toHaveBeenCalled();
    });

    it('should handle failed MCP server connections gracefully', async () => {
      const mcpConfigWithFailure = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "mcp-failure-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Agent with MCP tools"
  user: "{{ input.query }}"
  mcp:
    servers:
      working_server:
        command: "python"
        args: ["-m", "mcp.working"]
      failing_server:
        command: "python"
        args: ["-m", "mcp.nonexistent"]
      another_failing:
        command: "invalid-command"
        args: ["nonexistent"]
  tool_filter:
    allow: ["*"]
  output:
    result:
      type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(mcpConfigWithFailure));

      // Mock partial tool discovery (some servers fail)
      const mockToolDiscovery = listToolsSpy.mockResolvedValue([
        { name: 'working_tool', description: 'Working tool', server: 'working_server' }
        // Tools from failing servers are not included
      ]);

      const mockResponse = {
        choices: [{
          message: {
            content: 'I can only use the working tool since other servers failed to connect'
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        query: 'Use tools from connected servers'
      });

      expect(result.output.result).toBeDefined();
      expect(mockToolDiscovery).toHaveBeenCalled();
    });
  });

  describe('Tool Filtering and Selection', () => {
    it('should apply allow/deny filters correctly', async () => {
      const filterConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "tool-filter-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Agent with filtered tool access"
  user: "{{ input.query }}"
  mcp:
    servers:
      tools_server:
        command: "python"
        args: ["-m", "mcp.all_tools"]
    tool_filter:
      allow: ["calculator", "read_file", "search_web"]
      deny: ["delete_file", "format_disk"]
    tool_prompt: "Only use the allowed tools to help."
  output:
    result:
      type: "str"
    available_tools:
      type: "list"
      description: "List of available tools after filtering"
      items:
        type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(filterConfig));

      // Mock all available tools before filtering
      const mockAllTools = [
        { name: 'calculator', description: 'Math operations', server: 'tools_server' },
        { name: 'read_file', description: 'Read files', server: 'tools_server' },
        { name: 'write_file', description: 'Write files', server: 'tools_server' },
        { name: 'delete_file', description: 'Delete files', server: 'tools_server' },
        { name: 'format_disk', description: 'Format disk', server: 'tools_server' },
        { name: 'search_web', description: 'Web search', server: 'tools_server' }
      ];

      // Mock filtered tools
      const mockFilteredTools = [
        { name: 'calculator', description: 'Math operations', server: 'tools_server' },
        { name: 'read_file', description: 'Read files', server: 'tools_server' },
        { name: 'search_web', description: 'Web search', server: 'tools_server' }
      ];

      const mockToolDiscovery = listToolsSpy.mockResolvedValue(mockFilteredTools);
      
      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              result: 'I can use calculator, read_file, and search_web tools',
              available_tools: ['calculator', 'read_file', 'search_web']
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        query: 'What tools can I use?'
      });

      expect(result.output.available_tools).toHaveLength(3);
      expect(result.output.available_tools).toContain('calculator');
      expect(result.output.available_tools).toContain('read_file');
      expect(result.output.available_tools).toContain('search_web');
      // Should not contain filtered tools
      expect(result.output.available_tools).not.toContain('delete_file');
      expect(result.output.available_tools).not.toContain('format_disk');
    });

    it('should handle wildcard patterns in tool filters', async () => {
      const wildcardConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "wildcard-filter-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Agent with wildcard tool filtering"
  user: "{{ input.query }}"
  mcp:
    servers:
      math_server:
        command: "python"
        args: ["-m", "mcp.math"]
      file_server:
        command: "python"
        args: ["-m", "mcp.filesystem"]
    tool_filter:
      allow: ["math_*", "read_*", "write_*"]
      deny: ["math_*dangerous", "write_*system"]
    tool_prompt: "Use the safe math and file tools."
  output:
    result:
      type: "str"
    filtered_tools:
      type: "list"
      description: "Tools that match wildcard patterns"
`;

      flatAgent = new FlatAgent(parseAgentConfig(wildcardConfig));

      const mockWildcardTools = [
        { name: 'math_add', description: 'Add numbers', server: 'math_server' },
        { name: 'math_multiply', description: 'Multiply numbers', server: 'math_server' },
        { name: 'math_dangerous', description: 'Dangerous math operation', server: 'math_server' },
        { name: 'math_divide', description: 'Divide numbers', server: 'math_server' },
        { name: 'read_file', description: 'Read file', server: 'file_server' },
        { name: 'write_file', description: 'Write file', server: 'file_server' },
        { name: 'write_system', description: 'Write system file', server: 'file_server' },
        { name: 'delete_file', description: 'Delete file', server: 'file_server' }
      ];

      const mockFilteredWildcard = [
        { name: 'math_add', description: 'Add numbers', server: 'math_server' },
        { name: 'math_multiply', description: 'Multiply numbers', server: 'math_server' },
        { name: 'math_divide', description: 'Divide numbers', server: 'math_server' },
        { name: 'read_file', description: 'Read file', server: 'file_server' },
        { name: 'write_file', description: 'Write file', server: 'file_server' }
      ];

      const mockToolDiscovery = listToolsSpy.mockResolvedValue(mockFilteredWildcard);
      
      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              result: 'Wildcard filtering applied successfully',
              filtered_tools: ['math_add', 'math_multiply', 'math_divide', 'read_file', 'write_file']
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        query: 'Show filtered tools with wildcards'
      });

      expect(result.output.filtered_tools).toHaveLength(5);
      expect(result.output.filtered_tools).toContain('math_add');
      expect(result.output.filtered_tools).toContain('math_divide');
      // Should not contain dangerous patterns
      expect(result.output.filtered_tools).not.toContain('math_dangerous');
      expect(result.output.filtered_tools).not.toContain('write_system');
      expect(result.output.filtered_tools).not.toContain('delete_file');
    });
  });

  describe('Tool Execution and Results', () => {
    it('should execute mathematical tools and return structured results', async () => {
      const mathConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "math-operations-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "You are a mathematical assistant with access to calculation tools"
  user: "Solve: {{ input.problem }}"
  mcp:
    servers:
      advanced_math:
        command: "python"
        args: ["-m", "mcp.advanced_math"]
    tool_filter:
      allow: ["calculate", "solve_equation", "derivative", "integral"]
    tool_prompt: "Use the mathematical tools to solve the problem accurately."
  output:
    solution:
      type: "str"
      description: "Detailed solution to the problem"
    steps:
      type: "list"
      description: "Step-by-step solution process"
      items:
        type: "str"
    final_answer:
      type: "float"
      description: "Numerical answer"
    tools_used:
      type: "list"
      description: "Tools used in solving"
      items:
        type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(mathConfig));

      const mockToolDiscovery = listToolsSpy.mockResolvedValue([
        { name: 'calculate', description: 'Basic calculations', server: 'advanced_math' },
        { name: 'solve_equation', description: 'Solve equations', server: 'advanced_math' },
        { name: 'derivative', description: 'Calculate derivatives', server: 'advanced_math' },
        { name: 'integral', description: 'Calculate integrals', server: 'advanced_math' }
      ]);

      // Mock tool executing with complex math
      const mockToolCall = callToolSpy.mockImplementation((toolName, args) => {
        if (toolName === 'calculate') {
          return Promise.resolve({
            result: args.expression === '2 * 15 + 5' ? 35 : 'evaluation_failed',
            steps: ['Multiply 2 * 15 = 30', 'Add 30 + 5 = 35']
          });
        }
        return Promise.resolve({ result: 'tool_error' });
      });

      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              solution: 'To solve 2 * 15 + 5: first multiply 2 by 15 to get 30, then add 5 to get 35.',
              steps: ['Step 1: Calculate 2 × 15 = 30', 'Step 2: Add 30 + 5 = 35'],
              final_answer: 35,
              tools_used: ['calculate']
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        problem: 'What is 2 * 15 + 5?'
      });

      expect(result.output.solution).toContain('multiply');
      expect(result.output.steps).toHaveLength(2);
      expect(result.output.final_answer).toBe(35);
      expect(result.output.tools_used).toContain('calculate');
    });

    it('should handle file system tool operations', async () => {
      const filesystemConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "filesystem-operations-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "You can read, write, and manage files using filesystem tools"
  user: "{{ input.instruction }} {{ input.file_path }}"
  mcp:
    servers:
      filesystem:
        command: "python"
        args: ["-m", "mcp.filesystem"]
    tool_filter:
      allow: ["read_file", "write_file", "list_directory", "create_directory"]
    tool_prompt: "Use the filesystem tools to complete the file operations."
  output:
    file_content:
      type: "str"
      description: "Content of read files"
    operation_result:
      type: "object"
      description: "Result of file operations"
    directory_listing:
      type: "list"
      description: "Files and directories found"
      items:
        type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(filesystemConfig));

      const mockToolDiscovery = listToolsSpy.mockResolvedValue([
        { name: 'read_file', description: 'Read file contents', server: 'filesystem' },
        { name: 'write_file', description: 'Write content to file', server: 'filesystem' },
        { name: 'list_directory', description: 'List directory contents', server: 'filesystem' },
        { name: 'create_directory', description: 'Create directory', server: 'filesystem' }
      ]);

      // Mock filesystem tool operations
      const mockToolCall = callToolSpy.mockImplementation((toolName, args) => {
        switch (toolName) {
          case 'read_file':
            return Promise.resolve({
              content: 'Hello, this is test file content!',
              size: 33,
              encoding: 'utf-8'
            });
          case 'list_directory':
            return Promise.resolve({
              files: ['file1.txt', 'file2.json', 'subdirectory/'],
              total_count: 3
            });
          case 'write_file':
            return Promise.resolve({
              success: true,
              bytes_written: args.content.length,
              file_path: args.path
            });
          default:
            return Promise.resolve({ error: 'Unknown operation' });
        }
      });

      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              file_content: 'Hello, this is test file content!',
              operation_result: { 
                read_success: true,
                file_size: 33
              },
              directory_listing: ['file1.txt', 'file2.json', 'subdirectory/']
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        instruction: 'Read the contents of',
        file_path: '/tmp/test.txt'
      });

      expect(result.output.file_content).toBe('Hello, this is test file content!');
      expect(result.output.operation_result.read_success).toBe(true);
      expect(result.output.directory_listing).toHaveLength(3);
    });

    it('should handle web search and data retrieval tools', async () => {
      const webConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "web-search-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "You can search the web and retrieve information using web tools"
  user: "{{ input.search_query }}"
  mcp:
    servers:
      web_search:
        command: "python"
        args: ["-m", "mcp.web_search"]
      api_client:
        command: "python"
        args: ["-m", "mcp.api_client"]
    tool_filter:
      allow: ["search_web", "fetch_url", "parse_html"]
    tool_prompt: "Use web tools to search for and retrieve current information."
  output:
    search_results:
      type: "list"
      description: "Web search results"
      items:
        type: "object"
        properties:
          title:
            type: "str"
          url:
            type: "str"
          snippet:
            type: "str"
    retrieved_content:
      type: "str"
      description: "Content fetched from URLs"
    sources:
      type: "list"
      description: "Source URLs used"
      items:
        type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(webConfig));

      const mockToolDiscovery = listToolsSpy.mockResolvedValue([
        { name: 'search_web', description: 'Search the web', server: 'web_search' },
        { name: 'fetch_url', description: 'Fetch URL content', server: 'api_client' },
        { name: 'parse_html', description: 'Parse HTML content', server: 'api_client' }
      ]);

      // Mock web tools
      const mockToolCall = callToolSpy.mockImplementation((toolName, args) => {
        switch (toolName) {
          case 'search_web':
            return Promise.resolve({
              results: [
                {
                  title: 'JavaScript Async/Await Guide',
                  url: 'https://example.com/js-async-guide',
                  snippet: 'Comprehensive guide to async/await in JavaScript'
                },
                {
                  title: 'Modern JavaScript Features',
                  url: 'https://example.com/modern-js',
                  snippet: 'Overview of modern JavaScript features including async operations'
                }
              ],
              total_results: 2,
              search_time: 0.5
            });
          case 'fetch_url':
            return Promise.resolve({
              content: '<html><head><title>JavaScript Guide</title></head><body><h1>Async/Await Tutorial</h1></body></html>',
              status_code: 200,
              response_time: 200
            });
          default:
            return Promise.resolve({ error: 'Tool not available' });
        }
      });

      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              search_results: [
                {
                  title: 'JavaScript Async/Await Guide',
                  url: 'https://example.com/js-async-guide',
                  snippet: 'Comprehensive guide to async/await in JavaScript'
                },
                {
                  title: 'Modern JavaScript Features',
                  url: 'https://example.com/modern-js',
                  snippet: 'Overview of modern JavaScript features including async operations'
                }
              ],
              retrieved_content: 'JavaScript Async/Await Tutorial',
              sources: ['https://example.com/js-async-guide', 'https://example.com/modern-js']
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        search_query: 'JavaScript async await best practices'
      });

      expect(result.output.search_results).toHaveLength(2);
      expect(result.output.search_results[0].title).toContain('JavaScript Async/Await');
      expect(result.output.sources).toHaveLength(2);
      expect(result.output.sources[0].url).toContain('js-async-guide');
    });
  });

  describe('Error Handling and Recovery', () => {
    it('should handle tool execution failures gracefully', async () => {
          const errorHandlingConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "error-handling-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Agent that handles tool errors gracefully"
  user: "{{ input.task }}"
  mcp:
    servers:
      unreliable_server:
        command: "python"
        args: ["-m", "mcp.unreliable"]
    tool_filter:
      allow: ["*", "except:dangerous_*"]
    tool_prompt: "Use tools but handle any errors that occur."
  output:
    result:
      type: "str"
      description: "Result or error explanation"
    tool_errors:
      type: "list"
      description: "Errors encountered during tool usage"
      items:
        type: "str"
    fallback_result:
      type: "str"
      description: "Result achieved without failing tools"
`;

          flatAgent = new FlatAgent(parseAgentConfig(errorHandlingConfig));

          const mockToolDiscovery = listToolsSpy.mockResolvedValue([
              { name: 'working_tool', description: 'Works correctly', server: 'unreliable_server' },
              { name: 'failing_tool', description: 'Always fails', server: 'unreliable_server' },
              { name: 'dangerous_tool', description: 'Filtered out', server: 'unreliable_server' }
          ]);

          // Mock tool with failures
          const mockToolCall = callToolSpy.mockImplementation((toolName, args) => {
              if (toolName === 'failing_tool') {
                  return Promise.reject(new Error('Tool execution failed: Connection timeout'));
              } else if (toolName === 'working_tool') {
                  return Promise.resolve({
                      result: 'Tool worked correctly',
                      status: 'success'
                  });
              }
              return Promise.resolve({ error: 'Unknown tool' });
          });

          const mockResponse = {
              choices: [{
                  message: {
                      content: JSON.stringify({
                          result: 'I completed the task using working_tool after failing_tool failed',
                          tool_errors: ['Tool execution failed: Connection timeout'],
                          fallback_result: 'Task completed using alternative tool'
                      })
                  }
              }]
          };

          global.fetch = vi.fn().mockResolvedValue({
              ok: true,
              json: () => Promise.resolve(mockResponse)
          });

          const result = await flatAgent.call({
              task: 'Complete operation using available tools'
          });

          expect(result.output.result).toContain('working_tool');
          expect(result.output.tool_errors).toHaveLength(1);
          expect(result.output.tool_errors[0]).toContain('Connection timeout');
          expect(result.output.fallback_result).toBeDefined();
      });

      it('should handle partial tool failures in multi-tool workflows', async () => {
          const partialFailureConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "partial-failure-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Agent that continues when some tools fail"
  user: "{{ input.complex_task }}"
  mcp:
    servers:
      multi_tool_server:
        command: "python"
        args: ["-m", "mcp.multi_tools"]
    tool_filter:
      allow: ["*"]
    tool_prompt: "Use multiple tools, continue even if some fail."
  output:
    successful_operations:
      type: "list"
      description: "Operations that completed successfully"
      items:
        type: "str"
    failed_operations:
      type: "list"
      description: "Operations that failed"
      items:
        type: "str"
    partial_result:
      type: "object"
      description: "Result achieved with partial success"
`;

          flatAgent = new FlatAgent(parseAgentConfig(partialFailureConfig));

          const mockToolDiscovery = listToolsSpy.mockResolvedValue([
              { name: 'data_retriever', description: 'Retrieves data', server: 'multi_tool_server' },
              { name: 'data_processor', description: 'Processes data', server: 'multi_tool_server' },
              { name: 'data_formatter', description: 'Formats output', server: 'multi_tool_server' }
          ]);

          // Mock partial tool failures
          let toolCallCount = 0;
          const mockToolCall = callToolSpy.mockImplementation((toolName, args) => {
              toolCallCount++;
              if (toolName === 'data_processor') {
                  return Promise.reject(new Error('Processing service unavailable'));
              } else {
                  return Promise.resolve({
                      result: `${toolName} completed successfully`,
                      call_number: toolCallCount
                  });
              }
          });

          const mockResponse = {
              choices: [{
                  message: {
                      content: JSON.stringify({
                          successful_operations: ['data_retriever', 'data_formatter'],
                          failed_operations: ['data_processor'],
                          partial_result: {
                              status: 'partial_success',
                              completed_steps: 2,
                              total_steps: 3
                          }
                      })
                  }
              }]
          };

          global.fetch = vi.fn().mockResolvedValue({
              ok: true,
              json: () => Promise.resolve(mockResponse)
          });

          const result = await flatAgent.call({
              complex_task: 'Retrieve, process, and format data'
          });

          expect(result.output.successful_operations).toHaveLength(2);
          expect(result.output.failed_operations).toHaveLength(1);
          expect(result.output.successful_operations).toContain('data_retriever');
          expect(result.output.failed_operations).toContain('data_processor');
          expect(result.output.partial_result.completed_steps).toBe(2);
      });
  });

  describe('Complex MCP Workflows', () => {
    it('should handle multi-step workflows with multiple MCP servers', async () => {
          const workflowConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "multi-server-workflow-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Agent that orchestrates complex workflows using multiple MCP servers"
  user: "{{ input.workflow_request }}"
  mcp:
    servers:
      data_source:
        command: "python"
        args: ["-m", "mcp.data_source"]
      data_processor:
        command: "python"
        args: ["-m", "mcp.data_processor"]
      visualization:
        command: "python"
        args: ["-m", "mcp.visualization"]
      reporting:
        command: "python"
        args: ["-m", "mcp.reporting"]
    tool_filter:
      allow: ["*"]
    tool_prompt: "Coordinate multiple servers to complete the workflow."
  output:
    workflow_stages:
      type: "list"
      description: "Stages completed in the workflow"
      items:
        type: "object"
        properties:
          stage:
            type: "str"
          server:
            type: "str"
          status:
            type: "str"
    final_report:
      type: "object"
      description: "Complete workflow results"
    servers_used:
      type: "list"
      description: "MCP servers that participated"
      items:
        type: "str"
`;

          flatAgent = new FlatAgent(parseAgentConfig(workflowConfig));

          const mockToolDiscovery = listToolsSpy.mockResolvedValue([
              { name: 'fetch_data', description: 'Fetch raw data', server: 'data_source' },
              { name: 'clean_data', description: 'Clean and validate data', server: 'data_processor' },
              { name: 'create_chart', description: 'Create visualization', server: 'visualization' },
              { name: 'generate_report', description: 'Generate final report', server: 'reporting' }
          ]);

          // Mock complex workflow
          const mockToolCall = callToolSpy.mockImplementation((toolName, args) => {
              switch (toolName) {
                  case 'fetch_data':
                      return Promise.resolve({
                          data: Array.from({ length: 100 }, (_, i) => ({ index: i, value: Math.random() * 100 })),
                          source: 'database_connection',
                          records: 100
                      });
                  case 'clean_data':
                      return Promise.resolve({
                          cleaned_data: Array.from({ length: 95 }, (_, i) => ({ index: i, value: Math.random() * 100 })),
                          removed_records: 5,
                          validation_passed: true
                      });
                  case 'create_chart':
                      return Promise.resolve({
                          chart_url: 'https://charts.example.com/visualization_123.png',
                          chart_type: 'scatter_plot',
                          data_points: 95
                      });
                  case 'generate_report':
                      return Promise.resolve({
                          report_id: 'report_456',
                          summary: 'Data analysis completed successfully',
                          recommendations: ['Implement data quality checks', 'Monitor for outliers']
                      });
                  default:
                      return Promise.resolve({ error: 'Unknown workflow step' });
              }
          });

          const mockResponse = {
              choices: [{
                  message: {
                      content: JSON.stringify({
                          workflow_stages: [
                              { stage: 'data_fetching', server: 'data_source', status: 'completed' },
                              { stage: 'data_processing', server: 'data_processor', status: 'completed' },
                              { stage: 'visualization', server: 'visualization', status: 'completed' },
                              { stage: 'reporting', server: 'reporting', status: 'completed' }
                          ],
                          final_report: {
                              report_id: 'report_456',
                              chart_url: 'https://charts.example.com/visualization_123.png',
                              summary: 'Data analysis completed successfully with 95 records processed',
                              data_quality: 'good'
                          },
                          servers_used: ['data_source', 'data_processor', 'visualization', 'reporting']
                      })
                  }
              }]
          };

          global.fetch = vi.fn().mockResolvedValue({
              ok: true,
              json: () => Promise.resolve(mockResponse)
          });

          const result = await flatAgent.call({
              workflow_request: 'Analyze dataset and create visualization report'
          });

          expect(result.output.workflow_stages).toHaveLength(4);
          expect(result.output.workflow_stages[0].server).toBe('data_source');
          expect(result.output.final_report.report_id).toBe('report_456');
          expect(result.output.servers_used).toHaveLength(4);
          expect(result.output.servers_used).toContain('visualization');
      });
  });
});