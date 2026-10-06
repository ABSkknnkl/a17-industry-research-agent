#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 主域名连通性监控 —— 用于定位「模型思考停滞」

背景
----
10-04 18:00~24:00 应用日志出现 107 次聊天流重放（www.workbuddy.cn → wb.tencentbuddy.com）、
2279 条慢 RPC（最慢 375 秒）、98 次健康检查 10 秒超时。
但凌晨复测链路完全正常（0.15s 200），说明故障是「时段性」的。

本脚本用于在真正的故障时段（如 18:00~24:00）持续采样，坐实：
  1. 是「只有主域名挂」还是「全都挂」→ 站点问题 vs 本地网络问题
  2. 故障的起止时间与失败率
  3. 换网络 / 换代理节点前后的对比效果

设计要点
--------
- 只做 TCP + TLS 握手，**不发 HTTP 请求**（避免被限流，也能反映真实握手质量）
- 用公网基准（百度）做对照：三者同时挂 = 本地网络问题；只有主域名挂 = 主域名/CDN 问题
- 绕过 HTTP 代理环境变量，走真实 socket
- 输出：人类可读日志 + CSV（便于事后统计）

用法
----
    python3 scripts/net_quality_watch.py                        # 每 60 秒一轮，Ctrl-C 停
    python3 scripts/net_quality_watch.py --interval 30 --rounds 4
    python3 scripts/net_quality_watch.py --duration 360         # 跑 6 小时自动停
    python3 scripts/net_quality_watch.py --out output/net_watch

建议在「系统自带终端 Terminal.app」里跑（最贴近真实网络环境）。
"""

import argparse
import csv
import datetime
import os
import socket
import ssl
import statistics
import sys
import time

TARGETS = [
    ("www.workbuddy.cn",    "主域名  "),
    ("wb.tencentbuddy.com", "备用域名"),
    ("www.baidu.com",       "公网基准"),
]

TIMEOUT = 6.0          # 单次握手超时（秒）
MAX_IPS_PER_HOST = 4   # 每个域名最多测几个 IP


def resolve(host):
    """解析 A 记录（走系统解析器）。"""
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(host, 443, socket.AF_INET)})
    except Exception:
        return []


def probe_tls(host, ip, timeout=TIMEOUT):
    """
    对单个 IP 做 TCP 连接 + TLS 握手。
    返回 (是否成功, 耗时秒, 错误类型)
    """
    t0 = time.perf_counter()
    sock = None
    try:
        sock = socket.create_connection((ip, 443), timeout=timeout)
    except Exception as e:
        return False, time.perf_counter() - t0, type(e).__name__
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        w = ctx.wrap_socket(sock, server_hostname=host)
        dt = time.perf_counter() - t0
        try:
            w.close()
        except Exception:
            pass
        return True, dt, ""
    except Exception as e:
        try:
            sock.close()
        except Exception:
            pass
        return False, time.perf_counter() - t0, type(e).__name__


def sample_host(host):
    """对一个域名采样一轮，返回汇总 dict。"""
    ips = resolve(host)[:MAX_IPS_PER_HOST]
    if not ips:
        return {"ok": 0, "total": 0, "median": None, "worst": None, "errs": "DNS_FAIL"}
    results, errs = [], []
    for ip in ips:
        ok, dt, err = probe_tls(host, ip)
        results.append((ok, dt))
        if not ok:
            errs.append(err)
    good = [dt for ok, dt in results if ok]
    return {
        "ok": len(good),
        "total": len(results),
        "median": statistics.median(good) if good else None,
        "worst": max(good) if good else None,
        "errs": ",".join(sorted(set(errs))) if errs else "",
    }


def main():
    ap = argparse.ArgumentParser(description="WorkBuddy 主域名连通性监控")
    ap.add_argument("--interval", type=int, default=60, help="采样间隔秒数（默认 60）")
    ap.add_argument("--rounds", type=int, default=4, help="每个域名测几个 IP（默认 4）")
    ap.add_argument("--duration", type=int, default=0, help="总时长分钟数，0=不限（默认 0）")
    ap.add_argument("--out", default="output/net_watch", help="输出文件前缀")
    args = ap.parse_args()

    global MAX_IPS_PER_HOST
    MAX_IPS_PER_HOST = args.rounds

    outdir = os.path.dirname(os.path.abspath(args.out)) or "."
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"{args.out}_{stamp}.log"
    csv_path = f"{args.out}_{stamp}.csv"

    logf = open(log_path, "a", encoding="utf-8", buffering=1)
    csvf = open(csv_path, "a", encoding="utf-8", newline="")
    writer = csv.writer(csvf)
    writer.writerow(["timestamp", "host", "ok", "total", "median_tls_s", "worst_tls_s", "errors"])

    banner = (f"# WorkBuddy 连通性监控启动 {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
              f"# 间隔 {args.interval}s · 每域名测 {MAX_IPS_PER_HOST} 个 IP · 超时 {TIMEOUT}s\n"
              f"# 日志 {log_path}\n# 数据 {csv_path}\n")
    print(banner)
    logf.write(banner)

    started = time.time()
    stop_at = started + args.duration * 60 if args.duration else None
    fail_streak = {h: 0 for h, _ in TARGETS}

    try:
        while True:
            now = datetime.datetime.now()
            line_parts = []
            all_down = True
            for host, label in TARGETS:
                r = sample_host(host)
                writer.writerow([
                    now.strftime("%Y-%m-%d %H:%M:%S"), host, r["ok"], r["total"],
                    f"{r['median']:.3f}" if r["median"] is not None else "",
                    f"{r['worst']:.3f}" if r["worst"] is not None else "",
                    r["errs"],
                ])
                if r["total"] and r["ok"] > 0:
                    all_down = False
                if r["total"] and r["ok"] == 0:
                    fail_streak[host] += 1
                else:
                    fail_streak[host] = 0

                if r["ok"] == r["total"] and r["total"]:
                    stat = f"OK {r['ok']}/{r['total']}  TLS中位 {r['median']:.2f}s 最慢 {r['worst']:.2f}s"
                elif r["ok"] == 0:
                    stat = f"❌ 全失败 0/{r['total']}  ({r['errs']})  连续{fail_streak[host]}轮"
                else:
                    stat = f"⚠ 部分失败 {r['ok']}/{r['total']}  ({r['errs']})"
                line_parts.append(f"{label} {host:22s} {stat}")

            ts = now.strftime("%m-%d %H:%M:%S")
            header = f"[{ts}]"
            if all_down:
                header += "  🔴 三个目标全部失败 → 大概率本地网络/运营商问题"
            print(header)
            logf.write(header + "\n")
            for p in line_parts:
                print("    " + p)
                logf.write("    " + p + "\n")
            sys.stdout.flush()
            csvf.flush()

            if stop_at and time.time() >= stop_at:
                msg = f"\n# 已跑满 {args.duration} 分钟，结束。"
                print(msg); logf.write(msg + "\n")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        msg = "\n# 用户中断。"
        print(msg); logf.write(msg + "\n")
    finally:
        logf.close(); csvf.close()
        print(f"\n日志：{log_path}\n数据：{csv_path}")
        print("把 CSV 发我，我帮你算失败率与故障时段。")


if __name__ == "__main__":
    main()
