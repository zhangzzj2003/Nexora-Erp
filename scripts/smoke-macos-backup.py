"""用 macOS 安装包内的服务程序验证在线备份和独立恢复。"""

import argparse
import hashlib
import json
import secrets
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
SUPPLIER_NAME = "CI Mac 恢复验收供应商"


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def start_service(binary: Path, data_dir: Path, port: int, log_path: Path) -> subprocess.Popen:
    # 两次启动都使用安装包内的可执行文件，避免只验证源码的导入路径。
    with log_path.open("wb") as log:
        return subprocess.Popen(
            [str(binary), "--data-dir", str(data_dir), "--name", "Mac 打包恢复验收", "--port", str(port)],
            stdout=log, stderr=subprocess.STDOUT,
        )


def stop_service(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


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
    # 隔离测试实例也校验证书；恢复后继续使用原证书才能通过 TLS。
    context = ssl.create_default_context(cafile=str(certificate))
    with urllib.request.urlopen(request, context=context, timeout=2) as response:
        return json.load(response)


def wait_healthy(process: subprocess.Popen, port: int, certificate: Path, log_path: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if certificate.is_file():
            try:
                if request_json(port, certificate, "/api/v1/health").get("status") == "ok":
                    return
            except (OSError, urllib.error.URLError, ssl.SSLError):
                pass
        time.sleep(0.25)
    detail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    raise RuntimeError(f"打包服务未在 30 秒内通过 HTTPS 健康检查：\n{detail}")


def verify_supplier(port: int, certificate: Path, password: str, supplier_id: int) -> None:
    login = request_json(port, certificate, "/api/v1/auth/login",
                         {"username": "ci_admin", "password": password})
    # 备份恢复及安装升级须沿用数据库中的规则，不能重置首次设置。
    numbering = request_json(port, certificate, "/api/v1/system/document-numbering", token=login["token"])
    if not numbering['configured'] or numbering['style'] != 'english' or numbering['timezone'] != 'America/New_York':
        raise AssertionError('恢复或升级后编号规则发生变化')
    suppliers = request_json(port, certificate, "/api/v1/suppliers", token=login["token"])
    if not any(row["id"] == supplier_id and row["name"] == SUPPLIER_NAME for row in suppliers):
        raise AssertionError("恢复后的业务资料与原实例不一致")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 macOS 打包服务的在线备份和独立恢复")
    parser.add_argument("--source", type=Path,
                        default=ROOT / "release/mac-arm64/Nexora ERP.app/Contents/Resources/backend-service")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise RuntimeError("此检查只在 macOS 上运行")
    binary = args.source.resolve() / "nexora-server"
    if not binary.is_file():
        raise FileNotFoundError(f"缺少打包服务程序：{binary}")

    with tempfile.TemporaryDirectory(prefix="nexora-mac-backup-smoke-") as directory:
        root = Path(directory)
        source_dir = root / "source"
        restored_dir = root / "restored"
        archive = root / "instance.nexora-backup"
        source_port = available_port()
        source_log = root / "source.log"
        source = start_service(binary, source_dir, source_port, source_log)
        try:
            certificate = source_dir / "server.crt"
            wait_healthy(source, source_port, certificate, source_log)
            original_id = request_json(source_port, certificate, "/api/v1/server/info")["id"]
            password = secrets.token_urlsafe(24)
            request_json(source_port, certificate, "/api/v1/setup/admin",
                         {"username": "ci_admin", "password": password})
            login = request_json(source_port, certificate, "/api/v1/auth/login",
                                 {"username": "ci_admin", "password": password})
            # 新实例必须先由管理员确认编号规则，安装与恢复验收走同一初始化流程。
            request_json(source_port, certificate, "/api/v1/system/document-numbering",
                         {"style": "english", "timezone_mode": "specified", "timezone": "America/New_York", "version": 0},
                         login["token"], method="PUT")
            supplier = request_json(source_port, certificate, "/api/v1/suppliers",
                                    {"name": SUPPLIER_NAME}, login["token"])
            verify_supplier(source_port, certificate, password, supplier["id"])
            original_certificate_hash = sha256(certificate)

            # 运行中的数据库必须通过打包程序生成一致快照，不能直接复制 SQLite 文件。
            subprocess.run([str(binary), "backup", "--data-dir", str(source_dir),
                            "--output", str(archive)], check=True, capture_output=True, text=True)
            with zipfile.ZipFile(archive) as backup:
                if set(backup.namelist()) != {"manifest.json", "nexora.db", "server.crt", "server.key"}:
                    raise AssertionError("成组备份缺少数据库或证书文件")

                # 损坏的散列必须在发布恢复目录前被拒绝，避免留下半套可误用的实例。
                broken = root / "broken.nexora-backup"
                with zipfile.ZipFile(broken, "w") as target:
                    manifest = json.loads(backup.read("manifest.json"))
                    manifest["sha256"]["nexora.db"] = "0" * 64
                    target.writestr("manifest.json", json.dumps(manifest))
                    for name in ("nexora.db", "server.crt", "server.key"):
                        target.writestr(name, backup.read(name))
            invalid_dir = root / "invalid"
            rejected = subprocess.run([str(binary), "restore", "--archive", str(broken),
                                       "--data-dir", str(invalid_dir)], capture_output=True, text=True)
            if rejected.returncode == 0 or invalid_dir.exists():
                raise AssertionError("损坏备份没有被安全拒绝")

            subprocess.run([str(binary), "restore", "--archive", str(archive),
                            "--data-dir", str(restored_dir)], check=True, capture_output=True, text=True)
            if sha256(restored_dir / "server.crt") != original_certificate_hash:
                raise AssertionError("恢复后的证书发生变化")
        finally:
            stop_service(source)

        restored_port = available_port()
        restored_log = root / "restored.log"
        restored = start_service(binary, restored_dir, restored_port, restored_log)
        try:
            restored_certificate = restored_dir / "server.crt"
            wait_healthy(restored, restored_port, restored_certificate, restored_log)
            if request_json(restored_port, restored_certificate, "/api/v1/server/info")["id"] != original_id:
                raise AssertionError("恢复后的服务实例身份发生变化")
            verify_supplier(restored_port, restored_certificate, password, supplier["id"])
        finally:
            stop_service(restored)
    print("macOS 打包服务在线备份、独立恢复和损坏归档拒绝检查通过")


if __name__ == "__main__":
    main()
