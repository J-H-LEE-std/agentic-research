"""
SSE 푸시 알림 브릿지.
- notify()          : 동기 스레드(runner, db)에서 상태 변경 시 호출
- wait_for_change() : SSE 제너레이터가 대기; notify() 또는 timeout에 wake-up
"""
import asyncio
import threading

_waiters: list = []
_lock = threading.Lock()


def _set_if_pending(fut: asyncio.Future):
    if not fut.done():
        fut.set_result(None)


def notify():
    """상태 변경을 모든 대기 중인 SSE 스트림에 알린다."""
    with _lock:
        waiters = list(_waiters)
    for fut in waiters:
        if not fut.done():
            try:
                fut.get_loop().call_soon_threadsafe(_set_if_pending, fut)
            except Exception:
                pass


async def wait_for_change(timeout: float = 30.0) -> bool:
    """notify() 호출 또는 timeout까지 대기. 알림이 왔으면 True 반환."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    with _lock:
        _waiters.append(fut)
    try:
        await asyncio.wait_for(fut, timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        with _lock:
            try:
                _waiters.remove(fut)
            except ValueError:
                pass
