"""Small terminal menu over the same public CLI; no separate execution path."""

from datetime import datetime
from pathlib import Path
import sys

from .storage import Store


def menu(store_root):
    from .cli import main

    store = Store(store_root)
    prefix = ["--store", str(store.root)]
    while True:
        print(
            "\nFixFirst · Python 项目排查\n1 体验完整演示\n2 开始排查自己的项目\n3 继续已有排查\n0 退出"
        )
        choice = input("选择：").strip()
        if choice == "0":
            return 0
        if choice == "1":
            output = Path("workbench") / ("demo-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            main(prefix + ["demo", "--output", str(output), "--open"])
            continue
        if choice == "2":
            project = input("项目目录（输入完整路径）：").strip().strip("'\"")
            python = (
                input(f"项目 Python 路径（回车用 {sys.executable}）：").strip().strip("'\"")
                or sys.executable
            )
            if main(prefix + ["init", project, "--python", python]) != 0:
                continue
        if choice not in ("2", "3"):
            continue
        rows = store.list()
        if not rows:
            print("还没有排查记录")
            continue
        for i, row in enumerate(rows, 1):
            print(f"{i} {row['name']} · {row['goal_status']} · {row['session_id']}")
        try:
            index = int(input("选择排查编号：")) - 1
            if index < 0:
                continue
            session_id = rows[index]["session_id"]
        except (ValueError, IndexError):
            print("无效选择")
            continue
        while True:
            print(
                "\n1 运行全部检查\n2 只检查测试收集\n3 只检查代码\n4 打开报告\n5 导入日志\n6 切换目标\n7 声明已修改\n8 导出分享报告\n0 返回"
            )
            action = input("选择：").strip()
            if action == "0":
                break
            commands = {
                "1": ["scan", session_id],
                "2": ["scan", session_id, "--checks", "pytest"],
                "3": ["scan", session_id, "--checks", "ruff"],
                "4": ["report", session_id, "--open"],
            }
            if action in ("1", "2"):
                print("测试收集会执行项目导入；仅检查你信任的项目。")
            if action == "5":
                tool = input("来源 pip_install / pip_check / pytest / ruff：").strip()
                if tool not in ("pip_install", "pip_check", "pytest", "ruff"):
                    print("不支持的来源")
                    continue
                file = input("日志文件路径：").strip().strip("'\"")
                command = ["import", session_id, "--tool", tool, "--file", file]
            elif action == "6":
                goal = input("1 恢复测试收集 / 2 通过代码检查：").strip()
                if goal not in ("1", "2"):
                    continue
                command = [
                    "configure",
                    session_id,
                    "--goal",
                    "collect_tests" if goal == "1" else "check_style",
                ]
            elif action == "7":
                main(prefix + ["show", session_id])
                issue = input("输入 issue 开头的问题编号：").strip()
                command = ["mark-fixed", session_id, issue]
            elif action == "8":
                path = input("输出 HTML 路径：").strip().strip("'\"")
                command = ["export", session_id, "--output", path, "--open"]
            else:
                command = commands.get(action)
            if command:
                main(prefix + command)
