/**
 * MockLLMBackend — mock backend for testing.
 *
 * Provides predictable responses for testing without hitting real APIs.
 */

import { LLMBackend, LLMOptions, Message } from './types';

export interface MockResponse {
  content: string;
  raw?: any;
}

export class MockLLMBackend implements LLMBackend {
  totalCost = 0;
  totalApiCalls = 0;

  private responses: MockResponse[];
  private responseIndex = 0;
  private defaultResponse: MockResponse;

  /**
   * Create a mock backend with predefined responses.
   *
   * @param responses - Array of responses to return in order
   * @param defaultResponse - Response to use when responses are exhausted
   */
  constructor(
    responses: MockResponse[] = [],
    defaultResponse: MockResponse = { content: '{"result": "mock"}' }
  ) {
    this.responses = responses;
    this.defaultResponse = defaultResponse;
  }

  async call(messages: Message[], options?: LLMOptions): Promise<string> {
    this.totalApiCalls++;

    if (this.responseIndex < this.responses.length) {
      return this.responses[this.responseIndex++]!.content;
    }

    return this.defaultResponse.content;
  }

  async callRaw(messages: Message[], options?: LLMOptions): Promise<any> {
    this.totalApiCalls++;

    const response = this.responseIndex < this.responses.length
      ? this.responses[this.responseIndex++]
      : this.defaultResponse;

    return response?.raw ?? { text: response?.content };
  }

  /**
   * Reset the response index to start from the beginning.
   */
  reset(): void {
    this.responseIndex = 0;
    this.totalApiCalls = 0;
    this.totalCost = 0;
  }

  /**
   * Add responses to the queue.
   */
  addResponses(responses: MockResponse[]): void {
    this.responses.push(...responses);
  }
}