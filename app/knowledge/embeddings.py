"""추출기와 독립적인 OpenAI 임베딩 어댑터. 사용자 키 읽기 함수를 주입한다."""
from collections.abc import Callable

from openai import APIConnectionError, APIStatusError, OpenAI

from app.knowledge.extract import provider_error
from app.knowledge.schemas import EmbeddingBatch, KnowledgeError, ModelProfile


class OpenAIEmbedder:
    def __init__(self, read_key: Callable[[], str], model: str, dimensions: int, *, client_factory=OpenAI):
        if not 1 <= dimensions <= 16000:
            raise KnowledgeError("invalid_dimensions", "임베딩 차원은 1~16000으로 설정해 주세요.", 503)
        self.read_key, self.client_factory = read_key, client_factory
        self.profile = ModelProfile(provider="openai", model=model, dimensions=dimensions,
                                    revision="openai-embeddings-v1")

    def embed_documents(self, texts: list[str]) -> EmbeddingBatch:
        with self.client_factory(api_key=self.read_key(), timeout=30, max_retries=0) as client:
            options = {"dimensions": self.profile.dimensions} if self.profile.model.startswith("text-embedding-3-") else {}
            try:
                response = client.embeddings.create(model=self.profile.model, input=texts, **options)
            except (APIStatusError, APIConnectionError) as error:
                raise provider_error(error) from None
        by_index = {item.index: item.embedding for item in response.data}
        if len(response.data) != len(texts) or set(by_index) != set(range(len(texts))):
            raise KnowledgeError("embedding_order", "임베딩 응답의 입력 순서를 확인할 수 없습니다.")
        batch = EmbeddingBatch(vectors=[by_index[i] for i in range(len(texts))], profile=self.profile)
        batch.validate_for(len(texts), self.profile)
        return batch
