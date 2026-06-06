"""Multimodal *input understanding* features (Vision + Speech-to-Text).

Both ride the same swappable llama-server on the ``llm`` node: a request swaps it
to the multimodal Gemma 4 E4B preset (vision encoder + audio conformer in one
mmproj), calls the OpenAI-compatible ``/chat/completions`` with image/audio
content, and leaves the model resident until a different preset is requested.
"""
