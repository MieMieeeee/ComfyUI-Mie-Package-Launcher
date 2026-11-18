"""伴生服务生命周期管理: start / stop / status / update.

服务是生命周期单元 (用户拍板): 对外只有「服务起来了 / 停了 / 什么状态」,
内部 1~N 条命令 (openjutsu = build 一次性步骤 + proxy/app 两个长驻进程) 是实现细节.

语义对齐 WebuiProcessManager (老 webui 路径), 差异点全部来自「多进程 + 端口就绪」:
  - 就绪 = 全部 PortBinding 端口在监听 (start 路径端口优先不做 HTTP, 既有拍板)
  - stop = 进程树终止 + 端口复核 + **身份过滤**清残
  - pidfile = pidstore v2 多进程 (launcher/<service_id>.pid)

webui-legacy spec 不走本类 (strangler: 老五件套本期不动), 构造时显式拒绝.
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.companion import pidstore, proctree, registry


def _svc_log_path(app: Any, service_id: str) -> Path:
    """服务日志: <cwd>/launcher/<service_id>.log (build/proxy/app 三路输出合一, 带前缀)."""
    try:
        cwd = Path(getattr(app, "_cwd", ".") or ".").resolve()
    except Exception:
        cwd = Path(".").resolve()
    return cwd / "launcher" / (service_id + ".log")


def _port_listening(port: int, timeout: float = 0.5) -> bool:
    """127.0.0.1:port 能否连上 (最便宜的「在监听」判定, 不做 HTTP)."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except Exception:
        return False


# runtime 字符串 → 模块路径. runtime 的模块级函数接口 (duck typing):
#   resolve_paths(app, env_id=None) -> dict
#   check_deps(paths) -> {"ok", "missing", "available"}
#   build_steps(paths, ports, comfy_port) -> [步骤]      ← 新接口 (可选)
#   build_step_cmd / build_proxy_cmd / build_app_cmd       ← 老接口 (兼容)
#   comfyui_port(app) -> int
#   update(app, paths, on_progress=None) -> dict
#   ready_probe(paths, ports) -> bool                      ← 可选 (HTTP 就绪探针)
#   log_mode() -> "pipe" | "file"                          ← 可选 (子进程输出方式)
_RUNTIME_MODULES = {
    "openjutsu": "core.companion.openjutsu_runtime",
    "h3-engine": "core.companion.h3_runtime",
}


