"""
Model profile management for FlatAgents.

Provides centralized model configuration through profiles.yml files.
Profiles enable easy switching between model configurations (e.g., dev vs prod).

Resolution order (low to high priority):
1. default profile (fallback)
2. Named profile from agent's model field
3. Inline overrides from agent's model field
4. override profile (trumps all)
"""

import os
from typing import Any, Dict, Optional

from .monitoring import get_logger

logger = get_logger(__name__)

# Cache loaded profile managers by directory
_profile_managers: Dict[str, "ProfileManager"] = {}


class ProfileManager:
    """
    Manages model profiles from profiles.yml files.

    Resolution order (low to high priority):
    1. default profile (fallback)
    2. Named profile from agent's model field
    3. Inline overrides from agent's model field
    4. override profile (trumps all)

    Example:
        >>> manager = ProfileManager("config/profiles.yml")
        >>> config = manager.resolve_model_config("fast-cheap")
        >>> print(config)
        {'provider': 'cerebras', 'name': 'zai-glm-4.6', 'temperature': 0.6}
    """

    def __init__(self, profiles_dict: Optional[Dict[str, Any]] = None):
        """
        Initialize profile manager.

        Args:
            profiles_dict: Profiles dict with format:
                {'profiles': {...}, 'default': 'name', 'override': 'name'}
                Use load_profiles_from_file() to load from a YAML file.
        """
        self._profiles: Dict[str, Dict[str, Any]] = {}
        self._default_profile: Optional[str] = None
        self._override_profile: Optional[str] = None

        if profiles_dict:
            self._profiles = profiles_dict.get('profiles', {})
            self._default_profile = profiles_dict.get('default')
            self._override_profile = profiles_dict.get('override')

    @classmethod
    def get_instance(cls, config_dir: str) -> "ProfileManager":
        """
        Get or create a ProfileManager for a directory.

        Caches instances by directory to avoid re-reading profiles.yml.

        Args:
            config_dir: Directory containing profiles.yml

        Returns:
            ProfileManager instance (may have no profiles if file not found)
        """
        if config_dir not in _profile_managers:
            profiles_path = os.path.join(config_dir, "profiles.yml")
            if os.path.exists(profiles_path):
                profiles_dict = load_profiles_from_file(profiles_path)
                _profile_managers[config_dir] = cls(profiles_dict)
            else:
                # No profiles file - return empty manager
                _profile_managers[config_dir] = cls()
        return _profile_managers[config_dir]

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached ProfileManager instances."""
        _profile_managers.clear()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize profiles to a dict (for passing to other components)."""
        return {
            'profiles': self._profiles,
            'default': self._default_profile,
            'override': self._override_profile
        }

    def get_profile(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a profile by name.

        Args:
            name: Profile name

        Returns:
            Profile config dict or None if not found
        """
        return self._profiles.get(name)

    @property
    def profiles(self) -> Dict[str, Dict[str, Any]]:
        """All loaded profiles."""
        return self._profiles

    @property
    def default_profile(self) -> Optional[str]:
        """Name of the default profile."""
        return self._default_profile

    @property
    def override_profile(self) -> Optional[str]:
        """Name of the override profile."""
        return self._override_profile

    def resolve_model_config(
        self,
        agent_model_config: Any
    ) -> Dict[str, Any]:
        """
        Resolve the final model configuration.

        Resolution order:
        1. Start with default profile (if set)
        2. Apply named profile (if agent_model_config is string or has 'profile' key)
        3. Merge inline overrides (if agent_model_config is dict)
        4. Apply override profile (trumps all)

        Args:
            agent_model_config: Agent's model config (string, dict, or None)

        Returns:
            Fully resolved model configuration dict

        Raises:
            ValueError: If a referenced profile is not found
        """
        result = {}

        # 1. Apply default profile
        if self._default_profile:
            default_cfg = self.get_profile(self._default_profile)
            if default_cfg:
                result.update(default_cfg)
            else:
                logger.warning(f"Default profile '{self._default_profile}' not found")

        # 2. Handle agent's model config
        if isinstance(agent_model_config, str):
            # String = profile name
            profile_cfg = self.get_profile(agent_model_config)
            if profile_cfg:
                result.update(profile_cfg)
            elif result:
                # Profile not found but we have a default - warn and continue
                logger.warning(
                    f"Model profile '{agent_model_config}' not found, "
                    f"using default profile '{self._default_profile}'"
                )
            else:
                raise ValueError(f"Model profile '{agent_model_config}' not found and no default configured")

        elif isinstance(agent_model_config, dict):
            # Check for profile reference in dict
            profile_name = agent_model_config.get('profile')
            if profile_name:
                profile_cfg = self.get_profile(profile_name)
                if profile_cfg:
                    result.update(profile_cfg)
                elif result:
                    # Profile not found but we have a default - warn and continue
                    logger.warning(
                        f"Model profile '{profile_name}' not found, "
                        f"using default profile '{self._default_profile}'"
                    )
                else:
                    raise ValueError(f"Model profile '{profile_name}' not found and no default configured")

            # Merge inline overrides (excluding 'profile' key)
            inline_overrides = {
                k: v for k, v in agent_model_config.items()
                if k != 'profile' and v is not None
            }
            result.update(inline_overrides)

        # 3. Apply override profile (trumps all)
        if self._override_profile:
            override_cfg = self.get_profile(self._override_profile)
            if override_cfg:
                result.update(override_cfg)
            else:
                available_profiles = list(self._profiles.keys())
                raise ValueError(
                    f"Override profile '{self._override_profile}' not found. "
                    f"The intended model override was NOT applied. "
                    f"Available profiles: {available_profiles}"
                )

        return result


def load_profiles_from_file(profiles_file: str) -> Dict[str, Any]:
    """
    Load profiles from a YAML file.

    Use this to load profiles that can be passed to ProfileManager or
    injected into context for distributed systems.

    Args:
        profiles_file: Path to profiles.yml file

    Returns:
        Profiles dict with format:
            {'profiles': {...}, 'default': 'name', 'override': 'name'}

    Example:
        >>> profiles = load_profiles_from_file("config/profiles.yml")
        >>> manager = ProfileManager(profiles)
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("pyyaml is required for profiles.yml")

    profiles_file = os.path.abspath(os.path.expanduser(profiles_file))
    if not os.path.exists(profiles_file):
        raise FileNotFoundError(f"Profiles file not found: {profiles_file}")

    with open(profiles_file, 'r') as f:
        config = yaml.safe_load(f) or {}

    # Validate spec if present
    spec = config.get('spec')
    if spec and spec != 'flatprofile':
        raise ValueError(f"Invalid profiles spec: expected 'flatprofile', got '{spec}'")

    # Support both wrapped (spec/data) and unwrapped format
    data = config.get('data', config)

    result = {
        'profiles': data.get('model_profiles', {}),
        'default': data.get('default'),
        'override': data.get('override')
    }

    logger.info(
        f"Loaded {len(result['profiles'])} profiles from {profiles_file}"
        f" (default={result['default']}, override={result['override']})"
    )

    return result


def resolve_model_config(
    agent_model_config: Any,
    config_dir: str,
    profiles_file: Optional[str] = None,
    profiles_dict: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convenience function to resolve model configuration.

    Args:
        agent_model_config: Agent's model config (string, dict, or None)
        config_dir: Directory containing agent config (for profiles.yml lookup)
        profiles_file: Explicit path to profiles.yml (overrides auto-discovery)
        profiles_dict: Pre-loaded profiles dict (takes precedence over file)

    Returns:
        Fully resolved model configuration dict

    Example:
        >>> config = resolve_model_config("fast-cheap", "./config")
        >>> print(config)
        {'provider': 'cerebras', 'name': 'zai-glm-4.6', 'temperature': 0.6}
    """
    if profiles_dict:
        manager = ProfileManager(profiles_dict)
    elif profiles_file:
        manager = ProfileManager(load_profiles_from_file(profiles_file))
    else:
        manager = ProfileManager.get_instance(config_dir)

    return manager.resolve_model_config(agent_model_config)


def resolve_profiles_with_fallback(
    own_profiles: Optional[Dict[str, Any]],
    parent_profiles: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Resolve profiles: own wins entirely, parent is fallback only when own is None.

    No merging. Nearest profiles.yml wins completely.

    Args:
        own_profiles: Child's own profiles (from its profiles.yml)
        parent_profiles: Parent's profiles (fallback for dynamic agents/machines)

    Returns:
        own_profiles if exists, else parent_profiles, else None
    """
    return own_profiles if own_profiles else parent_profiles


def discover_profiles_file(config_dir: str, explicit_path: Optional[str] = None) -> Optional[str]:
    """
    Discover profiles.yml in config_dir if not explicitly provided.

    This is used by FlatAgent and FlatMachine to auto-discover profiles.yml
    and propagate it to child agents/machines.

    Args:
        config_dir: Directory to search for profiles.yml
        explicit_path: Explicit path if already provided (returned as-is)

    Returns:
        Path to profiles.yml if found, explicit_path if provided, or None
    """
    if explicit_path:
        path = os.path.expanduser(explicit_path)
        if not os.path.isabs(path):
            path = os.path.join(config_dir, path)
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Profiles file not found: {path}")
        return path
    default_path = os.path.join(config_dir, 'profiles.yml')
    return default_path if os.path.exists(default_path) else None


def _profiles_dict_from_flatprofile_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a wrapped flatprofile catalog config to ProfileManager input."""
    spec = config.get("spec")
    if spec != "flatprofile":
        raise ValueError(f"Invalid profile spec: expected 'flatprofile', got '{spec}'")

    data = config.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError("Invalid flatprofile config: data must be an object")

    return {
        "profiles": data.get("model_profiles", {}),
        "default": data.get("default"),
        "override": data.get("override"),
    }


def _resolve_default_profile(profiles_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the default/override profile from a flatprofile catalog."""
    manager = ProfileManager(profiles_dict)
    resolved = manager.resolve_model_config(None)
    if resolved:
        return resolved

    profiles = profiles_dict.get("profiles", {}) or {}
    if len(profiles) == 1:
        return dict(next(iter(profiles.values())))

    raise ValueError(
        "Inline flatprofile catalogs used as data.profile must set data.default "
        "or contain exactly one model_profiles entry"
    )


def load_profile_from_file(profile_file: str) -> Dict[str, Any]:
    """Load a wrapped flatprofile catalog file and resolve its default profile."""
    try:
        import yaml
    except ImportError:
        yaml = None

    if not os.path.exists(profile_file):
        raise FileNotFoundError(f"Profile file not found: {profile_file}")

    with open(profile_file, "r") as f:
        if profile_file.endswith(".json"):
            config = __import__("json").load(f) or {}
        else:
            if yaml is None:
                raise ImportError("pyyaml is required for YAML profile files")
            config = yaml.safe_load(f) or {}

    return _resolve_default_profile(_profiles_dict_from_flatprofile_config(config))


def resolve_profile_config(
    profile_ref: Any,
    config_dir: str,
    profiles_file: Optional[str] = None,
    profiles_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve a flatagent data.profile value into concrete execution profile data."""
    if isinstance(profile_ref, str):
        effective_profiles = profiles_dict
        if effective_profiles is None:
            discovered = discover_profiles_file(config_dir, profiles_file)
            effective_profiles = load_profiles_from_file(discovered) if discovered else None
        if not effective_profiles:
            raise ValueError(f"Profile '{profile_ref}' not found: no flatprofile catalog available")
        return resolve_model_config(profile_ref, config_dir, profiles_dict=effective_profiles)

    if isinstance(profile_ref, dict):
        return _resolve_default_profile(_profiles_dict_from_flatprofile_config(profile_ref))

    raise ValueError("Invalid profile reference. Expected profile name string or flatprofile catalog dict.")


__all__ = [
    "ProfileManager",
    "load_profiles_from_file",
    "resolve_model_config",
    "resolve_profiles_with_fallback",
    "discover_profiles_file",
    "load_profile_from_file",
    "resolve_profile_config",
]
