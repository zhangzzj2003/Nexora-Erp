"""在一次性 macOS CI 主机上演练打包服务的安装、升级与回退。"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_ROOT = Path("/Library/Application Support/Nexora ERP")
PLIST = Path("/Library/LaunchDaemons/com.nexora.erp.host.plist")
LABEL = "system/com.nexora.erp.host"
SUPPLIER = "CI Mac 系统升级供应商"


def require_disposable_runner(system_root: Path, plist: Path, ci_marker: str | None) -> None:
    # 安装命令使用正式系统路径；仅在空白 CI 主机运行，已有资料时立即退出。
    if ci_marker != "true":
        raise RuntimeError("此检查只允许在一次性 GitHub Actions 主机运行")
    if system_root.exists() or system_root.is_symlink() or plist.exists() or plist.is_symlink():
        raise RuntimeError("发现已有 Nexora 系统服务或资料，拒绝覆盖")


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def command(binary: Path, *args: str, success: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=90)
    if success and result.returncode:
        raise RuntimeError(f"打包服务命令 {args[0]} 失败：{result.stderr[-1500:]}")
    if not success and result.returncode == 0:
        raise AssertionError(f"预期失败的打包服务命令 {args[0]} 却成功")
    return result


def request_json(port: int, certificate: Path, route: str, payload: dict | None = None,
                 token: str | None = None, *, method: str | None = None) -> dict | list:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://127.0.0.1:{port}{route}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers, method=method,
    )
    # 业务检查仍核验实例证书，不能把其他进程的 HTTPS 响应误判为恢复成功。
    context = ssl.create_default_context(cafile=str(certificate))
    with urllib.request.urlopen(request, context=context, timeout=2) as response:
        return json.load(response)


def wait_healthy(port: int, certificate: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if certificate.is_file():
            try:
                if request_json(port, certificate, "/api/v1/health").get("status") == "ok":
                    return
            except (OSError, urllib.error.URLError, ssl.SSLError):
                pass
        time.sleep(0.25)
    log = SYSTEM_ROOT / "logs" / "host.err.log"
    detail = log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.is_file() else ""
    raise RuntimeError(f"系统服务没有通过 HTTPS 健康检查：{detail}")


def wait_offline(port: int, certificate: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            request_json(port, certificate, "/api/v1/health")
        except (OSError, urllib.error.URLError, ssl.SSLError):
            return
        time.sleep(0.25)
    raise RuntimeError("停止系统服务后 HTTPS 仍可访问")


def verify_supplier(port: int, certificate: Path, password: str, supplier_id: int) -> None:
    login = request_json(port, certificate, "/api/v1/auth/login",
                         {"username": "ci_admin", "password": password})
    # 服务重启和升级后必须沿用已经保存的实例规则。
    numbering = request_json(port, certificate, "/api/v1/system/document-numbering", token=login["token"])
    if not numbering['configured'] or numbering['style'] != 'english' or numbering['timezone'] != 'America/New_York':
        raise AssertionError('升级后编号规则发生变化')
    rows = request_json(port, certificate, "/api/v1/suppliers", token=login["token"])
    if not any(row["id"] == supplier_id and row["name"] == SUPPLIER for row in rows):
        raise AssertionError("升级或回退后无法读取原供应商")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cleanup_owned_install(port: int, certificate: Path, installed_binary: Path) -> None:
    # 清理只针对开场确认不存在、由这次 CI 安装创建的系统路径。
    if installed_binary.is_file():
        subprocess.run([str(installed_binary), "stop"], capture_output=True, timeout=30)
    if subprocess.run(["launchctl", "print", LABEL], capture_output=True).returncode == 0:
        subprocess.run(["launchctl", "bootout", LABEL], check=True)
    if certificate.is_file():
        wait_offline(port, certificate)
    PLIST.unlink(missing_ok=True)
    if SYSTEM_ROOT.exists():
        shutil.rmtree(SYSTEM_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 macOS 打包服务的系统安装和升级回退")
    parser.add_argument("--source", type=Path,
                        default=ROOT / "release/mac-arm64/Nexora ERP.app/Contents/Resources/backend-service")
    args = parser.parse_args()
    if sys.platform != "darwin" or os.geteuid() != 0:
        raise RuntimeError("此检查需要 macOS 管理员权限")
    require_disposable_runner(SYSTEM_ROOT, PLIST, os.environ.get("GITHUB_ACTIONS"))
    if subprocess.run(["launchctl", "print", LABEL], capture_output=True).returncode == 0:
        raise RuntimeError("已有同名 LaunchDaemon，拒绝接管")
    source = args.source.resolve()
    binary = source / "nexora-server"
    if not binary.is_file():
        raise FileNotFoundError(f"缺少打包服务程序：{binary}")

    with tempfile.TemporaryDirectory(prefix="nexora-installed-upgrade-", dir="/private/tmp") as directory:
        temporary = Path(directory)
        data_dir = temporary / "data"
        certificate = data_dir / "server.crt"
        port = available_port()
        config = temporary / "request.json"
        config.write_text(json.dumps({"name": "CI Mac 固定主机", "data_dir": str(data_dir),
                                      "port": port}), encoding="utf-8")
        installed_binary = SYSTEM_ROOT / "service" / "nexora-server"
        try:
            command(binary, "install", "--request", str(config), "--source", str(source))
            wait_healthy(port, certificate)
            password = "CiMacSmoke-" + os.urandom(16).hex()
            request_json(port, certificate, "/api/v1/setup/admin",
                         {"username": "ci_admin", "password": password})
            login = request_json(port, certificate, "/api/v1/auth/login",
                                 {"username": "ci_admin", "password": password})
            # 新实例必须先由管理员确认编号规则，安装与恢复验收走同一初始化流程。
            request_json(port, certificate, "/api/v1/system/document-numbering",
                         {"style": "english", "timezone_mode": "specified", "timezone": "America/New_York", "version": 0},
                         login["token"], method="PUT")
            supplier = request_json(port, certificate, "/api/v1/suppliers",
                                    {"name": SUPPLIER}, login["token"])
            original_certificate_hash = sha256(certificate)
            verify_supplier(port, certificate, password, supplier["id"])

            command(installed_binary, "stop")
            wait_offline(port, certificate)
            command(installed_binary, "start")
            wait_healthy(port, certificate)
            verify_supplier(port, certificate, password, supplier["id"])

            command(installed_binary, "upgrade", "--source", str(source))
            wait_healthy(port, certificate)
            verify_supplier(port, certificate, password, supplier["id"])
            if sha256(certificate) != original_certificate_hash:
                raise AssertionError("正常升级后证书发生变化")
            archives = list((SYSTEM_ROOT / "backups").glob("upgrade-*.nexora-backup"))
            if len(archives) != 1:
                raise AssertionError("正常升级没有生成唯一的升级前备份")
            with zipfile.ZipFile(archives[0]) as archive:
                if set(archive.namelist()) != {"manifest.json", "nexora.db", "server.crt", "server.key"}:
                    raise AssertionError("升级前备份不完整")
                if hashlib.sha256(archive.read("server.crt")).hexdigest() != original_certificate_hash:
                    raise AssertionError("升级前备份没有保留原证书")

            broken = temporary / "broken-service"
            shutil.copytree(source, broken)
            (broken / "nexora-server").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            (broken / "nexora-server").chmod(0o755)
            original_binary_hash = sha256(installed_binary)
            command(installed_binary, "upgrade", "--source", str(broken), success=False)
            wait_healthy(port, certificate)
            verify_supplier(port, certificate, password, supplier["id"])
            if sha256(installed_binary) != original_binary_hash or sha256(certificate) != original_certificate_hash:
                raise AssertionError("失败升级没有恢复原程序和证书")
        finally:
            cleanup_owned_install(port, certificate, installed_binary)
    print("macOS 系统服务安装、启停、升级备份及失败回退检查通过")


if __name__ == "__main__":
    main()