class CompanionServiceManager:
    """一个 (app, service_id) 对应一个实例. 不依赖 PyQt5, CLI/GUI 复用."""

    def __init__(self, app: Any, service_id: str, *, env_id: Optional[str] = None):
        self.app = app
        self.spec = registry.get(service_id)
        if self.spec.runtime == "webui-legacy":
            raise ValueError(
                f"服务 {service_id} 走 webui 老五件套 (strangler P1), "
                "请用 WebuiProcessManager 或 webui 子命令")
        self.env_id = env_id
        self._procs: Dict[str, Dict[str, Any]] = {}  # role -> {"proc": Popen, "thread": Thread}

    # ---------------- 路径 / 端口 ----------------

    def _runtime(self):
        """runtime 模块 (duck-typed 模块级函数接口).

        分发表在 _RUNTIME_MODULES: runtime 字符串 → 模块路径. 加新 runtime 只需
        加一条表项 + 一个模块, 不用再往 manager 里堆 if (旧实现是
        `if spec.runtime == "openjutsu"` 的硬编码 if, 第三个 runtime 就该拆表).
        """
        name = self.spec.runtime
        if name == "webui-legacy":
            raise ValueError(
                f"服务 {self.spec.id} 走 webui 老五件套 (strangler P1), "
                "请用 WebuiProcessManager 或 webui 子命令")
        mod_path = _RUNTIME_MODULES.get(name)
        if not mod_path:
            raise ValueError(f"未知 runtime: {name}")
        import importlib
        return importlib.import_module(mod_path)

    def _paths(self) -> Dict[str, Any]:
        return self._runtime().resolve_paths(self.app, env_id=self.env_id)

    def _ports(self) -> Dict[str, int]:
        return registry.resolved_ports(self.app, self.spec)

    def _root(self) -> Optional[Path]:
        """服务 root 的**未 resolve** 路径 (身份门用).

        身份门要靠命令行/工作目录里的**环境专属路径文本**把多个环境分开,
        所以这里不能 resolve 掉 junction (见 registry.resolve_root_raw).
        """
        return registry.resolve_root_raw(self.app, self.spec, env_id=self.env_id)

    def _pidfile_path(self) -> Path:
        try:
            cwd = Path(getattr(self.app, "_cwd", ".") or ".").resolve()
        except Exception:
            cwd = Path(".").resolve()
        return pidstore.default_path(cwd, self.spec.id)

    def _log_path(self) -> Path:
        return _svc_log_path(self.app, self.spec.id)

    def _identity_rules(self) -> List:
        return list(self.spec.identity.values())

    # ---------------- pidstore 读取 (含身份门) ----------------

    def _raw_store(self) -> Optional[dict]:
        return pidstore.read(self._pidfile_path())

    def _live_processes(self) -> List[Dict[str, Any]]:
        """读 pidstore, 逐 pid 存活 + 身份校验, 返 live 子集.

        全死 → 顺手清 pidfile (幽灵自愈, 同 webui._live_webui_pidfile_data 语义);
        部分死 → 只返活的 (stop 只杀活的, status 如实展示).
        """
        raw = self._raw_store()
        if raw is None:
            return []
        # 环境闸门: pidstore 记的是**别的环境**的实例 → 不认 (也不杀它).
        # pidfile 路径跨环境共用 (<cwd>/launcher/<service_id>.pid), 而 CLI 的 --env
        # 能指向别的环境; 少了这道闸, `service stop h3-engine --env X` 会杀掉 Y 环境
        # 正在跑的实例 (2026-11-18 接入 H3 时发现).
        store_env = raw.get("env_id")
        if store_env:
            eff_env = self._effective_env_id()
            if eff_env and store_env != eff_env:
                return []
        root = self._root()
        live: List[Dict[str, Any]] = []
        for e in raw.get("processes") or []:
            pid = e.get("pid")
            role = str(e.get("role") or "")
            rule = self.spec.identity.get(role)
            ok = False
            if rule is not None:
                ok = pidstore.is_alive(pid) and proctree.is_service_pid(pid, rule, root)
            else:
                # 未知 role: 任一身份规则命中即可 (向后兼容手改的 pidstore)
                ok = pidstore.is_alive(pid) and proctree.is_our_pid(pid, self._identity_rules(), root)
            if ok:
                live.append({"pid": pid, "role": role})
        if not live:
            try:
                pidstore.clear(self._pidfile_path())
                try:
                    getattr(self.app, "logger", None) and self.app.logger.warning(
                        "%s.pid 幽灵清理：记录的进程均已不在（或身份不符），按未运行处理",
                        self.spec.id)
                except Exception:
                    pass
            except Exception:
                pass
        return live

    def _try_adopt(self) -> bool:
        """收养: pidstore 失联但端口被**身份校验过**的本服务进程占用 → 重写 pidstore.

        与 ComfyUI 的 adopt_external_service 同思路 (只收养身份校验过的 PID);
        要求**每个**绑定端口都有命中身份的占用者, 任一端口是无关节程 → 不收养
        (走正常的端口占用报错路径).
        """
        root = self._root()
        ports = self._ports()
        processes: List[Dict[str, Any]] = []
        seen: set = set()
        for binding in self.spec.ports:
            port = ports.get(binding.role, binding.default_port)
            try:
                from core.probe import find_pids_by_port_safe
                occupy = find_pids_by_port_safe(str(port))
            except Exception:
                occupy = []
            matched = None
            for opid in occupy:
                if opid in seen or opid == os.getpid():
                    continue
                if proctree.is_our_pid(opid, self._identity_rules(), root):
                    matched = opid
                    break
            if matched is None:
                return False
            seen.add(matched)
            processes.append({"pid": matched, "role": binding.role})
        if not processes:
            return False
        try:
            pidstore.write(self._pidfile_path(), self.spec.id, processes, ports,
                           self._log_path(), env_id=self._effective_env_id())
            try:
                getattr(self.app, "logger", None) and self.app.logger.info(
                    "%s.pid 收养：端口占用者身份校验通过，重写 pidstore (pids=%s)",
                    self.spec.id, [e["pid"] for e in processes])
            except Exception:
                pass
        except Exception:
            return False
        return True

    def _effective_env_id(self) -> Optional[str]:
        try:
            return self._paths().get("env_id")
        except Exception:
            return self.env_id

    def _refresh_pidstore_from_ports(self) -> None:
        """按端口重新发现长命监听者, 校正 pidstore.

        背景 (2026-10-31 真机): app 的 root 进程是 `node npm-cli.js run start`,
        npm 把 `next start` 拉起来后**自己就退出** —— spawn 时记录的 root pid
        是短命进程, 退出后 pidstore 身份校验落空 → 页面误回「一键启动」而服务
        实际在跑. 端口上真正常驻的是 next 进程 (身份规则同样命中), 所以 start
        就绪后用端口重发现一次, 把 pidstore 换成长命的监听者 (proxy root 本就
        长命, 重发现到的还是它自己). 失败不影响 start 结果 (stop 的端口清残兜底).
        """
        try:
            from core.probe import find_pids_by_port_safe
            root = self._root()
            ports = self._ports()
            processes = []
            seen: set = set()
            for binding in self.spec.ports:
                port = ports.get(binding.role, binding.default_port)
                try:
                    occupy = find_pids_by_port_safe(str(port))
                except Exception:
                    occupy = []
                for opid in occupy:
                    if opid in seen or opid == os.getpid():
                        continue
                    if proctree.is_our_pid(opid, self._identity_rules(), root):
                        seen.add(opid)
                        processes.append({"pid": opid, "role": binding.role})
                        break
            if processes and len(processes) == len(self.spec.ports):
                pidstore.write(self._pidfile_path(), self.spec.id, processes, ports,
                               self._log_path(), env_id=self._effective_env_id())
                try:
                    getattr(self.app, "logger", None) and self.app.logger.info(
                        "%s.pid 校正：按端口重发现监听者 (pids=%s)",
                        self.spec.id, [e["pid"] for e in processes])
                except Exception:
                    pass
        except Exception:
            pass

    # ---------------- 对外 API ----------------

    def is_running(self) -> bool:
        """服务是否有活着的 (身份校验过) 进程.

        pidstore 失联时做一次收养兜底 (同 status): 覆盖「root 进程短命退出 /
        外部手动启动」—— 真机 2026-10-31: npm root 退出后 pidstore 落空, 页面
        轮询只调本方法, 不兜底就误回「一键启动」. 收养要求全部端口都有身份
        匹配的占用者, 且只在 pidstore 失联时才发生 (正常路径零端口扫描开销).
        """
        if self._live_processes():
            return True
        self._try_adopt()
        return bool(self._live_processes())

    def status(self) -> dict:
        """状态查询. 四态语义与 webui 对齐 (running=进程层, ready=加端口层):
        进程在+端口通=就绪; 进程在+端口不通=启动中; 进程不在+端口通=端口被占; 都不=未跑.
        """
        live = self._live_processes()
        if not live:
            # 收养尝试: 外部重启 (如 Manager 式 os.execv) 后 pidfile 失联的场景
            self._try_adopt()
            live = self._live_processes()
        ports = self._ports()
        raw = self._raw_store() or {}
        ports_state = {
            b.role: {"port": ports.get(b.role, b.default_port),
                     "listening": _port_listening(ports.get(b.role, b.default_port))}
            for b in self.spec.ports
        }
        running = bool(live)
        ready = running and all(v["listening"] for v in ports_state.values())
        url = None
        if self.spec.browser_url_role:
            br = ports_state.get(self.spec.browser_url_role)
            if br:
                url = f"http://127.0.0.1:{br['port']}"
        # 语义健康 (可选): runtime 能给出更细的判据时附上 (H3 的 /api/health)
        health = None
        if running:
            try:
                info = getattr(self._runtime(), "health_info", None)
                if callable(info):
                    health = info(self._paths(), ports)
            except Exception:
                health = None
        return {
            "service_id": self.spec.id,
            "name": self.spec.name,
            "running": running,
            "ready": ready,
            "pids": live,
            "ports": ports_state,
            "url": url,
            "log_path": str(self._log_path()),
            "since": raw.get("started_at"),
            "env_id": raw.get("env_id"),
            "health": health,
        }

    def start(self, *, timeout: float = 120.0, no_wait: bool = False) -> dict:
        """启动服务. 阻塞到全部端口就绪或 timeout (no_wait 则 spawn 完即返).

        返 {ok, exit_code, error, pids, ports, url, elapsed_sec, already_running,
            adopted, log_path, env_id}; exit_code 语义: 6=ComfyUI 未跑 / 7=未安装 /
            8=依赖缺失 / 1=其他失败 / 0=成功(含 already_running).
        """
        start_t = time.time()
        result = {
            "ok": False, "exit_code": 1, "error": None,
            "pids": [], "ports": {}, "url": None,
            "elapsed_sec": 0.0, "already_running": False, "adopted": False,
            "log_path": str(self._log_path()), "env_id": None,
            "service_id": self.spec.id,
        }
        def _fail(error: str, exit_code: int, **extra) -> dict:
            result.update({"ok": False, "exit_code": exit_code, "error": error,
                           "elapsed_sec": time.time() - start_t}, **extra)
            return result

        # 1. 已在跑 (身份校验过) → 短路
        live = self._live_processes()
        if live:
            result.update({"ok": True, "exit_code": 0, "already_running": True,
                           "pids": live, "ports": self._ports(),
                           "elapsed_sec": time.time() - start_t,
                           "env_id": self._effective_env_id()})
            return result

        # 2. 收养 (外部重启后 pidfile 失联, 端口占用者身份校验过)
        if self._try_adopt():
            live = self._live_processes()
            if live:
                result.update({"ok": True, "exit_code": 0, "already_running": True,
                               "adopted": True, "pids": live, "ports": self._ports(),
                               "elapsed_sec": time.time() - start_t,
                               "env_id": self._effective_env_id()})
                return result

        # 3. 可用性 (退出码 7)
        avail = registry.availability(self.app, self.spec, env_id=self.env_id)
        if not avail["available"]:
            missing = ", ".join(avail["missing_markers"])
            return _fail(f"服务未安装或当前环境无此服务: {self.spec.name}"
                         f" (root={avail['root']}, 缺 {missing})", 7)

        # 4. 依赖闸门 (退出码 8)
        try:
            paths = self._paths()
        except Exception as e:
            return _fail(f"路径解析失败: {e}", 7)
        deps = self._runtime().check_deps(paths)
        if not deps["ok"]:
            return _fail("依赖缺失: " + ", ".join(deps["missing"]), 8,
                         missing=deps["missing"])

        # 5. requires_comfyui (退出码 6, 不强启动 —— 自动起是 GUI 编排的事)
        if self.spec.requires_comfyui and not self._comfyui_running():
            return _fail("ComfyUI 未运行; 本服务需要先启动 ComfyUI (GUI 一键启动或 "
                         "先 start ComfyUI)", 6)

        # 6. 端口预检
        ports = self._ports()
        result["ports"] = ports
        result["env_id"] = paths.get("env_id")
        for binding in self.spec.ports:
            port = ports.get(binding.role, binding.default_port)
            try:
                from core.probe import find_pids_by_port_safe
                occupy = find_pids_by_port_safe(str(port))
            except Exception:
                occupy = []
            if occupy:
                return _fail(f"端口 {port} 已被占用 (PID: {', '.join(map(str, occupy))}),"
                             f" 请先停掉那个进程或改 {binding.config_key}",
                             1, port_in_use=True)

        # 7. 日志文件
        log_path = self._log_path()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            if log_path.exists():
                log_path.unlink()
        except Exception:
            pass

        def _append_log(text: str) -> None:
            try:
                with open(log_path, "a", encoding="utf-8", errors="replace") as hf:
                    hf.write(text)
            except Exception:
                pass

        _append_log(f"=== {self.spec.id} spawn at {datetime.now().isoformat()} ===\n")

        # 8. 步骤执行. 步骤由 runtime 决定 (新接口 build_steps): 一次性步骤
        #    ("once", 跑完必须退出 0) + 长驻步骤 ("long", 一直挂着).
        #    openjutsu 仍是老接口 (build_step_cmd/build_proxy_cmd/build_app_cmd),
        #    这里做兼容回落, 两个 runtime 共用同一条执行链.
        try:
            steps = self._build_steps(paths, ports)
        except Exception as e:
            return _fail(f"启动命令构造失败: {e}", 1)
        if not steps:
            return _fail("runtime 没有给出任何启动步骤", 1)

        log_mode = self._log_mode()
        processes: List[Dict[str, Any]] = []
        for step in steps:
            role = str(step.get("role") or "app")
            kind = str(step.get("kind") or "long")
            cmd, env, cwd = step["cmd"], step["env"], step["cwd"]
            _append_log(f"cmd[{role}]: {' '.join(str(c) for c in cmd)}\ncwd: {cwd}\n")
            if kind == "once":
                step_ok, step_err = self._run_step(cmd, env, cwd, log_path,
                                                   role=role, timeout=600)
                if not step_ok:
                    return _fail(f"步骤 {role} 失败: {step_err} (日志: {log_path})", 1)
                continue
            try:
                proc = self._spawn(role, cmd, env, cwd, log_path, log_mode=log_mode)
            except Exception as e:
                # 已起的部分进程清掉, 不留半套
                self._kill_spawned()
                self._clear_store()
                return _fail(f"spawn {role} 失败: {e}", 1)
            processes.append({"pid": proc.pid, "role": role})
            try:
                pidstore.write(self._pidfile_path(), self.spec.id, processes, ports,
                               log_path, env_id=paths.get("env_id"))
            except Exception:
                pass

        result["pids"] = processes
        if self.spec.browser_url_role:
            result["url"] = f"http://127.0.0.1:{ports.get(self.spec.browser_url_role, 0)}"

        # 10. 等就绪 (默认看端口; runtime 可再给一个语义探针, 如 H3 的
        #     /api/health —— 端口通不代表「是我们的服务」)
        if no_wait:
            result.update({"ok": True, "exit_code": 0,
                           "elapsed_sec": time.time() - start_t})
            return result

        probe = self._ready_probe()
        deadline = time.time() + timeout
        ready = False
        dead_roles: List[str] = []
        while time.time() < deadline:
            dead_roles = [role for role, v in self._procs.items()
                          if v["proc"].poll() is not None]
            if dead_roles:
                break
            if all(_port_listening(p) for p in ports.values()):
                if probe is not None:
                    try:
                        if not probe(paths, ports):
                            time.sleep(0.5)
                            continue
                    except Exception:
                        pass
                ready = True
                break
            time.sleep(0.5)

        if ready:
            # 就绪后按端口校正 pidstore (app 的 npm root 是短命进程, 见
            # _refresh_pidstore_from_ports; 不校正的话页面很快误判未跑)
            self._refresh_pidstore_from_ports()
            result["pids"] = [{"pid": e["pid"], "role": e["role"]}
                              for e in self._live_processes()] or processes
            result.update({"ok": True, "exit_code": 0,
                           "elapsed_sec": time.time() - start_t})
            return result

        if dead_roles:
            # 某根进程已死 → 半套状态无意义, 全清
            self._kill_spawned()
            self._clear_store()
            return _fail(f"进程启动即退出: {', '.join(dead_roles)} (日志: {log_path})", 1)

        # 超时但进程都活着: 语义同 webui (不杀, 留给用户 stop/查日志)
        try:
            getattr(self.app, "logger", None) and self.app.logger.warning(
                "%s 启动超时 (%.0fs), 进程仍在运行", self.spec.id, timeout)
        except Exception:
            pass
        return _fail(f"{self.spec.name} 启动超时 (未在 {timeout:.0f}s 内端口就绪;"
                     f" 日志: {log_path})", 1)

    def stop(self, *, timeout: float = 10.0, force: bool = False) -> dict:
        """停止服务 (幂等, 未跑返 ok=True). 树杀 + 端口复核 + 身份过滤清残.

        force=True: 跳过自有句柄的优雅 terminate, 直接树杀 (对外部 pid 无差别 ——
        外部 pid 本来就只能 taskkill).
        """
        start_t = time.time()
        live = self._live_processes()

        killed = False
        # 1. 自有 Popen 句柄: 优雅终止优先 (npm/node 能做清理), 不行再树杀
        if not force:
            for role, v in list(self._procs.items()):
                proc = v["proc"]
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=3)
                        killed = True
                except Exception:
                    pass

        # 2. 树杀所有 live pid (自有句柄未死 / 外部 pid)
        for e in live:
            if proctree.kill_tree(e["pid"], timeout=max(3.0, timeout)):
                killed = True

        # 3. 端口清残 (身份过滤: 只杀 cmdline/cwd 匹配的占用者)
        ports = self._ports()
        swept = proctree.sweep_stragglers(ports.values(), self._identity_rules(),
                                          self._root())
        if swept:
            killed = True

        # 4. 端口复核 (≤5s); 仍被占 → 如实上报 (占用者非本服务, 我们不误杀)
        residual = [p for p in ports.values() if _port_listening(p)]
        deadline = time.time() + 5.0
        while residual and time.time() < deadline:
            time.sleep(0.5)
            residual = [p for p in ports.values() if _port_listening(p)]

        # 5. 清 pidstore + 收 drain 线程
        self._clear_store()
        self._kill_spawned(join_only=True)

        return {
            "ok": True,
            "killed": killed,
            "residual_ports": residual,
            "elapsed_sec": time.time() - start_t,
            "error": None,
            "service_id": self.spec.id,
        }

    def install(self, *, on_progress=None, repo_url=None) -> dict:
        """下载安装服务本体 (runtime 提供 install 钩子时).

        幂等: 目标目录已有内容 → 跳过下载 (不删用户数据), 返回 already_exists.
        """
        rt = self._runtime()
        fn = getattr(rt, "install", None)
        if not callable(fn):
            return {"ok": False, "error": "服务 %s 不提供下载安装" % self.spec.name,
                    "exit_code": 1, "service_id": self.spec.id}
        try:
            paths = self._paths()
        except Exception as e:
            return {"ok": False, "error": "路径解析失败: %s" % e, "exit_code": 7,
                    "service_id": self.spec.id}
        try:
            res = fn(self.app, paths, on_progress=on_progress, repo_url=repo_url)
        except TypeError:
            res = fn(self.app, paths, on_progress=on_progress)
        except Exception as e:
            return {"ok": False, "error": "下载失败: %s" % e, "exit_code": 1,
                    "service_id": self.spec.id}
        res.setdefault("exit_code", 0 if res.get("ok") else 1)
        res["service_id"] = self.spec.id
        return res

    def setup(self, *, on_progress=None) -> dict:
        """装服务的运行依赖 (runtime 提供 setup 钩子时)."""
        rt = self._runtime()
        fn = getattr(rt, "setup", None)
        if not callable(fn):
            return {"ok": False, "error": "服务 %s 不需要安装依赖" % self.spec.name,
                    "exit_code": 1, "service_id": self.spec.id}
        try:
            paths = self._paths()
        except Exception as e:
            return {"ok": False, "error": "路径解析失败: %s" % e, "exit_code": 7,
                    "service_id": self.spec.id}
        try:
            res = fn(self.app, paths, on_progress=on_progress)
        except Exception as e:
            return {"ok": False, "error": "依赖安装失败: %s" % e, "exit_code": 1,
                    "service_id": self.spec.id}
        res.setdefault("exit_code", 0 if res.get("ok") else 1)
        res["service_id"] = self.spec.id
        return res

    def update(self, *, on_progress=None) -> dict:
        """更新链 (委托 runtime). 前置: 服务已安装且未在跑."""
        if self.is_running():
            return {"ok": False, "error": "服务正在运行, 请先 stop 再 update",
                    "exit_code": 1, "service_id": self.spec.id}
        avail = registry.availability(self.app, self.spec, env_id=self.env_id)
        if not avail["available"]:
            return {"ok": False, "error": "服务未安装, 无法更新", "exit_code": 7,
                    "service_id": self.spec.id}
        try:
            paths = self._paths()
        except Exception as e:
            return {"ok": False, "error": f"路径解析失败: {e}", "exit_code": 7,
                    "service_id": self.spec.id}
        res = self._runtime().update(self.app, paths, on_progress=on_progress)
        res.setdefault("exit_code", 0 if res.get("ok") else 1)
        res["service_id"] = self.spec.id
        return res

    # ---------------- 内部 ----------------

    def _port_of(self, ports: Dict[str, int], role: str, fallback: int) -> int:
        """某个 role 的生效端口 (spec 声明的默认值为兜底)."""
        for b in self.spec.ports:
            if b.role == role:
                return int(ports.get(role, b.default_port))
        return int(ports.get(role, fallback))

    def _build_steps(self, paths: Dict[str, Any], ports: Dict[str, int]) -> List[Dict[str, Any]]:
        """runtime 给出的启动步骤列表.

        新接口 (build_steps): 返回 [{"role", "kind": "once"|"long", "cmd", "env", "cwd"}].
        老接口兼容 (openjutsu): build_step_cmd / build_proxy_cmd / build_app_cmd,
        这里翻译成同一种形状 —— 执行链只有一条, 免得两个 runtime 各写一套.
        """
        rt = self._runtime()
        builder = getattr(rt, "build_steps", None)
        if builder is not None:
            steps = builder(paths, ports, self._comfyui_port())
            return list(steps or [])
        steps: List[Dict[str, Any]] = []
        step_cmd = getattr(rt, "build_step_cmd", None)
        if step_cmd is not None:
            cmd, env, cwd = step_cmd(paths)
            steps.append({"role": "build", "kind": "once",
                          "cmd": cmd, "env": env, "cwd": cwd})
        proxy_port = self._port_of(ports, "proxy", 8197)
        app_port = self._port_of(ports, "app", 8198)
        proxy_cmd = getattr(rt, "build_proxy_cmd", None)
        if proxy_cmd is not None:
            cmd, env, cwd = proxy_cmd(paths, proxy_port)
            steps.append({"role": "proxy", "kind": "long",
                          "cmd": cmd, "env": env, "cwd": cwd})
        app_cmd = getattr(rt, "build_app_cmd", None)
        if app_cmd is not None:
            cmd, env, cwd = app_cmd(paths, app_port, proxy_port, self._comfyui_port())
            steps.append({"role": "app", "kind": "long",
                          "cmd": cmd, "env": env, "cwd": cwd})
        return steps

    def _log_mode(self) -> str:
        """子进程输出方式: "pipe" (默认, launcher 进程内的 drain 线程转发) 或
        "file" (子进程直接写日志文件).

        "file" 的理由: CLI 起完就退出时, 管道读端随 launcher 进程一起消失,
        子进程再写 stdout 会抛 BrokenPipeError —— Flask 这类每次请求都写日志的
        服务会直接把请求打挂. 长驻服务一律用 file.
        """
        try:
            mode = getattr(self._runtime(), "log_mode", None)
            if callable(mode):
                return "file" if str(mode()) == "file" else "pipe"
        except Exception:
            pass
        return "pipe"

    def _ready_probe(self):
        """runtime 的语义就绪探针 (可选): fn(paths, ports) -> bool.

        默认只看端口在不在听. H3 提供了 HTTP 健康探针 (/api/health) —— 端口通
        不等于「跑的是我们的工作台」, 端口被别的 app 抢走时端口照样是通的.
        """
        try:
            probe = getattr(self._runtime(), "ready_probe", None)
            if callable(probe):
                return probe
        except Exception:
            pass
        return None

    def _comfyui_running(self) -> bool:
        try:
            from core.cli.runner import service_status
            return bool((service_status(self.app) or {}).get("running"))
        except Exception:
            return False

    def _comfyui_port(self) -> int:
        try:
            return int(self._runtime().comfyui_port(self.app))
        except Exception:
            return 8188

    def _spawn(self, role: str, cmd: list, env: dict, cwd: str, log_path: Path,
               log_mode: str = "pipe"):
        """起一个长驻子进程.

        log_mode="file": 子进程 stdout/stderr 直接指向日志文件 (父进程这边关掉
        自己的句柄, 子进程持有独立副本) —— launcher 退出后子进程照样能写日志.
        log_mode="pipe": 老行为, launcher 进程内的 drain 线程把管道内容写进日志
        (带 "[role] " 前缀, 多进程输出合一的可读性靠它).
        """
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if log_mode == "file":
            fh = open(log_path, "ab")
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                    cwd=cwd, env=env, close_fds=True, creationflags=creationflags,
                )
            finally:
                try:
                    fh.close()
                except Exception:
                    pass
            self._procs[role] = {"proc": proc, "thread": None}
            return proc
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, cwd=cwd, env=env, close_fds=True,
            creationflags=creationflags,
        )
        t = threading.Thread(target=self._drain, args=(proc, role, log_path),
                             daemon=True, name=f"{self.spec.id}_{role}_drain")
        t.start()
        self._procs[role] = {"proc": proc, "thread": t}
        return proc

    def _drain(self, proc: subprocess.Popen, role: str, log_path: Path) -> None:
        """逐行写日志, 加 [role] 前缀 (多进程输出合一的可读性靠它)."""
        stream = None
        try:
            if proc.stdout is None:
                return
            stream = proc.stdout
            prefix = ("[" + role + "] ").encode("utf-8")
            for raw in stream:
                try:
                    with open(log_path, "ab") as lf:
                        lf.write(prefix + raw)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def _run_step(self, cmd: list, env: dict, cwd: str, log_path: Path, *,
                  role: str, timeout: float) -> tuple:
        """一次性步骤: Popen + 流式写日志 + 有界等待. 返 (ok, error)."""
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, cwd=cwd, env=env,
                                    close_fds=True, creationflags=creationflags)
        except Exception as e:
            return False, str(e)
        t = threading.Thread(target=self._drain, args=(proc, role, log_path),
                             daemon=True, name=f"{self.spec.id}_{role}_step")
        t.start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            rc = proc.poll()
            if rc is not None:
                t.join(timeout=2.0)
                return (rc == 0), (None if rc == 0 else f"exit {rc}")
            time.sleep(0.3)
        proctree.kill_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        t.join(timeout=2.0)
        return False, f"超时 (>{timeout:.0f}s)"

    def _kill_spawned(self, *, join_only: bool = False) -> None:
        """清理自有句柄记录; join_only=True 只收线程不杀进程 (进程已被树杀的收尾)."""
        for role, v in list(self._procs.items()):
            proc = v["proc"]
            if not join_only:
                try:
                    if proc.poll() is None:
                        proctree.kill_tree(proc.pid)
                except Exception:
                    pass
        for role, v in list(self._procs.items()):
            t = v.get("thread")
            if t is None:
                continue
            try:
                t.join(timeout=2.0)
            except Exception:
                pass
        self._procs.clear()

    def _clear_store(self) -> None:
        try:
            pidstore.clear(self._pidfile_path())
        except Exception:
            pass
