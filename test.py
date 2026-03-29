import asyncio
from google.adk.runners import InMemoryRunner
from google.adk.agents import LlmAgent

async def main():
  runner = InMemoryRunner(app_name='t', agent=LlmAgent(name='a', instruction='1', model='m'))
  session = await runner.session_service.create_session(app_name='t', user_id='u', session_id='s', state={'foo': 'bar'})
  print(session.state)
asyncio.run(main())
