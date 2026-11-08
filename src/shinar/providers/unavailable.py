"""Allow local materials and history to open without inventing offline replies."""


class UnavailableLearningLLMProvider:
    display_label = '本地资料 · AI 未配置'
    preparation_cache_identity = 'unavailable'
    supports_streaming = False
    offline_read_only = True

    async def _unavailable(self, **kwargs):
        raise RuntimeError('ai_service_unconfigured')

    analyze_material = generate_task = generate_reply = prepare_custom_topic = _unavailable
    prepare_dialogue = correct_answer = create_review_items = summarize_session = _unavailable
