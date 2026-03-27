export function taskConfig(): Record<string, any> {
  return {
    spec: 'flatmachine',
    spec_version: '2.0.0',
    data: {
      name: 'dfss-task-runner',
      context: {
        task_id: 'input.task_id',
        root_id: 'input.root_id',
        depth: 'input.depth',
        resource_class: 'input.resource_class',
        has_expensive_descendant: 'input.has_expensive_descendant',
        distance_to_nearest_slow_descendant: 'input.distance_to_nearest_slow_descendant',
        children: [],
        result: null,
      },
      states: {
        start: {
          type: 'initial',
          transitions: [{ to: 'execute_task' }],
        },
        execute_task: {
          action: 'run_task',
          on_error: 'error_exit',
          transitions: [{ to: 'done' }],
        },
        done: {
          type: 'final',
          output: {
            task_id: 'context.task_id',
            root_id: 'context.root_id',
            depth: 'context.depth',
            resource_class: 'context.resource_class',
            result: 'context.result',
            children: 'context.children',
          },
        },
        error_exit: {
          type: 'final',
          output: {
            task_id: 'context.task_id',
            root_id: 'context.root_id',
            error: 'context.last_error',
          },
        },
      },
    },
  };
}
