"""PostgreSQL 대기 문서를 프로세스당 한 개씩 처리한다. 자동 유료 재시도는 없다."""
import asyncio
from logging import getLogger

from app.knowledge.operations import process_claimed
from app.knowledge.schemas import KnowledgeError

log = getLogger(__name__)


class IngestionWorker:
    def __init__(self, repository, storage, make_adapters):
        self.repository, self.storage, self.make_adapters = repository, storage, make_adapters
        self.stop = asyncio.Event()

    def run_once(self):
        self.repository.expire()
        job = self.repository.claim()
        if job is None:
            return False
        try:
            renderer, extractor, embedder = self.make_adapters(job["user_id"], job["profile"])
        except Exception as error:
            code = error.code if isinstance(error, KnowledgeError) else "provider_not_configured"
            self.repository.update_attempt(job["id"], job["attempt_id"], status="failed",
                                           error_code=code, error_stage="configuration")
            return True
        process_claimed(self.repository, self.storage, renderer, extractor, embedder, job)
        return True

    async def run(self):
        while not self.stop.is_set():
            try:
                worked = await asyncio.to_thread(self.run_once)
            except Exception as error:
                log.error("지식 문서 처리 실패 (%s)", type(error).__name__)
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=2)
                except TimeoutError:
                    pass
