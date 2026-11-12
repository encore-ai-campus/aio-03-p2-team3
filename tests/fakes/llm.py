import httpx
import openai


class FakeLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return self

    def invoke(self, prompt):
        self.calls.append(prompt)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def openai_error(status: int, *, message: str = "가상 SDK 오류"):
    """실제 OpenAI SDK 예외를 네트워크 없이 만든다(응답에는 가상 정보만 둔다)."""
    classes = {
        400: openai.BadRequestError, 401: openai.AuthenticationError,
        403: openai.PermissionDeniedError, 404: openai.NotFoundError,
        422: openai.UnprocessableEntityError, 429: openai.RateLimitError,
    }
    cls = classes.get(status, openai.InternalServerError if status >= 500 else openai.APIStatusError)
    response = httpx.Response(
        status, request=httpx.Request("POST", "https://api.openai.invalid/v1/responses"),
    )
    kwargs = {"response": response, "body": {"message": message}}
    return cls(message, **kwargs)
