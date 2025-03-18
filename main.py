#!/usr/bin/env python3
"""
Main entry point for the L2 to L3 ARP mapping script.
This script connects to network devices, extracts MAC addresses,
maps them to IP addresses via ARP tables, performs DNS lookups,
and outputs the results to a CSV file.
"""

import argparse
import csv
import logging
import os
import socket
from pathlib import Path

from connector import NetworkConnector

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Network device MAC to IP mapping tool')
    parser.add_argument(
        '--hostnames', 
        type=str, 
        default='hostnames.txt',
        help='File containing hostnames of L2 devices'
    )
    parser.add_argument(
        '--upstream', 
        type=str, 
        default='upstream.txt',
        help='File containing hostnames of upstream L3 devices'
    )
    parser.add_argument(
        '--credentials', 
        type=str, 
        default='credentials.txt',
        help='File containing login credentials'
    )
    parser.add_argument(
        '--templates', 
        type=str, 
        default='templates',
        help='Directory containing TextFSM templates'
    )
    parser.add_argument(
        '--output', 
        type=str, 
        default='output.csv',
        help='Output CSV file'
    )
    return parser.parse_args()

def read_device_list(filename):
    """Read hostnames from file."""
    try:
        with open(filename, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        logger.error(f"File not found: {filename}")
        return []

def read_credentials(filename):
    """Read login credentials from file."""
    try:
        with open(filename, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
            if len(lines) >= 2:
                return {'username': lines[0], 'password': lines[1]}
            else:
                logger.error(f"Invalid credentials file format: {filename}")
                return {}
    except FileNotFoundError:
        logger.error(f"Credentials file not found: {filename}")
        return {}

def perform_dns_lookups(ip_addresses):
    """Perform DNS lookups for the given IP addresses."""
    dns_results = {}
    for ip in ip_addresses:
        try:
            hostname = socket.gethostbyaddr(ip)[0]
            dns_results[ip] = hostname
            logger.info(f"DNS lookup: {ip} -> {hostname}")
        except (socket.herror, socket.gaierror):
            dns_results[ip] = ""
            logger.warning(f"DNS lookup failed for IP: {ip}")
    
    return dns_results

def write_hosts_file(dns_results, filename='hosts.txt'):
    """Write DNS lookup results to hosts.txt file."""
    with open(filename, 'w') as f:
        for ip, hostname in dns_results.items():
            f.write(f"{ip} {hostname}\n")
    logger.info(f"DNS results written to {filename}")

def write_csv_results(results, filename='output.csv'):
    """Write results to CSV file."""
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Hostname', 'IP', 'MAC'])
        for entry in results:
            writer.writerow([
                entry.get('hostname', ''),
                entry.get('ip', ''),
                entry.get('mac', '')
            ])
    logger.info(f"Results written to {filename}")

def parse_hosts_file(filename='hosts.txt'):
    """Parse hosts.txt file."""
    results = []
    try:
        with open(filename, 'r') as f:
            for line in f:
                if line.strip():
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        ip, hostname = parts
                        results.append({'ip': ip, 'hostname': hostname})
                    else:
                        results.append({'ip': parts[0], 'hostname': ''})
    except FileNotFoundError:
        logger.error(f"Hosts file not found: {filename}")
    
    return results

def main():
    """Main execution function."""
    args = parse_arguments()
    
    # Read device lists and credentials
    l2_devices = read_device_list(args.hostnames)
    l3_devices = read_device_list(args.upstream)
    credentials = read_credentials(args.credentials)
    
    if not l2_devices:
        logger.error("No L2 devices found. Exiting.")
        return
    
    if not l3_devices:
        logger.error("No L3 devices found. Exiting.")
        return
    
    if not credentials:
        logger.error("No valid credentials found. Exiting.")
        return
    
    # Initialize network connector
    connector = NetworkConnector(
        username=credentials.get('username'),
        password=credentials.get('password'),
        templates_dir=args.templates
    )
    
    # Step 1: Connect to L2 devices and get MAC addresses
    mac_addresses = connector.collect_mac_addresses(l2_devices)
    logger.info(f"Collected {len(mac_addresses)} MAC addresses from L2 devices")
    
    # Step 2: Connect to L3 devices and get ARP tables
    mac_to_ip = connector.map_mac_to_ip(l3_devices, mac_addresses)
    logger.info(f"Mapped {len(mac_to_ip)} MAC addresses to IP addresses")
    
    # Step 3: Perform DNS lookups
    dns_results = perform_dns_lookups(mac_to_ip.values())
    write_hosts_file(dns_results)
    
    # Step 4: Create final CSV output
    results = []
    for mac, ip in mac_to_ip.items():
        hostname = dns_results.get(ip, '')
        results.append({
            'hostname': hostname,
            'ip': ip,
            'mac': mac
        })
    
    write_csv_results(results, args.output)
    logger.info(f"Process completed. Results saved to {args.output}")

if __name__ == "__main__":
    main() 