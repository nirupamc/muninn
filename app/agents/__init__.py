"""Agent launch integration for Munin (M8.3B).

This module provides the universal agent context injection workflow:
  munin run -- <agent> [args...]

It reuses:
- Existing Project Registry
- Existing ProjectResolver
- Existing ContextService (M5)
- Existing AgentService

And adds:
- AgentLaunchAdapter abstraction
- Agent detection and discovery
- Context briefing generation
- Child process management
"""

# Lazy imports to avoid circular import issues
