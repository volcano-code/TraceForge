"""Standalone SDK installation/API probe, NOT a product-runtime acceptance test.

No TraceForge runtime is imported. No repository code is executed. Model
responses below are explicitly scripted; this is not a real provider call.
"""
from __future__ import annotations
import importlib.metadata
import json
import socket
import tempfile
from pathlib import Path

PIN = '1.50.0'
OUT = Path('reports/sdk-environment')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'status': 'FAIL', 'scope': 'standalone SDK environment/API probe',
              'product_runtime_tested': False, 'real_model_called': False,
              'candidate_code_executed': False, 'provider_calls': 0}
    try:
        versions = {name: importlib.metadata.version(name)
                    for name in ('openhands-sdk', 'openhands-tools')}
        report['packages'] = versions
        assert all(v == PIN for v in versions.values()), 'Pinned packages mismatch'
        from openhands.sdk import Action, Agent, Conversation, LLM, Observation, TextContent, ToolDefinition
        from openhands.sdk.tool import Tool, ToolExecutor, register_tool
        from litellm import ModelResponse
        from pydantic import SecretStr
        completions, actions, events = [], [], []

        class ProbeAction(Action):
            message: str

        class ProbeObservation(Observation):
            value: str
            @property
            def to_llm_content(self):
                return [TextContent(text=self.value)]

        class ProbeExecutor(ToolExecutor):
            def __call__(self, action, conversation=None):
                actions.append(action.message)
                return ProbeObservation(value='probe-ok')

        class EnvironmentProbeTool(ToolDefinition):
            @classmethod
            def create(cls, conv_state=None, **kwargs):
                return [cls(description='In-memory echo for installation verification only.',
                            action_type=ProbeAction, observation_type=ProbeObservation,
                            executor=ProbeExecutor())]

        class ScriptedLLM(LLM):
            def completion(self, messages, tools=None, **kwargs):
                names = {tool.name for tool in tools}
                assert EnvironmentProbeTool.name in names and 'finish' in names
                index = len(completions)
                assert index < 2, 'Unexpected model turn'
                name = EnvironmentProbeTool.name if index == 0 else 'finish'
                completions.append(name)
                raw = ModelResponse(id=f'probe-{index}', model=self.model,
                    choices=[{'index': 0, 'message': {'role': 'assistant', 'content': None,
                        'tool_calls': [{'id': f'action-{index}', 'type': 'function',
                            'function': {'name': name, 'arguments': json.dumps({'message': 'probe'})}}]},
                        'finish_reason': 'tool_calls'}],
                    usage={'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20})
                return self._build_completion_result(raw)

        def no_network(*args, **kwargs):
            raise AssertionError('Network prohibited during scripted SDK session')
        original_connect = socket.socket.connect
        socket.socket.connect = no_network
        try:
            register_tool(EnvironmentProbeTool.name, EnvironmentProbeTool)
            llm = ScriptedLLM(model='openai/gpt-4o-mini',
                api_key=SecretStr('synthetic-probe-not-a-key'), usage_id='sdk-environment-probe', num_retries=0)
            with tempfile.TemporaryDirectory(prefix='tf-sdk-probe-') as tmp:
                conversation = Conversation(agent=Agent(llm=llm, tools=[Tool(name=EnvironmentProbeTool.name)]),
                    workspace=tmp, plugins=[], profile_store_dir=Path(tmp) / 'profiles', visualizer=None,
                    callbacks=[lambda event: events.append(type(event).__name__)],
                    max_iteration_per_run=4, max_budget_per_run=0.1)
                try:
                    conversation.send_message('Use the in-memory echo probe, then finish.')
                    conversation.run()
                    terminal = str(conversation.state.execution_status)
                    assert terminal.split('.')[-1].lower() == 'finished', terminal
                finally:
                    conversation.close()
            assert actions == ['probe'] and len(completions) == 2
            report.update(status='PASS', scripted_completions=len(completions),
                          real_sdk_tool_actions=len(actions), sdk_event_types=events,
                          terminal_status=terminal)
        finally:
            socket.socket.connect = original_connect
    except Exception as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        (OUT / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
