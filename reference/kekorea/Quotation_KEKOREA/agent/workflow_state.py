"""Session-owned document workspaces. Workers never read or write Streamlit state."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4


COMMON_KEYS = ('trade_draft', 'trade_draft_page', 'rendered_paths',
               'rendered_json', 'download_format')


def review_key(key, page):
    return str(key).startswith((f'confirm_source_alias_{page}_', f'packing_{page}_',
                               f'po_seller_name_{page}', f'po_seller_address_{page}',
                               f'review_missing_{page}_', f'review_values_{page}',
                               f'product_double_check_{page}_',
                               f'advanced_json_{page}', f'advanced_source_{page}'))


@dataclass(frozen=True)
class SavedUpload:
    name: str
    type: str
    data: bytes

    def getvalue(self):
        return self.data


@dataclass
class Job:
    future: object
    context: str = None
    file_format: str = None


class DocumentWorkspaces:
    def __init__(self, *, executor=None):
        self.pages = {}
        self.active = None
        self.jobs = {}
        self.errors = {}
        self.uploads = {}
        self.editor_rows = {}
        self.editor_bases = {}
        self.session_id = uuid4().hex
        self._executor = executor

    def save(self, state):
        if self.active is None:
            return
        self.pages[self.active] = {
            key: deepcopy(state[key]) for key in state
            if (key in COMMON_KEYS or review_key(key, self.active)
                or key == f'order_prompt_{self.active}')
            and key != f'packing_{self.active}_rows'}

    def activate(self, state, page):
        if self.active is None:
            # Adopt existing drafts from sessions opened before this change.
            self.active = state.get('trade_draft_page') or page
        if self.active == page:
            return
        self.save(state)
        for key in COMMON_KEYS:
            state.pop(key, None)
        self.active = page
        self.editor_bases.pop(page, None)
        for key, value in self.pages.get(page, {}).items():
            state[key] = deepcopy(value)

    def remember_uploads(self, page, uploads):
        self.uploads[page] = [SavedUpload(f.name, f.type, f.getvalue()) for f in uploads]

    def editor_input(self, page, original_rows):
        # Streamlit's data_editor state is read-only. Keep the actual rows and a
        # stable base during each visit, rather than trying to restore its deltas.
        if page not in self.editor_bases:
            self.editor_bases[page] = deepcopy(self.editor_rows.get(page, original_rows))
        return deepcopy(self.editor_bases[page])

    def reset_editor(self, page):
        self.editor_rows.pop(page, None)
        self.editor_bases.pop(page, None)

    def busy(self, page, kind):
        return (page, kind) in self.jobs

    def start(self, page, kind, function, *args, context=None, file_format=None, **kwargs):
        if self.busy(page, kind):
            return None
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='trade-document')
        # Copy before submission: later edits must not mutate an in-flight request.
        args, kwargs = deepcopy(args), deepcopy(kwargs)
        future = self._executor.submit(function, *args, **kwargs)
        job = Job(future, context, file_format)
        self.jobs[page, kind] = job
        self.errors.pop(page, None)
        return job

    def collect(self, state):
        self.save(state)
        completed = False
        for (page, kind), job in list(self.jobs.items()):
            if not job.future.done():
                continue
            completed = True
            del self.jobs[page, kind]
            try:
                result = job.future.result()
            except Exception as exc:
                self.errors[page] = str(exc)
                continue
            values = self.pages.setdefault(page, {})
            if kind == 'extract':
                self.reset_editor(page)
                for key in list(values):
                    if review_key(key, page) or key in COMMON_KEYS:
                        del values[key]
                values.update(trade_draft=result, trade_draft_page=page, rendered_paths={})
                if page == self.active:
                    for key in list(state):
                        if review_key(key, page) or key in COMMON_KEYS:
                            del state[key]
                    for key in COMMON_KEYS:
                        if key in values:
                            state[key] = deepcopy(values[key])
            elif kind == 'render' and values.get('rendered_json') == job.context:
                values['rendered_paths'] = {key: str(path) for key, path in result.items()}
                values['download_format'] = job.file_format
                if page == self.active:
                    state['rendered_paths'] = deepcopy(values['rendered_paths'])
                    state['download_format'] = job.file_format
        return completed
