"""单实例锁：同一份数据目录只允许一个进程写入。

两个实例同时采集会把同一份流量各记一次，统计直接翻倍，
所以按「数据目录的数据库路径」加锁；不同数据目录的两份副本互不影响。

判定用两层，任一认为「已被占用」就不启动：
  1. 共享内存（QSharedMemory），用于兼容老版本进程；
  2. 本地 socket 端点（QLocalServer）——它能 listen 成功才算独占，
     Windows 上同名管道随进程销毁，因此不会残留僵尸端点。

端点同时承担「唤醒」职责：窗口可以被收起到托盘而进程不退，
此时用户再双击 exe 只会看到「已经在运行」，很容易以为程序坏了。
新实例连上去打个招呼，老实例把窗口唤到前台，新实例自己退出。

提权重启时需要先 `release_single_instance()` 释放上面两把锁，
否则新实例启动后会被自己原来的锁拦住。
"""
from __future__ import annotations

import hashlib

# 单实例锁的 key 前缀（含共享内存名与本地 socket 名）。沿用旧标识是为了让
# 更名前后的两个版本互相识别，避免升级途中同时跑出两个采集器。
_KEY_PREFIX = "NetUsageMonitor."
_GUARD_ATTR = "_instance_guard"        # QSharedMemory 引用
_SERVER_ATTR = "_activate_server"      # QLocalServer 引用


def _key_for(scope: str) -> str:
    return _KEY_PREFIX + hashlib.sha1(scope.encode("utf-8")).hexdigest()[:24]


def _activate_name(scope: str) -> str:
    return _KEY_PREFIX + "show." + hashlib.sha1(scope.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------- 锁
def _probe_shared_memory(app, scope: str) -> bool | None:
    """True=本进程新建成功，False=已有进程持有，None=无法判定。"""
    try:
        from PySide6.QtCore import QSharedMemory
    except ImportError:
        return None
    shm = QSharedMemory(_key_for(scope))
    try:
        if shm.attach():
            shm.detach()
            return False
        if not shm.create(1):
            return None
        setattr(app, _GUARD_ATTR, shm)    # 持有引用，进程存活期间不释放
        return True
    except Exception:
        return None


def claim_single_instance(app, scope: str) -> bool | None:
    """申请单实例占用。True=本进程持锁，False=已有实例在跑，None=无法判定。"""
    if app is None:
        return None
    if _probe_shared_memory(app, scope) is False:
        return False
    server = _listen(app, scope)
    if server is None:
        # 端点已被别的进程占用：确实有实例在跑。
        # 不再调用 removeServer——那会把对方的唤醒端点抢走。
        shm = getattr(app, _GUARD_ATTR, None)
        if shm is not None:
            try:
                shm.detach()
            except Exception:
                pass
            try:
                setattr(app, _GUARD_ATTR, None)
            except Exception:
                pass
        return False
    setattr(app, _SERVER_ATTR, server)
    return True


def bind_activate_handler(app, on_activate) -> bool:
    """把「有新实例来打招呼」绑定到回调（通常是显示主窗口）。"""
    server = getattr(app, _SERVER_ATTR, None)
    if server is None:
        return False

    def _handle():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is not None:
                try:
                    conn.disconnectFromServer()
                except Exception:
                    pass
        try:
            on_activate()
        except Exception:
            pass

    server.newConnection.connect(_handle)
    return True


def release_single_instance(app=None) -> bool:
    """主动释放本进程持有的锁，供「提权重启」前使用。"""
    if app is None:
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
        except Exception:
            return False
    if app is None:
        return False

    released = False
    shm = getattr(app, _GUARD_ATTR, None)
    if shm is not None:
        try:
            shm.detach()
            released = True
        except Exception:
            pass
        try:
            setattr(app, _GUARD_ATTR, None)
        except Exception:
            pass

    server = getattr(app, _SERVER_ATTR, None)
    if server is not None:
        try:
            server.close()
            released = True
        except Exception:
            pass
        try:
            setattr(app, _SERVER_ATTR, None)
        except Exception:
            pass
    return released


# ---------------------------------------------------------------- 唤醒
def _listen(app, scope: str):
    try:
        from PySide6.QtNetwork import QLocalServer
    except ImportError:
        return None
    if app is None:
        return None
    try:
        server = QLocalServer(app)
        if not server.listen(_activate_name(scope)):
            return None
        return server
    except Exception:
        return None


def notify_running_instance(scope: str, timeout_ms: int = 1500) -> bool:
    """新实例侧：通知已在运行的那个实例把窗口显示出来。成功返回 True。"""
    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError:
        return False
    sock = QLocalSocket()
    try:
        sock.connectToServer(_activate_name(scope))
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(max(200, timeout_ms // 2))
        sock.disconnectFromServer()
        return True
    except Exception:
        return False
    finally:
        try:
            sock.abort()
        except Exception:
            pass
