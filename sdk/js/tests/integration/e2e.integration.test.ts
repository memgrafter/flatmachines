// e2e.integration.test.ts
// End-to-end integration tests for complete FlatAgents workflows

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { MemoryBackend } from '../src/persistence';
import { mkdirSync } from 'fs';
import * as yaml from 'yaml';

const parseAgentConfig = (config: string) => yaml.parse(config);
const parseMachineConfig = (config: string) => yaml.parse(config);

// TODO: Tests need rewrite - wrong mocking pattern (mock after instantiation)
describe.skip('End-to-End Workflow Integration Tests', () => {
  let memoryBackend: MemoryBackend;
  let tempDir: string;

  beforeEach(() => {
    vi.clearAllMocks();
    memoryBackend = new MemoryBackend();
    
    tempDir = `/tmp/flatagents-e2e-test-${Date.now()}`;
    try {
      mkdirSync(tempDir, { recursive: true });
    } catch (error) {
      // Directory might already exist
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Complete Data Processing Pipeline', () => {
    it('should execute full ETL pipeline with agents and machines', async () => {
      // Create extraction agent
      const extractAgent = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "data-extractor"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Extract and validate data from various sources"
  user: "Extract data from {{ input.source_type }} source: {{ input.source_config }}"
  output:
    extracted_data:
      type: "object"
      description: "Extracted raw data"
    validation_status:
      type: "str"
      description: "Data validation status"
    extraction_meta:
      type: "object"
      description: "Extraction metadata"
`;

      // Create transformation machine
      const transformMachine = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "transform-pipeline"
  context:
    transformation_log: []
    data_quality: {}
  states:
    start:
      type: "initial"
      agent: "data-transformer"
      input:
        raw_data: "{{ input.extracted_data }}"
        transform_rules: "{{ input.rules }}"
      output_to_context:
        transformed_data: "{{ output.processed_data }}"
        transformation_log: "{{ context.transformation_log.concat(['transform_applied']) }}"
      transitions:
        - to: "validate"
    validate:
      agent: "quality-validator"
      input:
        data: "{{ context.transformed_data }}"
        quality_checks: "{{ input.quality_checks }}"
      output_to_context:
        data_quality: "{{ output.quality_report }}"
        transformation_log: "{{ context.transformation_log.concat(['validated']) }}"
      transitions:
        - condition: "context.data_quality.overall_score >= 0.8"
          to: "enrich"
        - to: "fix_quality"
    fix_quality:
      agent: "quality-improver"
      input:
        data: "{{ context.transformed_data }}"
        issues: "{{ context.data_quality.issues }}"
      output_to_context:
        transformed_data: "{{ output.improved_data }}"
        data_quality: "{{ output.new_quality_report }}"
        transformation_log: "{{ context.transformation_log.concat(['quality_fixed']) }}"
      transitions:
        - to: "validate"
    enrich:
      agent: "data-enricher"
      input:
        base_data: "{{ context.transformed_data }}"
        enrichment_sources: "{{ input.enrichment_config }}"
      output_to_context:
        final_data: "{{ output.enriched_data }}"
        transformation_log: "{{ context.transformation_log.concat(['enriched']) }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        processed_data: "{{ context.final_data }}"
        quality_metrics: "{{ context.data_quality }}"
        transformation_history: "{{ context.transformation_log }}"
`;

      // Create loading agent
      const loadAgent = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "data-loader"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Load processed data to target destination"
  user: "Load data to {{ target.destination }} using {{ target.method }}"
  mcp:
    servers:
      database:
        command: "python"
        args: ["-m", "mcp.database"]
    tool_filter:
      allow: ["connect_db", "insert_batch", "create_table"]
  output:
    load_status:
      type: "object"
      description: "Loading operation status"
    records_loaded:
      type: "float"
      description: "Number of records successfully loaded"
    destination_info:
      type: "object"
      description: "Target destination information"
`;

      // Mock all agent and machine executions
      const mockExtractAgent = {
        output: {
          extracted_data: {
            records: Array.from({ length: 100 }, (_, i) => ({
              id: i,
              customer_name: `Customer_${i}`,
              email: `customer${i}@example.com`,
              purchase_amount: Math.floor(Math.random() * 1000)
            })),
            source: 'csv_export',
            timestamp: new Date().toISOString()
          },
          validation_status: 'valid',
          extraction_meta: { records_count: 100, source_size: '25KB' }
        }
      };

      const mockTransformMachine = {
        output: {
          processed_data: {
            records: Array.from({ length: 98 }, (_, i) => ({
              id: i,
              customer_name: `Customer_${i}_normalized`,
              email: `customer${i}@example.com`,
              purchase_amount: Math.floor(Math.random() * 1000),
              customer_segment: ['premium', 'standard', 'basic'][i % 3],
              processed_at: new Date().toISOString()
            })),
            processed_count: 98,
            quality_score: 0.92
          },
          quality_metrics: {
            overall_score: 0.92,
            completeness: 0.98,
            accuracy: 0.95,
            consistency: 0.90
          },
          transformation_history: ['transform_applied', 'validated', 'enriched']
        }
      };

      const mockLoadAgent = {
        output: {
          load_status: {
            status: 'success',
            connection: 'database_connected',
            batch_size: 50,
            total_batches: 2
          },
          records_loaded: 98,
          destination_info: {
            database: 'customers_db',
            table: 'processed_customers',
            location: 'postgresql://prod-db:5432/analytics'
          }
        }
      };

      // Mock the FlatAgent and FlatMachine constructors and execute methods
      vi.mock('../src/flatagent', () => ({
        FlatAgent: vi.fn().mockImplementation(() => ({
          call: vi.fn().mockResolvedValue(mockExtractAgent)
        }))
      }));

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockTransformMachine)
        }))
      }));

      // Load agent for the final step
      const LoadAgentClass = (await import('../src/flatagent')).FlatAgent;
      const loadAgentInstance = new LoadAgentClass(parseAgentConfig(loadAgent));
      vi.spyOn(loadAgentInstance, 'call').mockResolvedValue(mockLoadAgent);

      // Execute the complete ETL pipeline
      const extractAgentInstance = new (await import('../src/flatagent')).FlatAgent(parseAgentConfig(extractAgent));
      const extractResult = await extractAgentInstance.call({
        source_type: 'csv_file',
        source_config: { path: '/data/customers.csv', format: 'csv' }
      });

      expect(extractResult.output.validation_status).toBe('valid');
      expect(extractResult.output.extracted_data.records).toHaveLength(100);

      const transformMachineInstance = new (await import('../src/flatmachine')).FlatMachine({ config: parseMachineConfig(transformMachine) });
      const transformResult = await transformMachineInstance.execute({
        extracted_data: extractResult.output.extracted_data,
        rules: { normalize_names: true, validate_emails: true },
        quality_checks: { completeness: 0.9, accuracy: 0.9 },
        enrichment_config: { add_segments: true, calculate_rfm: false }
      });

      expect(transformResult.output.processed_data.processed_count).toBe(98);
      expect(transformResult.output.quality_metrics.overall_score).toBe(0.92);
      expect(transformResult.output.transformation_history).toHaveLength(3);

      const loadResult = await loadAgentInstance.call({
        target: {
          destination: 'customers_db.processed_customers',
          method: 'batch_insert'
        },
        processed_data: transformResult.output.processed_data
      });

      expect(loadResult.output.records_loaded).toBe(98);
      expect(loadResult.output.load_status.status).toBe('success');
      expect(loadResult.output.destination_info.table).toBe('processed_customers');

      // Verify the complete pipeline result
      const pipelineSummary = {
        extraction: {
          records_extracted: extractResult.output.extracted_data.records.length,
          status: extractResult.output.validation_status
        },
        transformation: {
          records_processed: transformResult.output.processed_data.processed_count,
          quality_score: transformResult.output.quality_metrics.overall_score,
          steps: transformResult.output.transformation_history.length
        },
        loading: {
          records_loaded: loadResult.output.records_loaded,
          destination: loadResult.output.destination_info.table
        }
      };

      expect(pipelineSummary.extraction.records_extracted).toBe(100);
      expect(pipelineSummary.transformation.records_processed).toBe(98);
      expect(pipelineSummary.loading.records_loaded).toBe(98);
    });
  });

  describe('Customer Service Automation Workflow', () => {
    it('should complete full customer service ticket lifecycle', async () => {
      // Ticket creation agent
      const ticketAgent = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "ticket-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Create and categorize customer service tickets"
  user: "Create ticket from: {{ input.customer_request }}"
  output:
    ticket:
      type: "object"
      description: "Created ticket details"
    category:
      type: "str"
      description: "Ticket category"
    priority:
      type: "str"
      description: "Ticket priority level"
`;

      // Processing machine
      const processingMachine = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "ticket-processing-machine"
  context:
    processing_steps: []
    customer_data: {}
  states:
    start:
      type: "initial"
      agent: "ticket-analyzer"
      input:
        ticket: "{{ input.ticket }}"
      output_to_context:
        customer_data: "{{ output.customer_profile }}"
        processing_steps: "{{ context.processing_steps.concat(['analyzed']) }}"
      transitions:
        - to: "route"
    route:
      agent: "ticket-router"
      input:
        ticket_data: "{{ context.customer_data }}"
        category: "{{ input.category }}"
        priority: "{{ input.priority }}"
      output_to_context:
        routing_decision: "{{ output.route_to }}"
        processing_steps: "{{ context.processing_steps.concat(['routed']) }}"
      transitions:
        - condition: "context.routing_decision == 'auto_reply'"
          to: "auto_reply"
        - to: "human_queue"
    auto_reply:
      agent: "auto-responder"
      input:
        customer_data: "{{ context.customer_data }}"
        ticket_content: "{{ input.original_request }}"
      output_to_context:
        auto_response: "{{ output.response }}"
        processing_steps: "{{ context.processing_steps.concat(['auto_responded']) }}"
        sentiment: "{{ output.sentiment_analysis }}"
      transitions:
        - condition: "context.sentiment.satisfaction >= 0.7"
          to: "close_ticket"
        - to: "human_queue"
    human_queue:
      agent: "human-routing"
      input:
        ticket_id: "{{ input.ticket.id }}"
        urgency: "{{ context.routing_decision }}"
      output_to_context:
        human_assignment: "{{ output.assigned_agent }}"
        estimated_response: "{{ output.response_time }}"
        processing_steps: "{{ context.processing_steps.concat(['human_assigned']) }}"
      transitions:
        - to: "await_human"
    await_human:
      type: "final"
      output:
        status: "awaiting_human_response"
        assigned_agent: "{{ context.human_assignment }}"
        response_eta: "{{ context.estimated_response }}"
        processing_history: "{{ context.processing_steps }}"
    close_ticket:
      agent: "ticket-closer"
      input:
        resolution: "{{ context.auto_response }}"
        customer_satisfaction: "{{ context.sentiment.satisfaction }}"
      output_to_context:
        closure_summary: "{{ output.summary }}"
      transitions:
        - to: "completed"
    completed:
      type: "final"
      output:
        status: "resolved"
        summary: "{{ context.closure_summary }}"
        processing_history: "{{ context.processing_steps }}"
`;

      // Follow-up agent
      const followupAgent = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "followup-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Create follow-up actions and surveys"
  user: "Create follow-up for: {{ input.ticket_summary }}"
  mcp:
    servers:
      email:
        command: "python"
        args: ["-m", "mcp.email"]
      survey:
        command: "python"
        args: ["-m", "mcp.survey"]
  output:
    followup_actions:
      type: "list"
      description: "Follow-up actions created"
    survey_sent:
      type: "bool"
      description: "Whether satisfaction survey was sent"
    next_contact:
      type: "str"
      description: "Next scheduled contact time"
`;

      // Mock the workflow components
      const mockTicketResult = {
        output: {
          ticket: {
            id: 'TKT-2023-001',
            customer_id: 'CUST-123',
            subject: 'Billing inquiry',
            created_at: new Date().toISOString()
          },
          category: 'billing',
          priority: 'medium'
        }
      };

      const mockProcessingResult = {
        output: {
          status: 'resolved',
          summary: {
            ticket_id: 'TKT-2023-001',
            resolution_type: 'automated',
            customer_satisfied: true,
            resolution_time: '5 minutes'
          },
          processing_history: ['analyzed', 'routed', 'auto_responded', 'resolved']
        }
      };

      const mockFollowupResult = {
        output: {
          followup_actions: [
            'send_thank_you_email',
            'schedule_billing_review_call',
            'add_to_newsletter_list'
          ],
          survey_sent: true,
          next_contact: '2024-01-20T14:00:00Z'
        }
      };

      // Mock all the constructors and execution
      vi.mock('../src/flatagent', () => ({
        FlatAgent: vi.fn().mockImplementation(() => ({
          call: vi.fn().mockResolvedValue(mockTicketResult)
        }))
      }));

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockProcessingResult)
        }))
      }));

      // Execute the complete customer service workflow
      const ticketAgentInstance = new (await import('../src/flatagent')).FlatAgent(parseAgentConfig(ticketAgent));
      const ticketResult = await ticketAgentInstance.call({
        customer_request: 'I was charged twice for my monthly subscription. Can you help me resolve this?'
      });

      expect(ticketResult.output.ticket.id).toBe('TKT-2023-001');
      expect(ticketResult.output.category).toBe('billing');

      const processingMachineInstance = new (await import('../src/flatmachine')).FlatMachine({ config: parseMachineConfig(processingMachine) });
      const processingResult = await processingMachineInstance.execute({
        ticket: ticketResult.output.ticket,
        category: ticketResult.output.category,
        priority: ticketResult.output.priority,
        original_request: 'I was charged twice for my monthly subscription. Can you help me resolve this?'
      });

      expect(processingResult.output.status).toBe('resolved');
      expect(processingResult.output.processing_history).toContain('auto_responded');

      // Mock followup agent separately
      const FollowupAgentClass = (await import('../src/flatagent')).FlatAgent;
      const followupAgentInstance = new FollowupAgentClass(parseAgentConfig(followupAgent));
      vi.spyOn(followupAgentInstance, 'call').mockResolvedValue(mockFollowupResult);

      const followupResult = await followupAgentInstance.call({
        ticket_summary: processingResult.output.summary
      });

      expect(followupResult.output.followup_actions).toHaveLength(3);
      expect(followupResult.output.survey_sent).toBe(true);

      // Complete workflow summary
      const workflowSummary = {
        ticket_created: {
          id: ticketResult.output.ticket.id,
          category: ticketResult.output.category
        },
        processing_complete: {
          status: processingResult.output.status,
          steps: processingResult.output.processing_history.length
        },
        followup_scheduled: {
          actions_count: followupResult.output.followup_actions.length,
          survey_sent: followupResult.output.survey_sent
        }
      };

      expect(workflowSummary.ticket_created.category).toBe('billing');
      expect(workflowSummary.processing_complete.status).toBe('resolved');
      expect(workflowSummary.followup_scheduled.survey_sent).toBe(true);
    });
  });

  describe('Real-time Monitoring and Alerting System', () => {
    it('should handle real-time monitoring with automated responses', async () => {
      // Monitoring agent
      const monitoringAgent = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "monitoring-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Monitor system metrics and detect anomalies"
  user: "Analyze metrics: {{ input.system_metrics }}"
  mcp:
    servers:
      metrics:
        command: "python"
        args: ["-m", "mcp.metrics"]
      alerts:
        command: "python"
        args: ["-m", "mcp.alerts"]
  output:
    anomaly_detected:
      type: "bool"
      description: "Whether anomalies were detected"
    health_status:
      type: "str"
      description: "Overall system health status"
    metrics_summary:
      type: "object"
      description: "Summary of key metrics"
`;

      // Alert response machine
      const alertResponseMachine = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "alert-response-machine"
  persistence:
    enabled: true
    backend: "memory"
  context:
    response_log: []
    escalation_level: 0
  states:
    start:
      type: "initial"
      agent: "alert-processor"
      input:
        alert: "{{ input.alert_data }}"
        metrics: "{{ input.metrics_summary }}"
      output_to_context:
        response_log: "{{ context.response_log.concat(['alert_received']) }}"
        escalation_level: "{{ context.escalation_level + 1 }}"
      transitions:
        - condition: "input.alert_data.severity == 'critical'"
          to: "critical_response"
        - condition: "input.alert_data.severity == 'high'"
          to: "high_severity_response"
        - to: "low_severity_response"
    critical_response:
      launch: ["emergency_notification", "auto_recovery"]
      launch_input:
        alert: "{{ input.alert_data }}"
        immediate_action: true
      action: "escalate_to_oncall"
      output_to_context:
        response_log: "{{ context.response_log.concat(['critical_escalation']) }}"
      transitions:
        - to: "monitor_recovery"
    high_severity_response:
      launch: "notification_system"
      launch_input:
        alert: "{{ input.alert_data }}"
        priority: "high"
      action: "attempt_auto_fix"
      output_to_context:
        response_log: "{{ context.response_log.concat(['high_priority_action']) }}"
      transitions:
        - to: "monitor_recovery"
    low_severity_response:
      action: "log_and_monitor"
      output_to_context:
        response_log: "{{ context.response_log.concat(['logged']) }}"
      transitions:
        - to: "monitor_recovery"
    monitor_recovery:
      agent: "recovery_monitor"
      input:
        original_alert: "{{ input.alert_data }}"
        escalation_level: "{{ context.escalation_level }}"
      output_to_context:
        recovery_status: "{{ output.recovery_result }}"
        response_log: "{{ context.response_log.concat(['monitored']) }}"
      transitions:
        - condition: "context.recovery_status.resolved == true"
          to: "resolved"
        - condition: "context.escalation_level < 3"
          to: "escalate_further"
        - to: "escalate_max"
    escalate_further:
      action: "increase_escalation"
      output_to_context:
        escalation_level: "{{ context.escalation_level + 1 }}"
        response_log: "{{ context.response_log.concat(['escalated']) }}"
      transitions:
        - to: "monitor_recovery"
    escalate_max:
      type: "final"
      output:
        status: "escalated_to_maximum"
        final_escalation_level: "{{ context.escalation_level }}"
        response_history: "{{ context.response_log }}"
    resolved:
      type: "final"
      output:
        status: "resolved"
        recovery_summary: "{{ context.recovery_status }}"
        response_history: "{{ context.response_log }}"
`;

      // Resolution agent
      const resolutionAgent = `
spec: flatagent
spec_version: "0.6.0"
data:
  name: "resolution-agent"
  model:
    name: "gpt-4"
    provider: "openai"
  system: "Generate resolution report and improvement recommendations"
  user: "Create report for: {{ input.incident_summary }}"
  mcp:
    servers:
      reporting:
        command: "python"
        args: ["-m", "mcp.reporting"]
      analytics:
        command: "python"
        args: ["-m", "mcp.analytics"]
  output:
    incident_report:
      type: "object"
      description: "Detailed incident report"
    recommendations:
      type: "list"
      description: "Improvement recommendations"
      items:
        type: "str"
    postmortem_actions:
      type: "list"
      description: "Actions to prevent recurrence"
      items:
        type: "str"
`;

      // Mock monitoring and alerting workflow
      const mockMonitoringResult = {
        output: {
          anomaly_detected: true,
          health_status: 'degraded',
          metrics_summary: {
            cpu_usage: 95,
            memory_usage: 87,
            response_time: 2500,
            error_rate: 8.5
          }
        }
      };

      const mockAlertResponse = {
        output: {
          status: 'resolved',
          recovery_summary: {
            resolved: true,
            resolution_time: '15 minutes',
            root_cause: 'High CPU usage due to database query',
            auto_recovery_success: true
          },
          response_history: ['alert_received', 'critical_escalation', 'monitored', 'resolved']
        }
      };

      const mockResolutionResult = {
        output: {
          incident_report: {
            incident_id: 'INC-2023-042',
            severity: 'critical',
            duration: '15 minutes',
            impact: 'High-latency responses for 25% of users',
            root_cause: 'Database query optimization required'
          },
          recommendations: [
            'Implement database query optimization',
            'Add CPU usage threshold alerts',
            'Deploy auto-scaling based on CPU metrics'
          ],
          postmortem_actions: [
            'Update database indexes',
            'Add resource monitoring dashboard',
            'Conduct quarterly performance reviews'
          ]
        }
      };

      // Mock constructors and executions
      vi.mock('../src/flatagent', () => ({
        FlatAgent: vi.fn().mockImplementation(() => ({
          call: vi.fn().mockResolvedValue(mockMonitoringResult)
        }))
      }));

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockAlertResponse)
        }))
      }));

      // Execute the complete monitoring workflow
      const monitoringAgentInstance = new (await import('../src/flatagent')).FlatAgent(parseAgentConfig(monitoringAgent));
      const monitoringResult = await monitoringAgentInstance.call({
        system_metrics: {
          servers: [
            { id: 'web-01', cpu: 95, memory: 87, status: 'degraded' },
            { id: 'db-01', cpu: 78, memory: 65, status: 'normal' }
          ],
          network: { latency: 2500, packet_loss: 0.1 }
        }
      });

      expect(monitoringResult.output.anomaly_detected).toBe(true);
      expect(monitoringResult.output.health_status).toBe('degraded');
      expect(monitoringResult.output.metrics_summary.cpu_usage).toBe(95);

      const alertResponseMachineInstance = new (await import('../src/flatmachine')).FlatMachine({
        config: parseMachineConfig(alertResponseMachine),
        persistence: memoryBackend
      });
      const alertResult = await alertResponseMachineInstance.execute({
        alert_data: {
          id: 'ALERT-123',
          severity: 'critical',
          message: 'High CPU usage detected on web-01',
          timestamp: new Date().toISOString()
        },
        metrics_summary: monitoringResult.output.metrics_summary
      });

      expect(alertResult.output.status).toBe('resolved');
      expect(alertResult.output.recovery_summary.auto_recovery_success).toBe(true);
      expect(alertResult.output.response_history).toHaveLength(4);

      // Mock resolution agent
      const ResolutionAgentClass = (await import('../src/flatagent')).FlatAgent;
      const resolutionAgentInstance = new ResolutionAgentClass(parseAgentConfig(resolutionAgent));
      vi.spyOn(resolutionAgentInstance, 'call').mockResolvedValue(mockResolutionResult);

      const resolutionResult = await resolutionAgentInstance.call({
        incident_summary: {
          incident_id: 'INC-2023-042',
          duration: '15 minutes',
          root_cause: 'Database query optimization required'
        }
      });

      expect(resolutionResult.output.incident_report.severity).toBe('critical');
      expect(resolutionResult.output.recommendations).toHaveLength(3);
      expect(resolutionResult.output.postmortem_actions).toContain('Update database indexes');

      // Complete monitoring workflow summary
      const workflowSummary = {
        monitoring: {
          anomalies_detected: monitoringResult.output.anomaly_detected,
          health_status: monitoringResult.output.health_status
        },
        response: {
          incident_resolved: alertResult.output.status,
          response_steps: alertResult.output.response_history.length,
          recovery_time: alertResult.output.recovery_summary.resolution_time
        },
        resolution: {
          recommendations_created: resolutionResult.output.recommendations.length,
          postmortem_actions: resolutionResult.output.postmortem_actions.length
        }
      };

      expect(workflowSummary.monitoring.anomalies_detected).toBe(true);
      expect(workflowSummary.response.incident_resolved).toBe('resolved');
      expect(workflowSummary.resolution.recommendations_created).toBe(3);
    });
  });

  describe('Complex Multi-System Integration', () => {
    it('should orchestrate multiple systems with persistence and error recovery', async () => {
      // Create a complex workflow that integrates everything
      const orchestrationMachine = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "orchestration-machine"
  persistence:
    enabled: true
    backend: "memory"
  context:
    system_status: {}
    integration_points: []
    error_count: 0
  states:
    initialize:
      type: "initial"
      action: "setup_integration_environment"
      output_to_context:
        system_status: "{{ context.system_status }}"
        integration_points: "{{ context.integration_points.concat(['database', 'api', 'messaging']) }}"
      transitions:
        - to: "coordinate_systems"
    coordinate_systems:
      machine: ["database_system", "api_system", "messaging_system"]
      input:
        config: "{{ input.system_config }}"
        context: "{{ context }}"
      mode: "settled"
      timeout: 30
      output_to_context:
        system_status: "{{ output }}"
        integration_points: "{{ context.integration_points.concat(['systems_initialized']) }}"
      on_error: "handle_system_error"
      transitions:
        - condition: "output.database.status == 'ready' and output.api.status == 'ready' and output.messaging.status == 'ready'"
          to: "orchestrate_workflows"
        - to: "troubleshoot"
    orchestrate_workflows:
      foreach: "{{ input.workflows }}"
      as: "workflow"
      key: "{{ workflow.id }}"
      machine: "workflow_executor"
      input:
        workflow_def: "{{ input.workflow }}"
        system_context: "{{ context.system_status }}"
      output_to_context:
        integration_points: "{{ context.integration_points.concat([workflow.id + '_completed']) }}"
      transitions:
        - to: "aggregate_results"
    handle_system_error:
      agent: "error_handler"
      input:
        error: "{{ context.last_error }}"
        affected_system: "{{ context.failed_system }}"
      output_to_context:
        error_count: "{{ context.error_count + 1 }}"
        recovery_attempt: "{{ output.recovery_action }}"
      transitions:
        - condition: "context.error_count < 3"
          to: "coordinate_systems"
        - to: "escalate_failure"
    troubleshoot:
      agent: "troubleshooter"
      input:
        system_status: "{{ context.system_status }}"
        integration_points: "{{ context.integration_points }}"
      output_to_context:
        troubleshoot_report: "{{ output.diagnosis }}"
      transitions:
        - condition: "output.diagnosis.fixable"
          to: "coordinate_systems"
        - to: "escalate_failure"
    aggregate_results:
      agent: "result_aggregator"
      input:
        workflow_results: "{{ context.workflow_results }}"
        system_performance: "{{ context.system_status }}"
      output_to_context:
        final_results: "{{ output.aggregated_data }}"
        integration_points: "{{ context.integration_points.concat(['aggregation_complete']) }}"
      transitions:
        - to: "complete"
    escalate_failure:
      type: "final"
      output:
        status: "failed"
        error_count: "{{ context.error_count }}"
        last_error: "{{ context.last_error }}"
        integration_progress: "{{ context.integration_points }}"
    complete:
      type: "final"
      output:
        status: "success"
        final_results: "{{ context.final_results }}"
        systems_integrated: "{{ context.integration_points }}"
        total_errors: "{{ context.error_count }}"
`;

      // Mock the complex orchestration
      const mockOrchestrationResult = {
        output: {
          status: 'success',
          final_results: {
            total_workflows_processed: 15,
            success_rate: 0.93,
            performance_metrics: {
              average_response_time: 450,
              throughput_per_second: 1250,
              resource_utilization: 0.78
            },
            data_processed: {
              records: 50000,
              data_volume: '2.5GB',
              processing_time: '45 minutes'
            }
          },
          systems_integrated: [
            'database', 'api', 'messaging', 'systems_initialized',
            'workflow_1_completed', 'workflow_2_completed', 'workflow_3_completed',
            'workflow_4_completed', 'workflow_5_completed', 'aggregation_complete'
          ],
          total_errors: 0
        },
        executionId: 'complex-orchestration-execution',
        states: [
          'initialize', 'coordinate_systems', 'orchestrate_workflows',
          'aggregate_results', 'complete'
        ]
      };

      // Mock FlatMachine constructor and execution
      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockOrchestrationResult)
        }))
      }));

      // Execute the complex orchestration
      const orchestrationMachineInstance = new (await import('../src/flatmachine')).FlatMachine({
        config: parseMachineConfig(orchestrationMachine),
        persistence: memoryBackend
      });

      const workflows = [
        {
          id: 'workflow_1',
          type: 'data_processing',
          priority: 'high',
          steps: ['extract', 'transform', 'load']
        },
        {
          id: 'workflow_2',
          type: 'api_integration',
          priority: 'medium',
          steps: ['authenticate', 'fetch', 'process']
        },
        {
          id: 'workflow_3',
          type: 'messaging',
          priority: 'low',
          steps: ['queue', 'process', 'notify']
        },
        {
          id: 'workflow_4',
          type: 'analytics',
          priority: 'medium',
          steps: ['collect', 'analyze', 'report']
        },
        {
          id: 'workflow_5',
          type: 'monitoring',
          priority: 'high',
          steps: ['monitor', 'alert', 'respond']
        }
      ];

      const result = await orchestrationMachineInstance.execute({
        system_config: {
          database: { host: 'db-prod', port: 5432, replicas: 3 },
          api: { gateway: 'api-gateway', rate_limit: 1000 },
          messaging: { broker: 'kafka', topics: ['events', 'commands'] }
        },
        workflows: workflows
      });

      // Verify the complex orchestration completed successfully
      expect(result.output.status).toBe('success');
      expect(result.output.final_results.total_workflows_processed).toBe(15);
      expect(result.output.final_results.success_rate).toBe(0.93);
      expect(result.output.systems_integrated).toContain('database');
      expect(result.output.systems_integrated).toContain('aggregation_complete');
      expect(result.output.total_errors).toBe(0);
      expect(result.executionId).toBe('complex-orchestration-execution');

      // Verify integration completeness
      const integrationSummary = {
        systems_coordinated: ['database', 'api', 'messaging'],
        workflows_orchestrated: 5,
        total_steps: result.states.length,
        persistence_enabled: true,
        error_recovery_capacity: true,
        final_performance: result.output.final_results.performance_metrics
      };

      expect(integrationSummary.systems_coordinated).toHaveLength(3);
      expect(integrationSummary.workflows_orchestrated).toBe(5);
      expect(integrationSummary.total_steps).toBe(5);
      expect(integrationSummary.final_performance.average_response_time).toBe(450);
    });
  });

  describe('Performance and Scalability Integration', () => {
    it('should handle high-volume concurrent operations efficiently', async () => {
      const concurrentProcessingMachine = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "concurrent-processing-machine"
  context:
    concurrent_operations: []
    performance_metrics: {}
  states:
    start:
      type: "initial"
      launch: ["processor_a", "processor_b", "processor_c", "processor_d", "processor_e"]
      launch_input:
        workload: "{{ input.workload_size }}"
        batch_size: "{{ input.batch_size }}"
      action: "monitor_performance"
      output_to_context:
        concurrent_operations: "{{ context.concurrent_operations.concat(['launched_5_processors']) }}"
        performance_metrics: "{{ context.performance_metrics }}"
      transitions:
        - to: "monitor_progress"
    monitor_progress:
      machine: "progress_monitor"
      input:
        active_processors: 5
        total_workload: "{{ input.workload_size }}"
      mode: "any"
      timeout: 60
      output_to_context:
        performance_metrics: "{{ context.performance_metrics }}"
        concurrent_operations: "{{ context.concurrent_operations.concat(['monitoring_active']) }}"
      transitions:
        - condition: "output.completion_rate >= 0.95"
          to: "finalize"
        - to: "handle_slowdown"
    handle_slowdown:
      launch: "performance_optimizer"
      launch_input:
        current_metrics: "{{ context.performance_metrics }}"
        optimization_target: "speed"
      output_to_context:
        concurrent_operations: "{{ context.concurrent_operations.concat(['optimization_applied']) }}"
      transitions:
        - to: "monitor_progress"
    finalize:
      agent: "results_collector"
      input:
        performance_data: "{{ context.performance_metrics }}"
        operations_log: "{{ context.concurrent_operations }}"
      output_to_context:
        final_performance: "{{ output.performance_summary }}"
        efficiency_score: "{{ output.efficiency_score }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        performance_summary: "{{ context.final_performance }}"
        efficiency_score: "{{ context.efficiency_score }}"
        operations_completed: "{{ context.concurrent_operations.length }}"
`;

      // Mock high-performance execution
      const mockPerformanceResult = {
        output: {
          performance_summary: {
            total_operations: 50000,
            completion_rate: 0.98,
            average_response_time: 220,
            throughput_per_second: 2500,
            resource_efficiency: 0.92,
            error_rate: 0.001
          },
          efficiency_score: 0.95,
          operations_completed: 7 // launched_5_processors + monitoring_active + optimization_applied + finalize + complete
        },
        executionId: 'high-performance-execution',
        states: ['start', 'monitor_progress', 'finalize', 'complete']
      };

      // Mock with performance tracking
      const startTime = Date.now();
      
      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockPerformanceResult)
        }))
      }));

      const concurrentMachineInstance = new (await import('../src/flatmachine')).FlatMachine({
        config: parseMachineConfig(concurrentProcessingMachine),
        persistence: memoryBackend
      });

      const result = await concurrentMachineInstance.execute({
        workload_size: 50000,
        batch_size: 1000
      });

      const executionTime = Date.now() - startTime;

      // Verify performance and efficiency
      expect(result.output.performance_summary.total_operations).toBe(50000);
      expect(result.output.performance_summary.completion_rate).toBe(0.98);
      expect(result.output.efficiency_score).toBe(0.95);
      expect(result.executionId).toBe('high-performance-execution');
      
      // Should complete efficiently (under 5 seconds for this mock)
      expect(executionTime).toBeLessThan(5000);
      
      // Verify concurrent operation handling
      expect(result.output.operations_completed).toBeGreaterThan(5);
    });
  });
});