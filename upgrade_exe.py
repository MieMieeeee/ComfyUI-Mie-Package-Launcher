"""
启动器升级脚本 - 将新版本 exe 上传到 gitee 并发布

用法:
    python upgrade_exe.py <exe文件路径> [版本号] [--test] [--no-push] [-c changelog]

示例:
    python upgrade_exe.py dist/ComfyUI启动器.exe
    python upgrade_exe.py dist/ComfyUI启动器.exe v1.0.9
    python upgrade_exe.py dist/ComfyUI启动器.exe v1.0.10-beta --test
"""

import os
import sys
import json
import hashlib
import shutil
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

GITEE_REPO_PATH = Path(r"F:\comfyui-mie-resources")
GITEE_REMOTE = "origin"
PROJECT_ROOT = Path(__file__).parent


class UpgradeScript:
    def __init__(self, channel="stable"):
        self.channel = channel
        self.exe_path = None
        self.version = None
        self.changelog = "版本更新"
        self.no_push = False
        self.file_size = None
        self.sha256_hash = None
        
        if channel == "test":
            self.releases_dir = GITEE_REPO_PATH / "launcher" / "releases" / "test"
            self.updates_dir = GITEE_REPO_PATH / "launcher" / "updates" / "test"
        else:
            self.releases_dir = GITEE_REPO_PATH / "launcher" / "releases"
            self.updates_dir = GITEE_REPO_PATH / "launcher" / "updates"
        self.index_file = self.updates_dir / "index.json"

    def parse_args(self, args=None):
        parser = argparse.ArgumentParser(
            description="启动器升级脚本 - 将新版本 exe 上传到 gitee 并发布",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
示例:
    python upgrade_exe.py dist/ComfyUI启动器.exe
    python upgrade_exe.py dist/ComfyUI启动器.exe v1.0.9
    python upgrade_exe.py dist/ComfyUI启动器.exe v1.0.10-beta --test
    python upgrade_exe.py dist/ComfyUI启动器.exe v1.0.10-beta --test --no-push -c "修复重大bug"
            """
        )
        parser.add_argument("exe_path", help="exe文件路径")
        parser.add_argument("version", nargs="?", help="版本号 (如 v1.0.9), 不提供则自动从 build_parameters.json 检测")
        parser.add_argument("--test", action="store_true", help="发布到测试频道")
        parser.add_argument("--no-push", action="store_true", help="仅准备文件，不推送到远程")
        parser.add_argument("-c", "--changelog", type=str, default="版本更新", help="更新日志")
        
        parsed = parser.parse_args(args)
        
        if parsed.test:
            self.channel = "test"
            self.releases_dir = GITEE_REPO_PATH / "launcher" / "releases" / "test"
            self.updates_dir = GITEE_REPO_PATH / "launcher" / "updates" / "test"
            self.index_file = self.updates_dir / "index.json"
        
        self.exe_path = Path(parsed.exe_path)
        self.version = parsed.version
        self.changelog = parsed.changelog
        self.no_push = parsed.no_push
        
        return parsed

    def detect_version(self):
        if self.version:
            return self.version
        
        build_params_file = PROJECT_ROOT / "build_parameters.json"
        if build_params_file.exists():
            with open(build_params_file, "r", encoding="utf-8") as f:
                params = json.load(f)
                version = params.get("version", "")
                if version:
                    self.version = version
                    print(f"自动检测到版本: {self.version}")
                    return self.version
        
        raise ValueError("无法自动检测版本，请通过参数指定版本号")

    def calculate_hash(self):
        sha256_hash = hashlib.sha256()
        with open(self.exe_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        self.sha256_hash = sha256_hash.hexdigest()
        print(f"SHA256: {self.sha256_hash}")
        return self.sha256_hash

    def get_file_size(self):
        self.file_size = self.exe_path.stat().st_size
        print(f"文件大小: {self.file_size} bytes ({self.file_size / (1024*1024):.2f} MB)")
        return self.file_size

    def prepare_release_filename(self):
        version_str = self.version.lstrip("v")
        exe_name = self.exe_path.name
        if "启动器" in exe_name:
            base_name = exe_name.split("启动器")[0] + "启动器"
            ext = self.exe_path.suffix
            return f"{base_name}_{version_str}{ext}"
        else:
            stem = self.exe_path.stem
            ext = self.exe_path.suffix
            return f"{stem}_{version_str}{ext}"

    def copy_exe_to_releases(self):
        self.releases_dir.mkdir(parents=True, exist_ok=True)
        
        dest_filename = self.prepare_release_filename()
        dest_path = self.releases_dir / dest_filename
        
        shutil.copy2(self.exe_path, dest_path)
        print(f"已复制文件到: {dest_path}")
        return dest_path

    def load_or_create_index(self):
        if self.index_file.exists():
            with open(self.index_file, "r", encoding="utf-8") as f:
                index_data = json.load(f)
            print(f"已加载现有 index.json")
        else:
            index_data = {
                "latest_version": "",
                "release_date": "",
                "download_url": "",
                "file_size": 0,
                "sha256": "",
                "changelog": "",
                "min_version": "v0.0.0",
                "prerelease": self.channel == "test"
            }
            print(f"将创建新的 index.json")
        
        return index_data

    def update_index_json(self, release_path):
        index_data = self.load_or_create_index()
        
        dest_filename = release_path.name
        
        if self.channel == "test":
            download_url = f"https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/releases/test/{dest_filename}"
        else:
            download_url = f"https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/releases/{dest_filename}"
        
        index_data["latest_version"] = self.version
        index_data["release_date"] = datetime.now().strftime("%Y-%m-%d")
        index_data["download_url"] = download_url
        index_data["file_size"] = self.file_size
        index_data["sha256"] = self.sha256_hash
        index_data["changelog"] = self.changelog
        index_data["prerelease"] = self.channel == "test"
        
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        
        print(f"已更新 index.json: {self.index_file}")
        print(f"  版本: {self.version}")
        print(f"  日期: {index_data['release_date']}")
        print(f"  URL: {download_url}")
        
        return index_data

    def git_add_commit_push(self):
        if not GITEE_REPO_PATH.exists():
            print(f"错误: Gitee 仓库路径不存在: {GITEE_REPO_PATH}")
            return False
        
        original_dir = os.getcwd()
        os.chdir(GITEE_REPO_PATH)
        
        try:
            subprocess.run(["git", "add", "."], check=True, capture_output=True)
            
            result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
            if not result.stdout.strip():
                print("没有需要提交的更改")
                return True
            
            commit_msg = f"release: {self.version} ({self.channel} channel)"
            print(f"执行 git commit: {commit_msg}")
            subprocess.run(["git", "commit", "-m", commit_msg], check=True, capture_output=True)
            
            if self.no_push:
                print("--no-push 模式: 跳过 git push")
                return True
            
            print(f"执行 git push {GITEE_REMOTE} ...")
            subprocess.run(["git", "push", GITEE_REMOTE, "master"], check=True, capture_output=True)
            print("推送成功!")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"Git 操作失败: {e}")
            if e.stdout:
                print(f"stdout: {e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout}")
            if e.stderr:
                print(f"stderr: {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}")
            return False
        finally:
            os.chdir(original_dir)

    def run(self, args=None):
        print(f"=== 启动器升级脚本 ===")
        print(f"频道: {self.channel}")
        
        self.parse_args(args)
        
        if not self.exe_path.exists():
            print(f"错误: exe 文件不存在: {self.exe_path}")
            return False
        
        self.detect_version()
        self.calculate_hash()
        self.get_file_size()
        release_path = self.copy_exe_to_releases()
        self.update_index_json(release_path)
        self.git_add_commit_push()
        
        print(f"\n=== 完成 ===")
        print(f"版本 {self.version} 已准备好发布到 {self.channel} 频道")
        if self.no_push:
            print("(注意: 使用 --no-push，未推送到远程)")
        
        return True


def main():
    script = UpgradeScript()
    try:
        success = script.run()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
