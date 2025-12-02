#!/usr/bin/env python3
"""
UE traffic monitor

Shows real-time transmitted (TX) and received (RX) packets and bytes per free-ran-ue
UE interface (ueTun0-ueTun99). Reads statistics from /sys/class/net/<iface>/statistics and
prints a table with rates.

Usage:
    ./scripts/ue_tx_rx_monitor.py [-i INTERVAL] [-n COUNT] [--interfaces ueTun0 ueTun1 ...]

Options:
    -i, --interval  Poll interval in seconds (default: 1)
    -n, --count     Number of samples to show (default: 0 -> run until Ctrl-C)
    --interfaces    Space-separated list of interfaces to monitor (default: auto-detect ueTun*)
    -h, --help      Show help

Examples:
    ./scripts/ue_tx_rx_monitor.py
    ./scripts/ue_tx_rx_monitor.py -i 2
    ./scripts/ue_tx_rx_monitor.py --interfaces ueTun0 ueTun1

"""
import argparse
import glob
import os
import re
import sys
import time
from collections import defaultdict


def natural_sort_key(iface):
    """Extract numeric part from interface name for natural sorting"""
    match = re.search(r'(\d+)$', iface)
    if match:
        return int(match.group(1))
    return 0


def detect_ue_interfaces():
    paths = glob.glob('/sys/class/net/ueTun*')
    ifaces = [os.path.basename(p) for p in paths]
    return sorted(ifaces, key=natural_sort_key)


def read_stat(iface, stat):
    path = f'/sys/class/net/{iface}/statistics/{stat}'
    try:
        with open(path, 'r') as f:
            return int(f.read().strip())
    except Exception:
        return None


def format_rate(delta, interval):
    if interval <= 0:
        return '0/s'
    per_s = delta / interval
    return f'{per_s:,.1f}/s'


def format_bytes_rate(delta, interval):
    """Format byte rate with compact units (prefer Mb/s)"""
    if interval <= 0:
        return '0'
    
    bytes_per_sec = delta / interval
    
    # Convert to bits per second (networking standard)
    bits_per_sec = bytes_per_sec * 8
    
    if bits_per_sec >= 1_000_000_000:  # Gb/s
        return f'{bits_per_sec/1_000_000_000:.2f}Gb/s'
    elif bits_per_sec >= 1_000_000:  # Mb/s
        return f'{bits_per_sec/1_000_000:.2f}Mb/s'
    elif bits_per_sec >= 1_000:  # Kb/s
        return f'{bits_per_sec/1_000:.2f}Kb/s'
    else:  # b/s
        return f'{bits_per_sec:.1f}b/s'


def human_bytes(n):
    try:
        n = float(n)
    except Exception:
        return 'N/A'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:3.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


def print_table(rows, timestamp, sample):
    # rows: list of tuples (iface, rx_pkts_total, rps, rbps, rx_bytes_total,
    #                        tx_pkts_total, tps, tbps, tx_bytes_total)
    print('\n' + '=' * 110)
    print(f'Time: {timestamp}   Sample: {sample}')
    print('-' * 110)
    header = f"{'Interface':<12}  {'RX Pkts':>12}  {'RX p/s':>12}  {'RX Rate':>14}  {'TX Pkts':>12}  {'TX p/s':>12}  {'TX Rate':>14}"
    print(header)
    print('-' * 110)
    for r in rows:
        iface = r[0]
        rxp, rps, rbps, rxb = r[1], r[2], r[3], r[4]
        txp, tps, tbps, txb = r[5], r[6], r[7], r[8]
        print(f"{iface:<12}  {rxp:>12}  {rps:>12}  {rbps:>14}  {txp:>12}  {tps:>12}  {tbps:>14}")
    print('=' * 110)


def main():
    parser = argparse.ArgumentParser(description='Monitor UE tx/rx packets/bytes per ueTun interface')
    parser.add_argument('-i', '--interval', type=float, default=1.0, help='poll interval seconds')
    parser.add_argument('-n', '--count', type=int, default=0, help='number of samples to show (0 = infinite)')
    parser.add_argument('--interfaces', nargs='*', help='interfaces to monitor (default: auto-detect ueTun*)')
    args = parser.parse_args()

    if args.interfaces:
        ifaces = args.interfaces
    else:
        ifaces = detect_ue_interfaces()

    if not ifaces:
        print('No ueTun interfaces found. Exit.')
        sys.exit(1)

    # Filter valid existing interfaces
    ifaces = [i for i in ifaces if os.path.exists(f'/sys/class/net/{i}')]
    if not ifaces:
        print('No valid interfaces found after filtering. Exit.')
        sys.exit(1)

    print(f'Monitoring {len(ifaces)} interface(s): {", ".join(ifaces)}')
    print('Press Ctrl-C to stop')

    prev = {}
    for iface in ifaces:
        rxp = read_stat(iface, 'rx_packets') or 0
        rxb = read_stat(iface, 'rx_bytes') or 0
        txp = read_stat(iface, 'tx_packets') or 0
        txb = read_stat(iface, 'tx_bytes') or 0
        prev[iface] = (rxp, rxb, txp, txb)

    sample = 0
    try:
        while True:
            time.sleep(args.interval)
            sample += 1
            rows = []
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            for iface in ifaces:
                # read rx and tx
                rxp = read_stat(iface, 'rx_packets')
                rxb = read_stat(iface, 'rx_bytes')
                txp = read_stat(iface, 'tx_packets')
                txb = read_stat(iface, 'tx_bytes')
                if None in (rxp, rxb, txp, txb):
                    rows.append((iface, 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A'))
                    continue
                rprev_p, rprev_b, tprev_p, tprev_b = prev.get(iface, (rxp, rxb, txp, txb))
                drp = rxp - rprev_p
                drb = rxb - rprev_b
                dtp = txp - tprev_p
                dtb = txb - tprev_b
                rps = format_rate(drp, args.interval)
                rbps = format_bytes_rate(drb, args.interval)
                tps = format_rate(dtp, args.interval)
                tbps = format_bytes_rate(dtb, args.interval)
                rows.append((iface, rxp, rps, rbps, human_bytes(rxb), txp, tps, tbps, human_bytes(txb)))
                prev[iface] = (rxp, rxb, txp, txb)

            print_table(rows, timestamp, sample)

            if args.count and sample >= args.count:
                break

    except KeyboardInterrupt:
        print('\nStopped by user')


if __name__ == '__main__':
    main()
