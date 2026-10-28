"""The model, pinned to an exact revision: a newer upload of the weights or processor can't change or
break the voice unannounced. Kept apart from server.py so the setup scripts can read it without
importing torch."""
MODEL_ID = 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'
MODEL_REVISION = 'fd4b254389122332181a7c3db7f27e918eec64e3'
