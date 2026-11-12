"""장치 토큰의 OS별 개인 저장소. Windows는 현재 사용자 DPAPI와 보호된 DACL을 쓴다."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
import stat

from app.worker.protocol import WorkerError

_WINDOWS_MAGIC = b"aio-worker-dpapi-v1\x00"


def write_private(path, data: bytes):
    if os.name == "nt":
        api = _WindowsAPI()
        encrypted = _WINDOWS_MAGIC + api.protect(data)
        with api.file(path, create=True) as target:
            target.write(encrypted)
        return
    if os.name != "posix":
        raise WorkerError("private_file_permissions_required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(data)


def read_private(path, limit: int) -> bytes:
    if os.name == "nt":
        api = _WindowsAPI()
        with api.file(path, create=False) as source:
            data = source.read(limit + 1)
        if len(data) > limit or not data.startswith(_WINDOWS_MAGIC):
            raise WorkerError("credentials_unavailable")
        data = api.unprotect(data[len(_WINDOWS_MAGIC):])
        if len(data) > limit:
            raise WorkerError("credentials_unavailable")
        return data
    if os.name != "posix":
        raise WorkerError("private_file_permissions_required")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as source:
        mode = os.fstat(source.fileno())
        if not stat.S_ISREG(mode.st_mode) or mode.st_mode & 0o077 or mode.st_uid != os.getuid():
            raise WorkerError("unauthorized")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise WorkerError("credentials_unavailable")
    return data


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]


class _SidAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


class _AclSize(ctypes.Structure):
    _fields_ = [("count", wintypes.DWORD), ("used", wintypes.DWORD), ("free", wintypes.DWORD)]


class _FileAttributes(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]


class _WindowsAPI:
    """Win32 포인터/핸들 크기를 명시한다. 라이브러리는 Windows 호출 때만 로드한다.

    근거: Microsoft Learn의 CryptProtectData/UnprotectData, CreateFileW,
    ConvertStringSecurityDescriptorToSecurityDescriptorW, GetSecurityInfo, GetAce.
    https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
    https://learn.microsoft.com/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo
    """
    def __init__(self):
        pointer = ctypes.c_void_p
        pp = ctypes.POINTER(pointer)
        dword_pointer = ctypes.POINTER(wintypes.DWORD)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.security = ctypes.WinDLL("advapi32", use_last_error=True)
        self.crypto = ctypes.WinDLL("crypt32", use_last_error=True)
        self._bind(self.kernel, "GetCurrentProcess", [], wintypes.HANDLE)
        self._bind(self.kernel, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
        self._bind(self.kernel, "LocalFree", [pointer], pointer)
        self._bind(self.kernel, "CreateFileW", [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                   ctypes.POINTER(_SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE)
        self._bind(self.kernel, "GetFileType", [wintypes.HANDLE], wintypes.DWORD)
        self._bind(self.kernel, "GetFileInformationByHandleEx", [wintypes.HANDLE, ctypes.c_int, pointer, wintypes.DWORD], wintypes.BOOL)
        self._bind(self.security, "OpenProcessToken", [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL)
        self._bind(self.security, "GetTokenInformation", [wintypes.HANDLE, ctypes.c_int, pointer, wintypes.DWORD, dword_pointer], wintypes.BOOL)
        self._bind(self.security, "ConvertSidToStringSidW", [pointer, pp], wintypes.BOOL)
        self._bind(self.security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", [wintypes.LPCWSTR, wintypes.DWORD, pp, dword_pointer], wintypes.BOOL)
        self._bind(self.security, "GetSecurityInfo", [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, pp, pp, pp, pp, pp], wintypes.DWORD)
        self._bind(self.security, "GetSecurityDescriptorControl", [pointer, ctypes.POINTER(wintypes.WORD), dword_pointer], wintypes.BOOL)
        self._bind(self.security, "EqualSid", [pointer, pointer], wintypes.BOOL)
        self._bind(self.security, "GetAclInformation", [pointer, pointer, wintypes.DWORD, ctypes.c_int], wintypes.BOOL)
        self._bind(self.security, "GetAce", [pointer, wintypes.DWORD, pp], wintypes.BOOL)
        self._bind(self.crypto, "CryptProtectData", [ctypes.POINTER(_Blob), wintypes.LPCWSTR,
                   ctypes.POINTER(_Blob), pointer, pointer, wintypes.DWORD, ctypes.POINTER(_Blob)], wintypes.BOOL)
        self._bind(self.crypto, "CryptUnprotectData", [ctypes.POINTER(_Blob), pp,
                   ctypes.POINTER(_Blob), pointer, pointer, wintypes.DWORD, ctypes.POINTER(_Blob)], wintypes.BOOL)

    @staticmethod
    def _bind(library, name, arguments, result):
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, result

    @staticmethod
    def _require(success):
        if not success:
            raise WorkerError("credentials_unavailable")

    def _transform(self, value, protect):
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        source, target = _Blob(len(value), buffer), _Blob()
        function = self.crypto.CryptProtectData if protect else self.crypto.CryptUnprotectData
        # UI_FORBIDDEN=1. LOCAL_MACHINE은 사용하지 않아 현재 Windows 사용자에게 묶는다.
        self._require(function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)))
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            self.kernel.LocalFree(target.data)

    def protect(self, value):
        return self._transform(value, True)

    def unprotect(self, value):
        return self._transform(value, False)

    @contextmanager
    def user_sid(self):
        token, length = wintypes.HANDLE(), wintypes.DWORD()
        self._require(self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)))
        try:
            self.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))  # TokenUser
            self._require(0 < length.value <= 65536)
            buffer = ctypes.create_string_buffer(length.value)
            self._require(self.security.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)))
            yield ctypes.cast(buffer, ctypes.POINTER(_SidAttributes)).contents.sid
        finally:
            self.kernel.CloseHandle(token)

    def _private_descriptor(self, sid):
        text, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
        self._require(self.security.ConvertSidToStringSidW(sid, ctypes.byref(text)))
        try:
            user = ctypes.wstring_at(text)
            # 현재 사용자를 소유자로 지정하고 상속을 끈다. 그 사용자에게만 접근을 허용한다.
            self._require(self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                f"O:{user}D:P(A;;FA;;;{user})", 1, ctypes.byref(descriptor), None))
            return descriptor
        finally:
            self.kernel.LocalFree(text)

    def _validate_file(self, handle, sid):
        attributes = _FileAttributes()
        self._require(self.kernel.GetFileType(handle) == 1)  # FILE_TYPE_DISK
        self._require(self.kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)))
        self._require(not attributes.attributes & (0x10 | 0x400))  # 디렉터리/reparse point 금지
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        self._require(self.security.GetSecurityInfo(handle, 1, 0x1 | 0x4, ctypes.byref(owner), None,
                                                   ctypes.byref(dacl), None, ctypes.byref(descriptor)) == 0)
        try:
            self._require(owner and dacl and self.security.EqualSid(owner, sid))
            control, revision = wintypes.WORD(), wintypes.DWORD()
            self._require(self.security.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)))
            self._require(control.value & 0x1000)  # SE_DACL_PROTECTED: 부모 권한을 상속하지 않는다.
            size, ace = _AclSize(), ctypes.c_void_p()
            self._require(self.security.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2))
            self._require(size.count == 1)
            self._require(self.security.GetAce(dacl, 0, ctypes.byref(ace)))
            self._require(ctypes.c_ubyte.from_address(ace.value).value == 0)  # ACCESS_ALLOWED_ACE
            self._require(self.security.EqualSid(ctypes.c_void_p(ace.value + 8), sid))
        finally:
            self.kernel.LocalFree(descriptor)

    @contextmanager
    def file(self, path, *, create):
        import msvcrt
        with self.user_sid() as sid:
            descriptor = self._private_descriptor(sid) if create else None
            attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
            try:
                # CREATE_NEW는 기존 파일/링크를 덮지 않는다. 읽기는 검증한 핸들을 끝까지 유지한다.
                handle = self.kernel.CreateFileW(os.path.abspath(path),
                    (0xC0000000 if create else 0x80000000) | 0x20000, 1,
                    ctypes.byref(attributes) if create else None, 1 if create else 3, 0x00200080, None)
                create_error = ctypes.get_last_error()
            finally:
                if descriptor:
                    self.kernel.LocalFree(descriptor)
            if handle == ctypes.c_void_p(-1).value:
                if create and create_error in {80, 183}:
                    raise FileExistsError("credentials_exist")
                raise WorkerError("credentials_unavailable")
            try:
                self._validate_file(handle, sid)
                descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY | os.O_NOINHERIT
                                                  | (os.O_WRONLY if create else os.O_RDONLY))
                handle = None  # Python 파일 객체가 핸들의 소유권을 받았다.
                with os.fdopen(descriptor, "wb" if create else "rb") as stream:
                    yield stream
            finally:
                if handle is not None:
                    self.kernel.CloseHandle(handle)
