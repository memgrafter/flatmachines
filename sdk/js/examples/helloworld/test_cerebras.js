#!/usr/bin/env node

// Simple test script for cerebras API
import { createOpenAI } from '@ai-sdk/openai';

async function testCerebras() {
  console.log('Testing cerebras API...');
  
  try {
    // Test 1: Check environment variables
    const apiKey = process.env.CEREBRAS_API_KEY || process.env.OPENAI_API_KEY;
    if (!apiKey) {
      console.error('❌ No API key found. Set CEREBRAS_API_KEY or OPENAI_API_KEY');
      process.exit(1);
    }
    
    console.log('✅ API key found');
    
    // Test 2: Create cerebras client
    const cerebras = createOpenAI({ 
      baseURL: 'https://api.cerebras.ai/v1',
      apiKey: apiKey
    });
    console.log('✅ Cerebras client created');
    
    // Test 3: List models
    const { generateText } = await import('ai');
    
    const result = await generateText({
      model: cerebras('zai-glm-4.6'),
      prompt: 'Say "Hello from Cerebras!" and nothing else.',
      maxTokens: 64,
    });
    
    console.log('✅ API call successful');
    console.log('Response:', result.text);
    
  } catch (error) {
    console.error('❌ Error:', error.message);
    console.error('Full error:', error);
    process.exit(1);
  }
}

testCerebras();