import asyncio
import os
from litellm import Router

router = Router(
    model_list=[{
        'model_name': 'test_chat',
        'litellm_params': {
            'model': 'gemini/gemini-2.0-flash',
            'api_key': os.environ.get("GOOGLE_API_KEY", ""),
            'tpm': 100000,
            'rpm': 60
        }
    }],
    num_retries=2,
    timeout=120,
    routing_strategy='usage-based-routing-v2',
    enable_pre_call_checks=False
)

async def main():
    try:
        resp = await router.acompletion(
            model='test_chat',
            messages=[{'role': 'user', 'content': 'Hello'}],
            max_tokens=120
        )
        print(resp)
    except Exception as e:
        print(repr(e))

asyncio.run(main())
