"""Serve the optional ADK analyst using the A2A protocol."""

from google.adk.a2a.utils.agent_to_a2a import to_a2a

from agent_service.fabpulse_agent.agent import root_agent

app = to_a2a(root_agent, host="127.0.0.1", port=8001)
