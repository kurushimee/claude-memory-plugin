"""Judges notes against a prompt with Qwen3-Reranker-4B on the GPU. llama-server loads the model for one prompt
and exits, so nothing stays in memory between prompts."""

import ctypes
import json
import os
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from . import vault

LLAMA = Path.home() / ".cache" / "mem" / "llama"
SERVER = LLAMA / "bin" / "llama-server.exe"
MODEL = LLAMA / "qwen3-reranker-4b-q4_k_m.gguf"
BODY_GATE = 0.45
TITLE_GATE = 0.1
DEADLINE = 25
CHUNK = 4
NEED = 3800  # MiB of free VRAM, the judge peaked at 3706 on the 2070
OWNED = (0, 0x80)  # WAIT_OBJECT_0, or WAIT_ABANDONED when the holder was killed
ASK = (
    "Given a user's message to a coding assistant and the assistant's previous reply, judge whether the memory note "
    "is about the specific subject, task or situation of this message. General advice that has nothing to do with "
    "this message does not count"
)


class Busy(Exception):
    """the judges of other prompts kept the GPU until the deadline"""


class Taken(Exception):
    """another program, like a game, holds so much VRAM that the judge would spill into system memory and run out of
    time"""


def scores(query, docs):
    """how well each doc fits the query, in order and as far as the deadline reaches, None when the model can't run
    here. The docs left over come up again on the next prompt, so a cut is no error unless the judge had a free GPU
    and still scored nothing. Raises Taken when another program holds the VRAM the judge needs"""
    if not SERVER.exists() or not MODEL.exists():
        return None
    end = time.monotonic() + DEADLINE
    out, alone = [], False
    try:
        with gpu_turn(end) as alone:
            if free_vram() < NEED:
                raise Taken
            with ranker(end - time.monotonic()) as rank:
                for i in range(0, len(docs), CHUNK):
                    out += rank(query, docs[i : i + CHUNK])
    except Busy:
        pass
    except Taken:
        raise
    except TimeoutError as e:
        if alone and not out:
            vault.log(f"judge scored nothing on a free GPU, no recall by meaning for this prompt: {e!r}")
    except Exception as e:
        vault.log(f"judge failed, no recall by meaning for this prompt: {e!r}")
        return None
    return out


@contextmanager
def gpu_turn(end):
    """holds the GPU for one judge on this machine, since two models don't fit in VRAM together and each then runs
    four times as long. Yields whether it was free at once"""
    k = kernel32()
    mutex = k.CreateMutexW(None, False, "Local\\mem-judge")
    try:
        alone = k.WaitForSingleObject(mutex, 0) in OWNED
        if not alone and k.WaitForSingleObject(mutex, int(max(0, end - time.monotonic()) * 1000)) not in OWNED:
            raise Busy
        try:
            yield alone
        finally:
            k.ReleaseMutex(mutex)
    finally:
        k.CloseHandle(mutex)


@contextmanager
def ranker(seconds=DEADLINE):
    """a rank(query, docs) function backed by llama-server, which runs only inside the with block"""
    port = free_port()
    args = [
        str(SERVER), "-m", str(MODEL), "--reranking", "-ngl", "99", "-np", "1", "-c", "4096", "-ub", "4096", "-b", "4096",
        "--port", str(port), "--no-webui",
    ]
    env = {**os.environ, "CUDA_CACHE_MAXSIZE": str(4 << 30)}
    server = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, creationflags=subprocess.CREATE_NO_WINDOW
    )
    job = die_with_this_process(server)
    end = time.monotonic() + seconds
    try:
        wait_ready(server, port, end)
        yield lambda query, docs: rerank(port, f"{ASK}\n{query}", docs, end)
    finally:
        server.kill()
        kernel32().CloseHandle(job)
        # the next judge loads only once this one's VRAM is free
        server.wait(10)


def free_vram():
    """MiB of VRAM no program holds"""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    return int(out.split()[0])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(server, port, end):
    while time.monotonic() < end:
        if server.poll() is not None:
            raise RuntimeError(f"llama-server exited with {server.returncode}")
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).status == 200:
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("llama-server did not load in time")


def rerank(port, query, docs, end):
    body = json.dumps({"query": query, "documents": docs, "top_n": len(docs)}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/rerank", body, {"Content-Type": "application/json"})
    results = json.load(urllib.request.urlopen(req, timeout=max(1, end - time.monotonic())))["results"]
    out = [0.0] * len(docs)
    for item in results:
        out[item["index"]] = item["relevance_score"]
    return out


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", ctypes.c_ulonglong * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def die_with_this_process(proc):
    """puts proc in a job that Windows kills once this process ends, so a hook killed mid prompt can't leave the
    model sitting in VRAM"""
    k = kernel32()
    job = k.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))  # JobObjectExtendedLimitInformation
    k.AssignProcessToJobObject(job, int(proc._handle))
    return job


def kernel32():
    k = ctypes.windll.kernel32
    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.CreateMutexW.restype = ctypes.c_void_p
    k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.ReleaseMutex.argtypes = [ctypes.c_void_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k
