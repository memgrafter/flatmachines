import { MachineGraph } from './graph';

export interface UIAdapter<T> {
  render(graph: MachineGraph, options?: Record<string, any>): T;
}
