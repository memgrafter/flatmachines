"""
Unit tests for profiles.yml auto-discovery.

Tests:
- discover_profiles_file utility function
- FlatAgent auto-discovery of profiles.yml
- FlatMachine adapter usage of profiles.yml
- Profile propagation to child agents/machines
"""

import os
import tempfile
import pytest
from flatagents.profiles import discover_profiles_file, ProfileManager


class TestDiscoverProfilesFile:
    """Test the discover_profiles_file utility function."""

    def test_returns_explicit_path_when_provided(self, tmp_path):
        """Explicit path is returned when it exists."""
        explicit_path = tmp_path / "explicit-profiles.yml"
        explicit_path.write_text("spec: flatprofile\ndata:\n  model_profiles: {}")
        result = discover_profiles_file(str(tmp_path), str(explicit_path))
        assert result == str(explicit_path)

    def test_missing_explicit_path_raises(self, tmp_path):
        """Explicit profile file refs must resolve."""
        explicit = tmp_path / "missing-profiles.yml"
        with pytest.raises(FileNotFoundError, match="Profiles file not found"):
            discover_profiles_file(str(tmp_path), str(explicit))

    def test_discovers_profiles_in_config_dir(self, tmp_path):
        """Discovers profiles.yml when it exists in config_dir."""
        profiles_path = tmp_path / "profiles.yml"
        profiles_path.write_text("spec: flatprofile\ndata:\n  model_profiles: {}")

        result = discover_profiles_file(str(tmp_path))
        assert result == str(profiles_path)

    def test_returns_none_when_no_profiles(self, tmp_path):
        """Returns None when profiles.yml doesn't exist."""
        result = discover_profiles_file(str(tmp_path))
        assert result is None

    def test_explicit_path_takes_precedence(self, tmp_path):
        """Explicit path takes precedence over auto-discovery."""
        # Create profiles.yml in config_dir
        profiles_path = tmp_path / "profiles.yml"
        profiles_path.write_text("spec: flatprofile\ndata:\n  model_profiles: {}")

        # But provide explicit path
        explicit_path = tmp_path / "explicit-profiles.yml"
        explicit_path.write_text("spec: flatprofile\ndata:\n  model_profiles: {}")
        result = discover_profiles_file(str(tmp_path), str(explicit_path))
        assert result == str(explicit_path)

    def test_empty_explicit_path_triggers_discovery(self, tmp_path):
        """Empty string explicit path is falsy, triggers discovery."""
        profiles_path = tmp_path / "profiles.yml"
        profiles_path.write_text("spec: flatprofile\ndata:\n  model_profiles: {}")

        # Empty string is falsy
        result = discover_profiles_file(str(tmp_path), "")
        assert result == str(profiles_path)

    def test_none_explicit_path_triggers_discovery(self, tmp_path):
        """None explicit path triggers discovery."""
        profiles_path = tmp_path / "profiles.yml"
        profiles_path.write_text("spec: flatprofile\ndata:\n  model_profiles: {}")

        result = discover_profiles_file(str(tmp_path), None)
        assert result == str(profiles_path)


class TestFlatAgentProfileDiscovery:
    """Test FlatAgent auto-discovers profiles.yml."""

    def test_agent_discovers_profiles_in_config_dir(self, tmp_path):
        """FlatAgent discovers profiles.yml in same directory as config."""
        from flatagents import FlatAgent

        # Create profiles.yml with a test profile
        profiles_content = """
spec: flatprofile
spec_version: "0.7.1"
data:
  model_profiles:
    test-profile:
      provider: openai
      name: gpt-4
      temperature: 0.5
  default: test-profile
"""
        (tmp_path / "profiles.yml").write_text(profiles_content)

        # Create agent config that references the profile
        agent_content = """
spec: flatagent
spec_version: "0.7.1"
data:
  name: test-agent
  model: test-profile
  system: "You are a test assistant."
  user: "{{ input.query }}"
"""
        agent_path = tmp_path / "agent.yml"
        agent_path.write_text(agent_content)

        # Load agent - should auto-discover profiles.yml
        agent = FlatAgent(config_file=str(agent_path))

        # Verify profile was resolved
        assert agent._profiles_file == str(tmp_path / "profiles.yml")
        assert agent.model == "openai/gpt-4"
        assert agent.temperature == 0.5

    def test_agent_uses_explicit_profiles_file(self, tmp_path):
        """FlatAgent uses explicit profiles_file when provided."""
        from flatagents import FlatAgent

        # Create profiles in a different directory
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        profiles_content = """
spec: flatprofile
spec_version: "0.7.1"
data:
  model_profiles:
    explicit-profile:
      provider: anthropic
      name: claude-3-opus
  default: explicit-profile
"""
        profiles_path = profiles_dir / "profiles.yml"
        profiles_path.write_text(profiles_content)

        # Create agent config in different directory
        agent_dir = tmp_path / "agents"
        agent_dir.mkdir()
        agent_content = """
spec: flatagent
spec_version: "0.7.1"
data:
  name: test-agent
  model: explicit-profile
  system: "Test"
  user: "{{ input.query }}"
"""
        agent_path = agent_dir / "agent.yml"
        agent_path.write_text(agent_content)

        # Load with explicit profiles_file
        agent = FlatAgent(config_file=str(agent_path), profiles_file=str(profiles_path))

        assert agent._profiles_file == str(profiles_path)
        assert agent.model == "anthropic/claude-3-opus"

    def test_agent_works_without_profiles(self, tmp_path):
        """FlatAgent works when no profiles.yml exists."""
        from flatagents import FlatAgent

        # Create agent with inline model config (no profiles)
        agent_content = """
spec: flatagent
spec_version: "0.7.1"
data:
  name: test-agent
  model:
    provider: openai
    name: gpt-4
    temperature: 0.7
  system: "Test"
  user: "{{ input.query }}"
"""
        agent_path = tmp_path / "agent.yml"
        agent_path.write_text(agent_content)

        agent = FlatAgent(config_file=str(agent_path))

        assert agent._profiles_file is None
        assert agent.model == "openai/gpt-4"


