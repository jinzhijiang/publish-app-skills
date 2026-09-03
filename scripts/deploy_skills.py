#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_skills.py — 把本仓库的 skill 装成全局可用。

用法:
    python3 scripts/deploy_skills.py --list          # 看仓库里有哪些 skill
    python3 scripts/deploy_skills.py                 # 部署全部
    python3 scripts/deploy_skills.py publish-app-oppo publish-app-vivo
    python3 scripts/deploy_skills.py --check         # 只报告差异,不改文件
    python3 scripts/deploy_skills.py --prune         # 顺带清掉仓库里已删除的 skill 的残留

部署链路:

    skills/<name>/  --rsync -a --delete-->  ~/.cc-switch/skills/<name>/   (真目录)
                                            ~/.claude/skills/<name>       (符号链接)

仓库是唯一真源;~/.cc-switch/skills 下的内容随时会被本脚本覆盖,不要在那里改。
脚本只改这两个部署位置,不碰仓库本身,也不 commit。

仅用 python3 标准库(外部命令只有 rsync)。

退出码: 0 成功 / 1 有 skill 部署失败 / 2 用法或环境错误
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
CC_SWITCH_SKILLS = Path.home() / ".cc-switch" / "skills"
CLAUDE_SKILLS = Path.home() / ".claude" / "skills"


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def repo_skills() -> list[str]:
    if not SKILLS_DIR.is_dir():
        die(f"找不到 {SKILLS_DIR}")
    return sorted(
        d.name for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    )


def deploy(name: str, *, dry_run: bool = False) -> bool:
    """同步到 ~/.cc-switch/skills 并确保 ~/.claude/skills 下有符号链接。"""
    src = SKILLS_DIR / name
    if not (src / "SKILL.md").is_file():
        log(f"  ✗ {name}: 缺 SKILL.md,跳过")
        return False

    target = CC_SWITCH_SKILLS / name
    link = CLAUDE_SKILLS / name

    cmd = ["rsync", "-a", "--delete", "--exclude=__pycache__", "--exclude=.DS_Store"]
    if dry_run:
        cmd += ["-n", "-i"]
    cmd += [f"{src}/", f"{target}/"]

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"  ✗ {name}: rsync 失败\n{result.stderr.strip()}")
        return False

    diff = result.stdout.strip()
    if dry_run:
        log(f"  · {name}: {'有差异' if diff else '已是最新'}")
        if diff:
            for line in diff.splitlines():
                log(f"      {line}")
    else:
        log(f"  ✓ {name} -> {target}")

    # ~/.claude/skills/<name> 必须是指向 cc-switch 那份的符号链接
    want = target.resolve() if target.exists() else target
    have = link.resolve() if link.is_symlink() and link.exists() else None
    if have != want:
        if dry_run:
            log(f"  · {name}: 需要{'重建' if link.exists() or link.is_symlink() else '新建'}符号链接 {link}")
        else:
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.is_symlink() or link.exists():
                if link.is_dir() and not link.is_symlink():
                    shutil.rmtree(link)
                else:
                    link.unlink()
            link.symlink_to(target)
            log(f"    · 符号链接 {link} -> {target}")
    return True


def prune(known: list[str], *, dry_run: bool = False) -> None:
    """清掉本仓库曾经部署、如今已从 skills/ 删除的残留。"""
    for base in (CC_SWITCH_SKILLS, CLAUDE_SKILLS):
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name in known or not entry.name.startswith(("publish-app-", "vasdolly-")):
                continue
            # 只碰指向本仓库部署位置的那一份,别人的同名 skill 不动
            if base is CLAUDE_SKILLS and not (
                entry.is_symlink() and str(entry.resolve()).startswith(str(CC_SWITCH_SKILLS))
            ):
                continue
            log(f"  · 残留待清理: {entry}")
            if not dry_run:
                if entry.is_symlink() or entry.is_file():
                    entry.unlink()
                else:
                    shutil.rmtree(entry)


def main() -> int:
    parser = argparse.ArgumentParser(description="部署本仓库的 skill 到 ~/.cc-switch/skills 与 ~/.claude/skills")
    parser.add_argument("names", nargs="*", help="只部署这些 skill(默认全部)")
    parser.add_argument("--list", action="store_true", help="列出仓库里的 skill 后退出")
    parser.add_argument("--check", action="store_true", help="只报告差异,不改文件")
    parser.add_argument("--prune", action="store_true", help="顺带清理仓库里已删除的 skill 的部署残留")
    args = parser.parse_args()

    if shutil.which("rsync") is None:
        die("找不到 rsync")

    available = repo_skills()
    if args.list:
        for name in available:
            print(f"  {name}")
        print(f"\n共 {len(available)} 个 skill。")
        return 0

    targets = args.names or available
    unknown = [n for n in targets if n not in available]
    if unknown:
        die("仓库里没有这些 skill: " + ", ".join(unknown))

    log(f"{'检查' if args.check else '部署'} {len(targets)} 个 skill:")
    failed = [n for n in targets if not deploy(n, dry_run=args.check)]

    if args.prune:
        log("清理残留:")
        prune(available, dry_run=args.check)

    if failed:
        log(f"\n失败 {len(failed)} 个: {', '.join(failed)}")
        return 1
    log(f"\n完成。skill 可在任意项目里直接调用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
