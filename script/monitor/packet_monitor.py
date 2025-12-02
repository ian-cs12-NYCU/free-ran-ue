#!/usr/bin/env python3
"""
UE packet destination monitor

Captures and displays packets sent from a specific UE (by source IP),
showing destination addresses. Can display either simplified (src->dst) 
or detailed 5-tuple format.

Usage:
    ./scripts/ue_packet_monitor.py [OPTIONS]

Options:
    --src-ip IP         Source IP address to filter (required if not using --select)
    --select            Interactively select from active UEs
    --5-tuple           Show detailed 5-tuple information (src_ip:port -> dst_ip:port, protocol)
    --simple            Show simplified format (src_ip -> dst_ip) [default]
    --interface IFACE   Capture interface (default: auto-detect from UE)
    --count N           Stop after N packets (default: run until Ctrl-C)
    --debug             Show debug information
    -h, --help          Show help

Examples:
    # Select from active UEs, simple format
    ./scripts/ue_packet_monitor.py --select
    
    # Specify IP directly with 5-tuple
    ./scripts/ue_packet_monitor.py --src-ip 10.61.0.1 --5-tuple
    
    # Simple format with specific IP
    ./scripts/ue_packet_monitor.py --src-ip 10.61.0.1 --simple

Note: Requires tshark to be installed. Run with sudo if permission errors occur.
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import time


def natural_sort_key(iface):
    """Extract numeric part from interface name for natural sorting"""
    match = re.search(r'(\d+)$', iface)
    if match:
        return int(match.group(1))
    return 0


def detect_ue_interfaces():
    """Detect ueTun* interfaces"""
    paths = glob.glob('/sys/class/net/ueTun*')
    ifaces = [os.path.basename(p) for p in paths]
    return sorted(ifaces, key=natural_sort_key)


def get_interface_ip(iface):
    """Get IP address assigned to interface"""
    try:
        result = subprocess.run(
            ['ip', '-4', 'addr', 'show', iface],
            capture_output=True,
            text=True,
            timeout=2
        )
        match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', result.stdout)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def list_active_ues():
    """List active UE interfaces and their IPs"""
    ifaces = detect_ue_interfaces()
    ue_list = []
    
    for iface in ifaces:
        ip = get_interface_ip(iface)
        if ip:
            ue_list.append((iface, ip))
    
    return ue_list


def select_ue_interactive():
    """Interactive UE selection"""
    ue_list = list_active_ues()
    
    if not ue_list:
        print("No active UE interfaces with IP addresses found.")
        print("Make sure free-ran-ue UEs are running with assigned IPs.")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("Active UE Interfaces:")
    print("-" * 60)
    for idx, (iface, ip) in enumerate(ue_list, 1):
        print(f"  {idx}. {iface:<20} IP: {ip}")
    print("=" * 60)
    
    while True:
        try:
            choice = input("\nSelect UE number (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                sys.exit(0)
            
            idx = int(choice)
            if 1 <= idx <= len(ue_list):
                return ue_list[idx - 1]  # Return tuple (interface, IP)
            else:
                print(f"Please enter a number between 1 and {len(ue_list)}")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled by user")
            sys.exit(0)


def check_tshark():
    """Check if tshark is available"""
    try:
        subprocess.run(['tshark', '--version'], 
                      capture_output=True, 
                      timeout=2)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def probe_capture_permissions(interface):
    """Probe whether tshark can open the requested interface (detect permission errors).

    This runs a short, timed tshark invocation that will exit quickly. We inspect
    stderr for permission-related messages and return (ok, message).
    """
    try:
        # Use duration:1 to avoid long waits if no traffic; permission errors appear immediately
        cmd = [
            'tshark', '-i', interface,
            '-a', 'duration:1',
            '-c', '1',
            '-n',
            '-T', 'fields',
            '-e', 'ip.src'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
        stderr = (result.stderr or '').lower()
        if 'permission' in stderr or "you don't have permission" in stderr:
            return (False, result.stderr.strip())
        # If tshark returned non-zero and produced other errors, surface them
        if result.returncode != 0 and stderr:
            return (False, result.stderr.strip())
        return (True, '')
    except FileNotFoundError:
        return (False, 'tshark not found')
    except subprocess.TimeoutExpired:
        # Timeout usually means tshark started but found no packets in the duration window
        return (True, '')
    except Exception as e:
        return (False, str(e))


def format_simple_line(src_ip, dst_ip, protocol, count):
    """Format simple output line"""
    return f"{count:>6}  {src_ip:<15} ---> {dst_ip:<15}  [{protocol}]"


def format_5tuple_line(src_ip, src_port, dst_ip, dst_port, protocol, count):
    """Format 5-tuple output line"""
    src_part = f"{src_ip}:{src_port}" if src_port else src_ip
    dst_part = f"{dst_ip}:{dst_port}" if dst_port else dst_ip
    return f"{count:>6}  {src_part:<22} ---> {dst_part:<22}  [{protocol}]"


def map_protocol(proto_num):
    """Map protocol number to name"""
    protocol_map = {
        '1': 'ICMP',
        '6': 'TCP',
        '17': 'UDP',
        '58': 'ICMPv6',
    }
    return protocol_map.get(proto_num, proto_num if proto_num else 'IP')


def run_simple_monitor(src_ip, interface, count_limit, debug=False):
    """Run monitor in simple mode (src_ip -> dst_ip)"""
    print("\n" + "=" * 80)
    print(f"Monitoring packets from: {src_ip}")
    print(f"Display mode: Simple (IP -> IP)")
    print(f"Interface: {interface}")
    print("Press Ctrl-C to stop")
    print("=" * 80)
    print(f"{'#':>6}  {'Source IP':<15}      {'Destination IP':<15}  {'Protocol'}")
    print("-" * 80)
    sys.stdout.flush()
    
    # Use display filter (works well with RAW interfaces)
    display_filter = f'ip.src == {src_ip}'
    
    tshark_cmd = [
        'tshark',
        '-i', interface,
        '-Y', display_filter,
        '-n',
        '-T', 'fields',
        '-e', 'ip.src',
        '-e', 'ipv6.src',
        '-e', 'ip.dst',
        '-e', 'ipv6.dst',
        '-e', 'ip.proto',
        '-e', 'ipv6.nxt',
        '-E', 'separator=|',
        '-E', 'occurrence=f'
    ]
    
    if count_limit:
        tshark_cmd.extend(['-c', str(count_limit)])
    
    if debug:
        print(f"Debug: Display filter = {display_filter}")
        print(f"Debug: Command = {' '.join(tshark_cmd)}")
        sys.stdout.flush()
    
    try:
        process = subprocess.Popen(
            ['stdbuf', '-oL'] + tshark_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )
        
        packet_count = 0
        
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split('|')
            if len(parts) < 4:
                continue
            
            src = parts[0] if parts[0] else parts[1]
            dst = parts[2] if parts[2] else parts[3]
            proto_num = parts[4] if len(parts) > 4 and parts[4] else (parts[5] if len(parts) > 5 else '')
            protocol = map_protocol(proto_num)
            
            if src and dst:
                packet_count += 1
                print(format_simple_line(src, dst, protocol, packet_count))
                sys.stdout.flush()
        
        process.wait()
        
        if packet_count == 0:
            print("\n" + "=" * 80)
            print("⚠ No packets were captured")
            print("=" * 80)
        
    except KeyboardInterrupt:
        print("\n" + "=" * 80)
        print(f"Stopped by user. Total packets captured: {packet_count}")
        print("=" * 80)
        try:
            process.terminate()
            process.wait(timeout=2)
        except:
            try:
                process.kill()
            except:
                pass


def run_5tuple_monitor(src_ip, interface, count_limit, debug=False):
    """Run monitor in 5-tuple mode"""
    print("\n" + "=" * 100)
    print(f"Monitoring packets from: {src_ip}")
    print(f"Display mode: 5-tuple (IP:Port -> IP:Port, Protocol)")
    print(f"Interface: {interface}")
    print("Press Ctrl-C to stop")
    print("=" * 100)
    print(f"{'#':>6}  {'Source':<22}      {'Destination':<22}  {'Protocol'}")
    print("-" * 100)
    sys.stdout.flush()
    
    # Use display filter
    display_filter = f'ip.src == {src_ip}'
    
    tshark_cmd = [
        'tshark',
        '-i', interface,
        '-Y', display_filter,
        '-n',
        '-T', 'fields',
        '-e', 'ip.src',
        '-e', 'ipv6.src',
        '-e', 'tcp.srcport',
        '-e', 'udp.srcport',
        '-e', 'ip.dst',
        '-e', 'ipv6.dst',
        '-e', 'tcp.dstport',
        '-e', 'udp.dstport',
        '-e', 'ip.proto',
        '-e', 'ipv6.nxt',
        '-E', 'separator=|',
        '-E', 'occurrence=f'
    ]
    
    if count_limit:
        tshark_cmd.extend(['-c', str(count_limit)])
    
    if debug:
        print(f"Debug: Display filter = {display_filter}")
        print(f"Debug: Command = {' '.join(tshark_cmd)}")
        sys.stdout.flush()
    
    try:
        process = subprocess.Popen(
            ['stdbuf', '-oL'] + tshark_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )
        
        packet_count = 0
        
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split('|')
            if len(parts) < 8:
                continue
            
            src = parts[0] if parts[0] else parts[1]
            src_port = parts[2] if parts[2] else parts[3]
            dst = parts[4] if parts[4] else parts[5]
            dst_port = parts[6] if parts[6] else parts[7]
            proto_num = parts[8] if len(parts) > 8 and parts[8] else (parts[9] if len(parts) > 9 else '')
            protocol = map_protocol(proto_num)
            
            if src and dst:
                packet_count += 1
                print(format_5tuple_line(src, src_port, dst, dst_port, protocol, packet_count))
                sys.stdout.flush()
        
        process.wait()
        
        if packet_count == 0:
            print("\n" + "=" * 100)
            print("⚠ No packets were captured")
            print("=" * 100)
        
    except KeyboardInterrupt:
        print("\n" + "=" * 100)
        print(f"Stopped by user. Total packets captured: {packet_count}")
        print("=" * 100)
        try:
            process.terminate()
            process.wait(timeout=2)
        except:
            try:
                process.kill()
            except:
                pass


def main():
    parser = argparse.ArgumentParser(
        description='Monitor packet destinations from a specific UE by source IP',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive UE selection with simple format
  sudo ./scripts/ue_packet_monitor.py --select

  # Specify IP with 5-tuple details
  sudo ./scripts/ue_packet_monitor.py --src-ip 10.61.0.1 --5-tuple

  # Simple format capturing 100 packets
  sudo ./scripts/ue_packet_monitor.py --src-ip 10.61.0.1 --count 100
        """
    )
    
    parser.add_argument('--src-ip', type=str, help='Source IP address to monitor')
    parser.add_argument('--select', action='store_true', help='Select UE interactively')
    parser.add_argument('--5-tuple', dest='five_tuple', action='store_true', 
                       help='Show 5-tuple format (IP:Port)')
    parser.add_argument('--simple', action='store_true', 
                       help='Show simple format (IP only) [default]')
    parser.add_argument('--interface', type=str, default='', 
                       help='Capture interface (default: auto-detect from UE)')
    parser.add_argument('--count', type=int, help='Stop after N packets')
    parser.add_argument('--debug', action='store_true', help='Show debug information')
    
    args = parser.parse_args()
    
    # Check tshark availability
    if not check_tshark():
        print("Error: tshark is not installed or not in PATH")
        print("Install with: sudo apt-get install tshark")
        sys.exit(1)
    
    # Determine source IP and interface
    src_ip = None
    interface = args.interface
    
    if args.select:
        iface, src_ip = select_ue_interactive()
        print(f"\nSelected UE: {iface}")
        print(f"Selected UE IP: {src_ip}")
        if not interface:
            interface = iface
    elif args.src_ip:
        src_ip = args.src_ip
        if not interface:
            # Try to auto-detect which ueTun* interface has this IP and use it.
            ue_list = list_active_ues()
            matched_iface = None
            for iface, ip in ue_list:
                if ip == src_ip:
                    matched_iface = iface
                    break
            if matched_iface:
                interface = matched_iface
                if args.debug:
                    print(f"Auto-detected interface '{interface}' for src-ip {src_ip}")
            else:
                # Fall back to 'any' if we couldn't find the interface locally
                interface = 'any'
                print(f"Warning: no local ueTun* interface has IP {src_ip}; using capture interface 'any'.")
                print("If this IP belongs to a UE, run with --select to pick the correct interface or pass --interface <iface>.")
    else:
        parser.print_help()
        print("\nError: Either --src-ip or --select must be specified")
        sys.exit(1)
    
    # Determine display mode
    use_5tuple = args.five_tuple
    
    # Run monitoring
    try:
        # If not running as root, warn user (many systems require root to capture).
        if os.geteuid() != 0:
            print("Warning: script is not running as root — packet capture may fail. Try running with sudo.")

        # Probe capture permissions for the chosen interface and fail early with a helpful message
        ok, msg = probe_capture_permissions(interface)
        if not ok:
            print("\nError: Unable to open capture interface.")
            if msg:
                print(f"tshark error: {msg}")
            print("Try running with sudo or specify a different --interface that exists on this host.")
            sys.exit(1)

        if use_5tuple:
            run_5tuple_monitor(src_ip, interface, args.count, args.debug)
        else:
            run_simple_monitor(src_ip, interface, args.count, args.debug)
    except PermissionError:
        print("\nError: Permission denied. Try running with sudo:")
        print(f"  sudo {' '.join(sys.argv)}")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