class TestFlatMachineProfileDiscovery:
    """Test FlatMachine adapter usage of profiles.yml."""

    def test_machine_discovers_profiles_in_config_dir(self, tmp_path):
        """FlatMachine core does not auto-discover profiles.yml."""
        from flatmachines import FlatMachine

        # Create profiles.yml
        profiles_content = """
spec: flatprofile
spec_version: "0.7.1"
data:
  model_profiles:
    fast:
      provider: openai
      name: gpt-3.5-turbo
  default: fast
"""
        (tmp_path / "profiles.yml").write_text(profiles_content)

        # Create machine config
        machine_content = """
spec: flatmachine
spec_version: "0.7.1"
data:
  name: test-machine
  states:
    start:
      type: initial
      transitions:
        - to: end
    end:
      type: final
      output: {}
"""
        machine_path = tmp_path / "machine.yml"
        machine_path.write_text(machine_content)

        machine = FlatMachine(config_file=str(machine_path))

        assert machine._profiles_file is None

    def test_machine_propagates_profiles_to_agents(self, tmp_path):
        """FlatMachine passes discovered profiles to child agents in subdirectories."""
        from flatmachines import FlatMachine

        # Create profiles.yml in machine directory
        profiles_content = """
spec: flatprofile
spec_version: "0.7.1"
data:
  model_profiles:
    smart:
      provider: anthropic
      name: claude-3-sonnet
      temperature: 0.3
  default: smart
"""
        (tmp_path / "profiles.yml").write_text(profiles_content)

        # Create agents subdirectory (without profiles.yml)
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        agent_content = """
spec: flatagent
spec_version: "0.7.1"
data:
  name: child-agent
  model: smart
  system: "You are helpful."
  user: "{{ input.query }}"
"""
        agent_path = agents_dir / "child.yml"
        agent_path.write_text(agent_content)

        # Create machine that defines agents section with path reference
        machine_content = """
spec: flatmachine
spec_version: "0.7.1"
data:
  name: test-machine
  agents:
    child: ./agents/child.yml
  states:
    start:
      type: initial
      agent: child
      input:
        query: "test"
      transitions:
        - to: end
    end:
      type: final
      output: {}
"""
        machine_path = tmp_path / "machine.yml"
        machine_path.write_text(machine_content)

        machine = FlatMachine(config_file=str(machine_path))

        # Get the executor - adapter should resolve profiles via machine config dir
        executor = machine._get_executor("child")
        agent = executor._agent

        assert agent.model == "anthropic/claude-3-sonnet"
        assert agent.temperature == 0.3

    def test_machine_works_without_profiles(self, tmp_path):
        """FlatMachine works when no profiles.yml exists."""
        from flatmachines import FlatMachine

        # Create machine config without profiles.yml
        machine_content = """
spec: flatmachine
spec_version: "0.7.1"
data:
  name: test-machine
  states:
    start:
      type: initial
      transitions:
        - to: end
    end:
      type: final
      output: {}
"""
        machine_path = tmp_path / "machine.yml"
        machine_path.write_text(machine_content)

        machine = FlatMachine(config_file=str(machine_path))

        assert machine._profiles_file is None


class TestProfileManagerCache:
    """Test ProfileManager caching behavior."""

    def test_get_instance_caches_by_directory(self, tmp_path):
        """ProfileManager.get_instance caches managers by directory."""
        profiles_content = """
spec: flatprofile
data:
  model_profiles:
    test: { provider: openai, name: gpt-4 }
"""
        (tmp_path / "profiles.yml").write_text(profiles_content)

        # Clear cache first
        ProfileManager.clear_cache()

        manager1 = ProfileManager.get_instance(str(tmp_path))
        manager2 = ProfileManager.get_instance(str(tmp_path))

        assert manager1 is manager2

    def test_get_instance_returns_empty_when_no_profiles(self, tmp_path):
        """ProfileManager.get_instance returns empty manager when no profiles.yml."""
        ProfileManager.clear_cache()

        manager = ProfileManager.get_instance(str(tmp_path))

        assert manager.profiles == {}
        assert manager.default_profile is None
