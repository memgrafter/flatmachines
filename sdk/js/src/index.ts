/**
 * Legacy barrel export — re-exports everything from both packages.
 *
 * New consumers should import from:
 *   @anthropic/flatagents   — agent-level SDK
 *   @anthropic/flatmachines — orchestration SDK (also re-exports flatagents)
 *
 * This file maintains backward compatibility for existing imports from
 * the monolithic @memgrafter/flatagents package.
 */

// Re-export everything from flatmachines (which already re-exports flatagents)
export * from '@anthropic/flatmachines';
