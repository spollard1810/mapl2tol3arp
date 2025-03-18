# MAC to IP Address Mapping Tool

This tool connects to network devices, extracts MAC addresses from L2 devices, maps them to IP addresses using ARP tables from L3 devices, performs DNS lookups, and creates a comprehensive CSV output.

## Requirements

- Python 3.6+
- Required Python packages:
  - netmiko
  - textfsm

## Installation

```bash
pip install netmiko textfsm
```

## Configuration Files

1. **hostnames.txt**: List of L2 devices to extract MAC addresses from.
2. **upstream.txt**: List of L3 devices to extract ARP tables from.
3. **credentials.txt**: Login credentials (username on first line, password on second line).
4. **templates/**: Directory containing TextFSM templates for parsing command outputs.

## Usage

```bash
python main.py [options]
```

### Options

- `--hostnames FILE`: File with hostnames of L2 devices (default: hostnames.txt)
- `--upstream FILE`: File with hostnames of L3 devices (default: upstream.txt)
- `--credentials FILE`: File with login credentials (default: credentials.txt)
- `--templates DIR`: Directory with TextFSM templates (default: templates)
- `--output FILE`: Output CSV file (default: output.csv)

## Output Files

The script produces the following output files:

1. **mac_addresses.txt**: List of MAC addresses extracted from L2 devices.
2. **hosts.txt**: DNS lookup results for IP addresses.
3. **output.csv**: Final CSV output with Hostname, IP, and MAC address columns.

## Flow of the Script

1. Login to L2 devices in `hostnames.txt`
2. Extract MAC address tables and save to `mac_addresses.txt`
3. Login to L3 devices in `upstream.txt`
4. Extract ARP tables and match MAC addresses
5. Perform DNS lookups on matched IP addresses
6. Generate the final CSV output

## Example

```bash
python main.py --hostnames switches.txt --upstream routers.txt --output network_inventory.csv
```

## TextFSM Templates

The script uses TextFSM templates to parse the command outputs:

- `cisco_ios_show_mac_address_table.textfsm`: For parsing "show mac address-table" output
- `cisco_ios_show_ip_arp.textfsm`: For parsing "show ip arp" output

You can customize these templates based on your device output format. 