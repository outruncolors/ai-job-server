"""Multimodal *input understanding* features (Vision + Speech-to-Text).

Both ride the same swappable llama-server on the ``llm`` node: a request swaps it
to the multimodal Gemma 4 E4B preset (vision encoder + audio conformer in one
mmproj), calls the OpenAI-compatible ``/chat/completions`` with image/audio
content, and leaves the model resident until a different preset is requested.

Vision/STT run through the JobQueue like image/voice jobs (job dir, ``logs.txt``,
``output.txt`` artifact, crash recovery): the ``/v1/jobs/{vision,stt}`` routes in
``app.main`` save the upload and enqueue a runner from ``runner.py``, which calls
the ``service.py`` helpers below. ``service.py`` (generation) and ``swap.py``
(model swap) carry no FastAPI/job knowledge.
"""
