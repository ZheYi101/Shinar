"""Capture speech backends on the main thread; bind them on the worker."""

class SpeechRoute:
    """Capture routing once on the GUI thread, bind the model on the worker."""

    def __init__(self, vm, task: str) -> None:
        local = vm.local_speech
        self.backend = (
            local.provider(task) if local and local.enabled(task) else vm.speech_provider(task)
        )
        self._bound = None
        self._error = None

    async def bind(self, language: str):
        if self._error:
            raise self._error
        if self._bound is not None:
            return self._bound
        if self.backend is None:
            raise ValueError("speech_service_unavailable")
        bind = getattr(self.backend, "bind", None)
        self._bound = await bind(language) if bind else self.backend
        return self._bound

    async def prepare(self, language: str) -> None:
        try:
            await self.bind(language)
        except Exception as exc:
            self._error = exc
