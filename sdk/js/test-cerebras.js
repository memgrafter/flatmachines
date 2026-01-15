import { createOpenAI } from '@ai-sdk/openai';

async function testCerebras() {
  try {
    const openai = createOpenAI({ 
      baseURL: 'https://api.cerebras.ai/v1',
      apiKey: process.env.CEREBRAS_API_KEY || 'test-key'
    });
    
    console.log('Testing cerebras API...');
    const model = openai('zai-glm-4.6');
    console.log('Model created:', model);
    
    const { text } = await model.generateText({
      prompt: 'Say "hello"'
    });
    console.log('Response:', text);
  } catch (error) {
    console.error('Error:', error.message);
  }
}

testCerebras();