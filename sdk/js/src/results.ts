import { ResultBackend } from './types';

const store = new Map<string, any>();

export const inMemoryResultBackend: ResultBackend = {
  async write(uri, data) { 
    store.set(uri, data); 
  },
  
  async read(uri, opts) {
    if (opts?.block) {
      const deadline = Date.now() + (opts.timeout ?? 30000);
      while (!store.has(uri) && Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 100));
      }
    }
    return store.get(uri);
  },
  
  async exists(uri) { 
    return store.has(uri); 
  },
  
  async delete(uri) { 
    store.delete(uri); 
  },
};