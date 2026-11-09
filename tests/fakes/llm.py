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
