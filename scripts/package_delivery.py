"""Build a source-only delivery ZIP from the committed Git tree."""
import subprocess
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    safe = f"safe.directory={root.as_posix()}"
    status = subprocess.check_output(["git", "-c", safe, "status", "--porcelain"], cwd=root, text=True)
    if status.strip():
        raise SystemExit("工作区尚有未提交更改；请先检查，再创建交付包。")
    output = root / "delivery" / "AI-Panel-Studio-stage4.zip"
    output.parent.mkdir(exist_ok=True)
    subprocess.run(["git", "-c", safe, "archive", "--format=zip", f"--output={output}", "HEAD"], cwd=root, check=True)
    with zipfile.ZipFile(output) as archive:
        files = set(archive.namelist())
        required = {"README.md", ".env.example", "requirements.txt", "frontend/package-lock.json",
                    "backend/app/seed.py", "frontend/e2e/discussion.spec.ts", "docs/TEST_REPORT.md"}
        assert required <= files, f"交付包缺少文件：{required - files}"
        forbidden = [name for name in files if name == ".env" or name.endswith((".db", ".sqlite", ".sqlite3"))
                     or any(part in name.split("/") for part in ("node_modules", ".venv", "__pycache__", "dist", "test-results"))]
        assert not forbidden, f"交付包含不应提交的文件：{forbidden}"
        print(f"交付包：{output}；文件数：{len(files)}；大小：{output.stat().st_size} 字节")


if __name__ == "__main__":
    main()
