r"""
一键数据更新 + 模型重训脚本
========================
正式部署后由 Windows 任务计划程序每天定时调用（也可手动运行）：
  1. 采集 eBay（已售出优先，被拦截自动降级为在售）+ CardHobby 最新数据
  2. 自动重训 XGBoost 定价模型
  3. 输出日志到 logs/ 目录（含每次更新的数据量、MAPE 等）

用法:
    python scripts/update_all.py                      # 完整更新（默认）
    python scripts/update_all.py --players 15         # 指定球星数量
    python scripts/update_all.py --cardhobby-pages 30
    python scripts/update_all.py --skip-ebay          # 仅更新 CardHobby
    python scripts/update_all.py --skip-retrain       # 只更新数据不重训

定时任务注册（PowerShell 管理员，Windows 任务计划要求绝对路径）:
    schtasks /Create /TN "StarCard_Update" /TR "C:\绝对路径\scripts\update_all.bat" /SC DAILY /ST 03:00
"""

import sys
import os
import io
import time
import argparse
import subprocess
from datetime import datetime
from typing import List

# 强制UTF-8编码，避免Windows GBK兼容问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")


def log(msg: str, log_file):
    """同时输出到控制台和日志文件"""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    log_file.write(line + "\n")
    log_file.flush()


def run(cmd: List[str], log_file, label: str) -> int:
    """运行子进程命令并记录日志"""
    log(f"▶ {label}: {os.path.relpath(cmd[0], PROJECT_ROOT)} {' '.join(cmd[1:])}", log_file)
    t0 = time.time()
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    # 记录输出尾部（保留最近若干行，避免日志过大）
    for line in (result.stdout or "").strip().splitlines()[-25:]:
        log(f"    {line}", log_file)
    if result.returncode != 0:
        log(f"  ✗ {label} 失败 (rc={result.returncode}, {elapsed:.0f}s)", log_file)
        for line in (result.stderr or "").strip().splitlines()[-10:]:
            log(f"    [ERR] {line}", log_file)
    else:
        log(f"  ✓ {label} 完成 ({elapsed:.0f}s)", log_file)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="一键数据更新 + 模型重训")
    parser.add_argument("--players", type=int, default=15, help="参与采集的球星数量")
    parser.add_argument("--ebay-pages", type=int, default=2, help="eBay 每关键词翻页数")
    parser.add_argument("--cardhobby-pages", type=int, default=30, help="CardHobby 列表页数")
    parser.add_argument("--search-delay", type=float, default=5.0, help="eBay 搜索间隔秒数")
    parser.add_argument("--skip-ebay", action="store_true", help="跳过 eBay 采集")
    parser.add_argument("--ebay-only", action="store_true",
                        help="仅更新 eBay（手动自选更新用；耗时较长，预计 30-60 分钟）")
    parser.add_argument("--skip-retrain", action="store_true", help="跳过模型重训")
    parser.add_argument("--log-days", type=int, default=30,
                        help="日志保留天数（超过自动清理），默认 30")
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    log_file = open(log_path, "w", encoding="utf-8")

    python = os.path.join(PROJECT_ROOT, "venv", "Scripts", "python.exe")
    if not os.path.exists(python):
        python = "python"  # 回退到系统 python

    log("=" * 60, log_file)
    log("  球星卡系统 — 自动更新开始", log_file)
    log(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", log_file)
    log(f"  参数: players={args.players} ebay_pages={args.ebay_pages} "
        f"cardhobby_pages={args.cardhobby_pages}", log_file)
    log("=" * 60, log_file)

    # ---- 耗时提示：含 eBay 采集时明显提醒 ----
    if not args.skip_ebay:
        est = args.players * 7 * args.ebay_pages * (args.search_delay + 3) / 60
        msg = (f"⚠️  本次更新包含 eBay 采集（{args.players} 名球星 × 7 系列 × "
               f"{args.ebay_pages} 页），预计耗时 {max(est, 10):.0f}-{max(est * 2, 30):.0f} 分钟。\n"
               f"    请保持电脑联网、勿关闭窗口；期间可正常使用其他软件。")
        print("\n" + "=" * 60)
        print(msg)
        print("=" * 60 + "\n")
        log(msg.replace("\n", " | "), log_file)

    t_start = time.time()

    # ---- 第1步：采集数据 ----
    build_args = ["scripts/build_comps_db.py",
                  "--players", str(args.players),
                  "--ebay-pages", str(args.ebay_pages),
                  "--cardhobby-pages", str(args.cardhobby_pages),
                  "--search-delay", str(args.search_delay)]
    if args.skip_ebay:
        build_args.append("--skip-ebay")
    elif args.ebay_only:
        build_args.append("--skip-cardhobby")
        log("本次为 eBay 专属更新 (--ebay-only)，跳过 CardHobby 采集", log_file)

    rc_build = run([python] + build_args, log_file, "数据采集")
    if rc_build != 0:
        log("数据采集失败，中止更新（请查看上方日志）", log_file)
        log_file.close()
        return 1

    # ---- 第2步：重训模型 ----
    if not args.skip_retrain:
        rc_train = run([python, "train.py"], log_file, "模型重训")
        if rc_train != 0:
            log("模型重训失败，但数据已更新（旧模型仍可用）", log_file)
    else:
        log("跳过模型重训 (--skip-retrain)", log_file)

    # ---- 清理过期日志 ----
    try:
        cutoff = time.time() - args.log_days * 86400
        for f in os.listdir(LOG_DIR):
            fp = os.path.join(LOG_DIR, f)
            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                os.remove(fp)
                log(f"清理过期日志: {f}", log_file)
    except Exception as e:
        log(f"日志清理失败: {e}", log_file)

    elapsed = time.time() - t_start
    log("=" * 60, log_file)
    log(f"  更新完成！总耗时 {elapsed/60:.1f} 分钟", log_file)
    log(f"  日志: {log_path}", log_file)
    log("=" * 60, log_file)
    log_file.close()

    # 读取 CSV 数量概要并输出
    try:
        import pandas as pd
        for f, label in [("data/ebay_comps_database.csv", "eBay"),
                         ("data/cardhobby_comps_database.csv", "CardHobby")]:
            p = os.path.join(PROJECT_ROOT, f)
            if os.path.exists(p):
                df = pd.read_csv(p)
                print(f"[概览] {label}: {len(df)} 条 | 价格范围 ${df['price'].min():.0f}~${df['price'].max():.0f} "
                      f"| 中位数 ${df['price'].median():.0f}")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
