"""Optional integrations (e.g. LangChain Deep Agents)."""

__all__ = ["SandboxDeepAgentBackend"]


def __getattr__(name: str):
    if name == "SandboxDeepAgentBackend":
        from .deepagents_backend import SandboxDeepAgentBackend

        return SandboxDeepAgentBackend
    raise AttributeError(name)
