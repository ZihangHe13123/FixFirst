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
            "\nFixFirst · Python 项目排查\n1 体验导入与风格排查\n2 开始排查自己的项目\n3 继续已有排查\n4 体验测试执行与知识图谱\n0 退出"
        )
        choice = input("选择：").strip()
        if choice == "0":
            return 0
        if choice in ("1", "4"):
            output = Path("workbench") / ("demo-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            main(
                prefix
                + [
                    "demo",
                    "--output",
                    str(output),
                    "--scenario",
                    "execution" if choice == "4" else "collection",
                    "--open",
                ]
            )
            continue
        if choice == "2":
            project = input("项目目录（输入完整路径）：").strip().strip("'\"")
            python = (
                input(f"项目 Python 路径（回车用 {sys.executable}）：").strip().strip("'\"")
                or sys.executable
            )
            goal_choice = (
                input(
                    "目标：1 测试收集 / 2 代码检查 / 3 测试执行（会运行测试体；回车选 1）："
                ).strip()
                or "1"
            )
            goals = {"1": "collect_tests", "2": "check_style", "3": "pass_tests"}
            if goal_choice not in goals:
                print("无效目标")
                continue
            if (
                main(prefix + ["init", project, "--python", python, "--goal", goals[goal_choice]])
                != 0
            ):
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
                "\n1 按当前目标运行检查\n2 只检查测试收集\n3 只检查代码\n4 打开报告\n5 导入日志\n6 切换目标\n7 声明已修改\n8 导出分享报告\n9 执行完整测试\n10 重跑关联失败测试\n11 查询推荐依据\n0 返回"
            )
            action = input("选择：").strip()
            if action == "0":
                break
            commands = {
                "1": ["scan", session_id],
                "2": ["scan", session_id, "--checks", "pytest"],
                "3": ["scan", session_id, "--checks", "ruff"],
                "4": ["report", session_id, "--open"],
                "9": ["scan", session_id, "--checks", "pytest_run"],
                "10": ["run", session_id, "check-failed-tests"],
            }
            if action in ("1", "2"):
                print("测试收集会执行项目导入；仅检查你信任的项目。")
            if action == "5":
                tool = input("来源 pip_install / pip_check / pytest / pytest_run / ruff：").strip()
                if tool not in ("pip_install", "pip_check", "pytest", "pytest_run", "ruff"):
                    print("不支持的来源")
                    continue
                file = input("日志文件路径：").strip().strip("'\"")
                command = ["import", session_id, "--tool", tool, "--file", file]
            elif action == "6":
                goal = input("1 恢复测试收集 / 2 通过代码检查 / 3 通过测试运行：").strip()
                if goal not in ("1", "2", "3"):
                    continue
                command = [
                    "configure",
                    session_id,
                    "--goal",
                    {"1": "collect_tests", "2": "check_style", "3": "pass_tests"}[goal],
                ]
            elif action == "7":
                main(prefix + ["show", session_id])
                issue = input("输入 issue 开头的问题编号：").strip()
                command = ["mark-fixed", session_id, issue]
            elif action == "8":
                path = input("输出 HTML 路径：").strip().strip("'\"")
                command = ["export", session_id, "--output", path, "--open"]
            elif action == "11":
                question = input("问题（如：为什么推荐这个行动 / 当前目标有哪些问题）：").strip()
                command = ["ask", session_id, question]
            else:
                command = commands.get(action)
            if command:
                main(prefix + command)
