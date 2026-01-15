// flatagent.integration.test.ts
// Integration tests for FlatAgent functionality

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { FlatAgent } from '../src/flatagent';
import { existsSync } from 'fs';
import * as yaml from 'yaml';
import { join } from 'path';

const parseAgentConfig = (config: string) => yaml.parse(config);

describe('FlatAgent Integration Tests', () => {
  let flatAgent: FlatAgent;

  beforeEach(() => {
    // Reset any mocks
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // TODO: needs proper mocking
  describe.skip('Real Configuration Loading', () => {
    it('should load and execute a complete agent configuration', async () => {
      // Load real agent configuration from fixtures
      const configPath = join(__dirname, '../fixtures/configs/helloworld/next_char.yml');
      const agentConfig = existsSync(configPath)
        ? configPath
        : parseAgentConfig(`
spec: flatagent
spec_version: "0.6.0"
data:
  name: "test-agent"
  model:
    name: "gpt-4"
    provider: "openai"
    temperature: 0.7
    max_tokens: 1000
  system: "You are a helpful assistant."
  user: "{{ input.query }}"
  output:
    response:
      type: "str"
      description: "The agent's response"
`);

      flatAgent = new FlatAgent(agentConfig);
      
      // Mock the actual API call
      const mockResponse = {
        choices: [{
          message: {
            content: 'Hello! I am a helpful assistant ready to assist you.'
          }
        }]
      };

      // Mock the fetch/api call
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        query: 'Hello, can you help me?'
      });

      expect(result).toBeDefined();
      expect(result.output).toBeDefined();
      expect(result.output.response).toBe('Hello! I am a helpful assistant ready to assist you.');
    });

    it('should handle template rendering in real configuration', async () => {
      const configWithTemplates = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "template-agent"
  model:
    name: "gpt-3.5-turbo"
    provider: "openai"
  system: "You are a {{ input.role }} assistant specializing in {{ input.domain }}."
  user: |
    User: {{ input.user_message }}
    Context: {{ input.context }}
  output:
    analysis:
      type: "str"
      description: "Analysis of the user message"
    confidence:
      type: "float" 
      description: "Confidence score 0-1"
`;

      flatAgent = new FlatAgent(parseAgentConfig(configWithTemplates));

      // Mock API response
      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              analysis: "The user is asking for help with technical documentation",
              confidence: 0.85
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        role: 'technical',
        domain: 'software development',
        user_message: 'How do I create a REST API?',
        context: 'User is a beginner programmer'
      });

      expect(result.output.analysis).toBe('The user is asking for help with technical documentation');
      expect(result.output.confidence).toBe(0.85);
    });
  });

  describe('Error Handling Integration', () => {
    it('should handle network failures gracefully', async () => {
      const simpleConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "error-test-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Test agent"
  user: "{{ input.query }}"
`;

      flatAgent = new FlatAgent(parseAgentConfig(simpleConfig));

      // Mock network failure
      global.fetch = vi.fn().mockRejectedValue(new Error('Network timeout'));

      await expect(flatAgent.call({ query: 'test' })).rejects.toThrow('Network timeout');
    });

    it('should handle API error responses', async () => {
      const simpleConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "api-error-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Test agent"
  user: "{{ input.query }}"
`;

      flatAgent = new FlatAgent(parseAgentConfig(simpleConfig));

      // Mock API error response
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
        json: () => Promise.resolve({
          error: {
            message: 'Rate limit exceeded',
            type: 'rate_limit_error'
          }
        })
      });

      await expect(flatAgent.call({ query: 'test' })).rejects.toThrow();
    });

    it('should handle malformed API responses', async () => {
      const simpleConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "malformed-response-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Test agent"
  user: "{{ input.query }}"
`;

      flatAgent = new FlatAgent(parseAgentConfig(simpleConfig));

      // Mock malformed response
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ invalid: 'structure' })
      });

      await expect(flatAgent.call({ query: 'test' })).rejects.toThrow();
    });
  });

  // TODO: needs proper mocking
  describe.skip('Model Provider Integration', () => {
    it('should work with different model providers', async () => {
      const providers = [
        {
          name: 'OpenAI Provider',
          config: `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "openai-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "OpenAI agent"
  user: "{{ input.query }}"
`,
          mockResponse: {
            choices: [{ message: { content: 'Response from OpenAI' } }]
          }
        },
        {
          name: 'Anthropic Provider',
          config: `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "anthropic-agent"
  model:
    name: "claude-3"
    provider: "anthropic"
  system: "Anthropic agent"
  user: "{{ input.query }}"
`,
          mockResponse: {
            content: [{ text: 'Response from Anthropic' }]
          }
        },
        {
          name: 'Cerebras Provider',
          config: `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "cerebras-agent"
  model:
    name: "llama-3"
    provider: "cerebras"
  system: "Cerebras agent"
  user: "{{ input.query }}"
`,
          mockResponse: {
            choices: [{ message: { content: 'Response from Cerebras' } }]
          }
        }
      ];

      for (const provider of providers) {
        global.fetch = vi.fn().mockResolvedValue({
          ok: true,
          json: () => Promise.resolve(provider.mockResponse)
        });

        flatAgent = new FlatAgent(parseAgentConfig(provider.config));
        
        const result = await flatAgent.call({ query: 'test query' });
        
        expect(result).toBeDefined();
        expect(result.output).toBeDefined();
      }
    });

    it('should handle provider-specific configuration', async () => {
      const configWithProviderSettings = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "provider-settings-agent"
  model:
    name: "gpt-4"
    provider: "openai"
    temperature: 0.1
    max_tokens: 500
    top_p: 0.9
    frequency_penalty: 0.1
    presence_penalty: 0.1
  system: "Agent with custom provider settings"
  user: "{{ input.query }}"
`;

      flatAgent = new FlatAgent(parseAgentConfig(configWithProviderSettings));

      const mockResponse = {
        choices: [{ message: { content: 'Custom settings response' } }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({ query: 'test' });
      
      expect(result.output).toBeDefined();
      
      // Verify fetch was called with correct parameters
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('openai'),
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'Content-Type': 'application/json'
          }),
          body: expect.stringContaining('temperature')
        })
      );
    });
  });

  // TODO: needs proper mocking
  describe.skip('Structured Output Integration', () => {
    it('should handle complex structured output schemas', async () => {
      const complexOutputSchema = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "structured-output-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "You are a data analyst"
  user: "Analyze this data: {{ input.data }}"
  output:
    summary:
      type: "str"
      description: "Executive summary"
    insights:
      type: "list"
      description: "Key insights"
      items:
        type: "object"
        properties:
          category:
            type: "str"
          finding:
            type: "str"
          confidence:
            type: "float"
    metrics:
      type: "object"
      properties:
        accuracy:
          type: "float"
        precision:
          type: "float"
        recall:
          type: "float"
    recommendations:
      type: "list"
      description: "Actionable recommendations"
      items:
        type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(complexOutputSchema));

      const mockStructuredResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              summary: "Data analysis shows positive trends",
              insights: [
                { category: "Performance", finding: "95% success rate", confidence: 0.95 },
                { category: "User Satisfaction", finding: "High engagement", confidence: 0.88 }
              ],
              metrics: { accuracy: 0.92, precision: 0.89, recall: 0.94 },
              recommendations: [
                "Scale successful features",
                "Invest in user engagement",
                "Monitor performance metrics"
              ]
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockStructuredResponse)
      });

      const result = await flatAgent.call({
        data: 'User engagement metrics for Q3 2023'
      });

      expect(result.output.summary).toBe('Data analysis shows positive trends');
      expect(result.output.insights).toHaveLength(2);
      expect(result.output.insights[0].category).toBe('Performance');
      expect(result.output.metrics.accuracy).toBe(0.92);
      expect(result.output.recommendations).toContain('Scale successful features');
    });

    it('should handle output validation and coercion', async () => {
      const configWithTypeValidation = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "validation-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Provide typed output"
  user: "{{ input.query }}"
  output:
    score:
      type: "float"
      description: "Numeric score 0-100"
    passed:
      type: "bool"
      description: "Whether test passed"
    tags:
      type: "list"
      description: "Array of string tags"
      items:
        type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(configWithTypeValidation));

      // Mock response with various data types
      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              score: "85", // String that should be converted to number
              passed: "true", // String that should be converted to boolean
              tags: "tag1,tag2,tag3" // String that might need splitting
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({ query: 'Type validation test' });

      // The output should be properly typed (depending on implementation)
      expect(result.output).toBeDefined();
      expect(result.output.score).toBeDefined();
      expect(result.output.passed).toBeDefined();
      expect(result.output.tags).toBeDefined();
    });
  });

  // TODO: needs proper mocking
  describe.skip('MCP Integration', () => {
    it('should integrate with MCP tools', async () => {
      const configWithMCP = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "mcp-integrated-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "You have access to computational tools"
  user: "{{ input.query }}"
  mcp:
    servers:
      math:
        command: "python"
        args: ["-m", "mcp.math"]
      filesystem:
        command: "python"
        args: ["-m", "mcp.filesystem"]
    tool_filter:
      allow: ["calculator", "file_reader"]
    tool_prompt: "Use the available tools to help answer the user's question."
  output:
    result:
      type: "str"
      description: "Answer using available tools"
`;

      flatAgent = new FlatAgent(parseAgentConfig(configWithMCP));

      const mockResponse = {
        choices: [{
          message: {
            content: 'The calculation result is 42'
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      // Mock MCP tool calls
      const mockToolCall = vi.fn().mockResolvedValue({ result: 42 });

      const result = await flatAgent.call({
        query: 'What is 6 * 7?'
      });

      expect(result.output.result).toBe('The calculation result is 42');
    });

    it('should handle MCP tool failures gracefully', async () => {
      const configWithMCPTools = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "mcp-error-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Agent with tools"
  user: "{{ input.query }}"
  mcp:
    servers:
      test:
        command: "python"
        args: ["-m", "mcp.test"]
  output:
    result:
      type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(configWithMCPTools));

      const mockResponse = {
        choices: [{
          message: {
            content: 'I could not complete the operation due to tool errors'
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      // Mock tool failure
      const mockToolCall = vi.fn().mockRejectedValue(new Error('Tool connection failed'));

      const result = await flatAgent.call({
        query: 'Use the test tool'
      });

      expect(result.output.result).toBe('I could not complete the operation due to tool errors');
    });
  });

  // TODO: needs proper mocking
  describe.skip('Performance and Scalability', () => {
    it('should handle high-frequency calls efficiently', async () => {
      const simpleConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "performance-agent"
  model:
    name: "gpt-3.5-turbo"
    provider: "openai"
  system: "Quick response agent"
  user: "{{ input.query }}"
`;

      flatAgent = new FlatAgent(parseAgentConfig(simpleConfig));

      const mockResponse = {
        choices: [{ message: { content: 'Quick response' } }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const startTime = Date.now();
      const concurrentCalls = 10;

      const promises = Array.from({ length: concurrentCalls }, (_, i) =>
        flatAgent.call({ query: `test query ${i}` })
      );

      const results = await Promise.all(promises);
      const totalTime = Date.now() - startTime;

      expect(results).toHaveLength(concurrentCalls);
      results.forEach(result => {
        expect(result.output).toBeDefined();
      });

      // Should complete in reasonable time
      expect(totalTime).toBeLessThan(5000); // 5 seconds for 10 concurrent calls
    });

    it('should handle large context efficiently', async () => {
      const largeContextConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "large-context-agent"
  model:
    name: "gpt-4"
    provider: "openai"
    max_tokens: 2000
  system: "Process large documents"
  user: |
    Document: {{ input.large_document }}
    Question: {{ input.question }}
  output:
    summary:
      type: "str"
      description: "Document summary"
`;

      flatAgent = new FlatAgent(parseAgentConfig(largeContextConfig));

      const largeDocument = Array.from({ length: 100 }, (_, i) => 
        `This is paragraph ${i + 1} with some sample content that simulates a large document.`
      ).join('\n');

      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              summary: 'This document contains 100 paragraphs discussing various topics.'
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const startTime = Date.now();

      const result = await flatAgent.call({
        large_document: largeDocument,
        question: 'What is this document about?'
      });

      const totalTime = Date.now() - startTime;

      expect(result.output.summary).toBe('This document contains 100 paragraphs discussing various topics.');
      expect(totalTime).toBeLessThan(3000); // Should process large context efficiently
    });
  });

  // TODO: needs proper mocking
  describe.skip('Real-world Scenarios', () => {
    it('should handle customer service scenario', async () => {
      const customerServiceConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "customer-service-agent"
  model:
    name: "gpt-4"
    provider: "openai"
    temperature: 0.3
  system: |
    You are a customer service representative for a software company.
    Be helpful, professional, and solution-oriented.
  user: |
    Customer inquiry: {{ input.inquiry }}
    Customer account: {{ input.account_info }}
    Order history: {{ input.order_history }}
    Previous interactions: {{ input.previous_interactions }}
  output:
    response:
      type: "str"
      description: "Customer service response"
    sentiment:
      type: "str"
      description: "Customer sentiment analysis"
    escalation_needed:
      type: "bool"
      description: "Whether escalation to human agent is needed"
    follow_up_actions:
      type: "list"
      description: "Recommended follow-up actions"
      items:
        type: "str"
`;

      flatAgent = new FlatAgent(parseAgentConfig(customerServiceConfig));

      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              response: "I understand your concern about the billing issue. Let me help resolve this for you right away.",
              sentiment: "concerned but cooperative",
              escalation_needed: false,
              follow_up_actions: [
                "Review billing history for the disputed charge",
                "Process refund if charge is invalid",
                "Send confirmation email to customer"
              ]
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        inquiry: "I was charged twice for my monthly subscription",
        account_info: "Premium tier, customer since 2022",
        order_history: "Monthly billing on file, last charge: $29.99",
        previous_interactions: "Called yesterday about technical issues"
      });

      expect(result.output.response).toContain("billing issue");
      expect(result.output.escalation_needed).toBe(false);
      expect(result.output.follow_up_actions).toContain("Review billing history");
    });

    it('should handle code generation scenario', async () => {
      const codeGenerationConfig = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "code-generator-agent"
  model:
    name: "gpt-4"
    provider: "openai"
    temperature: 0.1
  system: |
    You are an expert software developer. Generate clean, well-documented code.
    Follow best practices and include error handling.
  user: |
    Programming task: {{ input.task }}
    Language: {{ input.language }}
    Requirements: {{ input.requirements }}
    Framework: {{ input.framework }}
  output:
    code:
      type: "str"
      description: "Generated source code"
    explanation:
      type: "str"
      description: "Explanation of the code"
    dependencies:
      type: "list"
      description: "Required dependencies"
      items:
        type: "object"
        properties:
          name:
            type: "str"
          version:
            type: "str"
          optional:
            type: "bool"
`;

      flatAgent = new FlatAgent(parseAgentConfig(codeGenerationConfig));

      const mockResponse = {
        choices: [{
          message: {
            content: JSON.stringify({
              code: `
function createApiClient(baseUrl) {
  const client = axios.create({
    baseURL: baseUrl,
    timeout: 5000,
    headers: {
      'Content-Type': 'application/json'
    }
  });

  // Request interceptor for API key
  client.interceptors.request.use((config) => {
    config.headers['X-API-Key'] = process.env.API_KEY;
    return config;
  });

  // Response interceptor for error handling
  client.interceptors.response.use(
    (response) => response,
    (error) => {
      console.error('API Error:', error.response?.data || error.message);
      return Promise.reject(error);
    }
  );

  return client;
}`,
              explanation: "This function creates an Axios HTTP client with proper configuration, including base URL, timeout, headers, and interceptors for API key authentication and error handling.",
              dependencies: [
                { name: "axios", version: "^1.0.0", optional: false },
                { name: "dotenv", version: "^16.0.0", optional: true }
              ]
            })
          }
        }]
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse)
      });

      const result = await flatAgent.call({
        task: "Create a reusable API client with authentication and error handling",
        language: "JavaScript",
        requirements: "Must support environment variables for configuration",
        framework: "Express.js"
      });

      expect(result.output.code).toContain("axios.create");
      expect(result.output.explanation).toContain("Axios");
      expect(result.output.dependencies).toHaveLength(2);
      expect(result.output.dependencies[0].name).toBe("axios");
    });
  });
});