"""Windows process ownership. Imported only on Windows."""

import ctypes as c
from ctypes import wintypes as w

k = c.WinDLL("kernel32", use_last_error=True)


class Basic(c.Structure):
    _fields_ = [("user", c.c_int64), ("job_user", c.c_int64), ("flags", w.DWORD),
                ("minimum", c.c_size_t), ("maximum", c.c_size_t), ("active", w.DWORD),
                ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class Extended(c.Structure):
    _fields_ = [("basic", Basic), ("io", c.c_uint64 * 6),
                ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]


class ThreadEntry(c.Structure):
    _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("tid", w.DWORD),
                ("pid", w.DWORD), ("priority", w.LONG), ("delta", w.LONG), ("flags", w.DWORD)]


def api(name, result, *args):
    function = getattr(k, name)
    function.restype, function.argtypes = result, args
    return function


create = api("CreateJobObjectW", w.HANDLE, c.c_void_p, w.LPCWSTR)
set_info = api("SetInformationJobObject", w.BOOL, w.HANDLE, c.c_int, c.c_void_p, w.DWORD)
assign = api("AssignProcessToJobObject", w.BOOL, w.HANDLE, w.HANDLE)
terminate = api("TerminateJobObject", w.BOOL, w.HANDLE, w.UINT)
close = api("CloseHandle", w.BOOL, w.HANDLE)
snapshot = api("CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
first = api("Thread32First", w.BOOL, w.HANDLE, c.POINTER(ThreadEntry))
next_thread = api("Thread32Next", w.BOOL, w.HANDLE, c.POINTER(ThreadEntry))
open_thread = api("OpenThread", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
resume = api("ResumeThread", w.DWORD, w.HANDLE)


class Job:
    def __init__(self):
        self.handle = create(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not set_info(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            error = c.WinError(c.get_last_error())
            self.close()
            raise error

    def start(self, proc):
        # Popen closes its primary thread handle. Find that thread while the process
        # is still suspended: it cannot create children before being assigned.
        if not assign(self.handle, int(proc._handle)):
            raise c.WinError(c.get_last_error())
        snap = snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snap == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = c.sizeof(entry)
            found = first(snap, c.byref(entry))
            while found:
                if entry.pid == proc.pid:
                    thread = open_thread(2, False, entry.tid)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise c.WinError(c.get_last_error())
                    try:
                        if resume(thread) == 0xFFFFFFFF:
                            raise c.WinError(c.get_last_error())
                        return
                    finally:
                        close(thread)
                found = next_thread(snap, c.byref(entry))
            raise OSError("Cannot find the suspended check's primary thread")
        finally:
            close(snap)

    def kill(self):
        if self.handle and not terminate(self.handle, 1):
            raise c.WinError(c.get_last_error())

    def close(self):
        if self.handle:
            close(self.handle)
            self.handle = None
