#!/usr/bin/env python3
"""
Connector module for handling network device connections via Netmiko.
Includes functions for executing commands, parsing output with TextFSM,
and collecting MAC and ARP information.
"""

import logging
import os
import time
from netmiko import ConnectHandler
from netmiko.exceptions import NetMikoTimeoutException, NetMikoAuthenticationException
import textfsm
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

class NetworkConnector:
    """Class to handle network device connections and command execution."""
    
    def __init__(self, username, password, templates_dir='templates', device_type='cisco_nxos', vxlan=False):
        """Initialize the connector with login credentials."""
        self.username = username
        self.password = password
        self.device_type = device_type
        self.templates_dir = templates_dir
        self.vxlan = vxlan
        self.mac_addresses = {}  # Changed from set to dict to store {mac: {'port': port, 'device': device}}
        self.connections = {}
        
    def connect(self, hostname):
        """Establish connection to a device."""
        try:
            logger.info(f"Connecting to device: {hostname}")
            
            device = {
                'device_type': self.device_type,
                'host': hostname,
                'username': self.username,
                'password': self.password,
                'timeout': 20,
                'global_delay_factor': 2,  # Slow down command execution for more reliable output
                'session_log': f"session_{hostname}.log",  # Optional - log the session for debugging
                # More flexible prompt pattern to handle various hostname formats
                'fast_cli': False,  # Disable fast_cli mode for more reliable operation
                'auto_connect': False  # Disable auto-connect for more control
            }
            
            connection = ConnectHandler(**device)
            
            # Manually connect and handle terminal settings
            connection.establish_connection()
            connection.session_preparation()
            
            # Manually send terminal length 0 command and verify output
            connection.send_command("terminal length 0", expect_string=r"#")
            
            self.connections[hostname] = connection
            logger.info(f"Successfully connected to {hostname}")
            return connection
            
        except NetMikoTimeoutException:
            logger.error(f"Connection timeout to device: {hostname}")
        except NetMikoAuthenticationException:
            logger.error(f"Authentication failed for device: {hostname}")
        except Exception as e:
            logger.error(f"Error connecting to {hostname}: {str(e)}")
            
        return None
    
    def disconnect_all(self):
        """Disconnect from all devices."""
        for hostname, connection in self.connections.items():
            try:
                connection.disconnect()
                logger.info(f"Disconnected from {hostname}")
            except Exception as e:
                logger.error(f"Error disconnecting from {hostname}: {str(e)}")
        
        self.connections = {}
    
    def execute_command(self, connection, command):
        """Execute a command on a connected device."""
        try:
            logger.info(f"Executing command: {command}")
            # Add parameters to handle pagination and longer outputs
            output = connection.send_command(
                command,
                expect_string=r"#",  # Wait for prompt
                strip_prompt=True,    # Remove prompt from output
                strip_command=True,   # Remove command from output
                delay_factor=2,       # Increase delay factor for more reliable output
                max_loops=2000        # Increase max loops for longer outputs
            )
            return output
        except Exception as e:
            logger.error(f"Error executing command: {str(e)}")
            return ""
    
    def parse_with_textfsm(self, text_data, template_name):
        """Parse command output using TextFSM template."""
        template_path = os.path.join(self.templates_dir, template_name)
        
        try:
            # Save the raw output for debugging
            debug_filename = f"raw_output_{template_name.replace('.textfsm', '')}_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            with open(debug_filename, 'w') as f:
                f.write(text_data)
            logger.info(f"Saved raw output to {debug_filename}")
            
            with open(template_path, 'r') as template_file:
                template = textfsm.TextFSM(template_file)
                
                # Log template value names for debugging
                logger.info(f"Template values: {[val.name for val in template.values]}")
                
                result = template.ParseText(text_data)
                
                # Log the first few parsed results for debugging
                if result:
                    sample = result[:min(5, len(result))]
                    logger.info(f"Sample of parsed data (first {len(sample)} entries): {sample}")
                
                logger.info(f"Successfully parsed {len(result)} entries with template: {template_name}")
                return result
        except FileNotFoundError:
            logger.error(f"Template file not found: {template_path}")
        except Exception as e:
            logger.error(f"Error parsing with TextFSM: {str(e)}")
            logger.error(f"Template path: {template_path}")
            
        return []
    
    def get_mac_address_table(self, connection):
        """Try different variants of the show mac address-table command based on device type and VXLAN mode."""
        if self.vxlan:
            # VXLAN-specific commands for EVPN
            mac_commands = [
                "show mac address-table vlan all",
                "show mac address-table vlan 1",
                "show mac address-table",
                "show mac address"
            ]
        else:
            # Standard commands for non-VXLAN
            mac_commands = [
                "show mac address-table",
                "show mac-address-table",
                "show mac addr",
                "show mac address-table dynamic",
                "show mac address-table vlan 1",
                "show mac address",
                "show mac"
            ]
        
        for command in mac_commands:
            try:
                logger.info(f"Trying command: {command}")
                output = self.execute_command(connection, command)
                
                # Dump the output to a file for debugging
                with open(f"mac_output_{time.strftime('%Y%m%d_%H%M%S')}.txt", "w") as f:
                    f.write(output)
                
                # Check if the output looks like a MAC address table
                if (len(output) > 100 and 
                    ("mac" in output.lower() or "address" in output.lower() or "vlan" in output.lower())):
                    logger.info(f"Successfully executed command: {command}")
                    return output
            except Exception as e:
                logger.warning(f"Error with command {command}: {str(e)}")
                continue
        
        logger.error("Could not retrieve MAC address table with any command variant")
        return ""
    
    def get_evpn_mac_ip_bindings(self, connection):
        """Get MAC-to-IP bindings from EVPN for VXLAN environments."""
        evpn_commands = [
            "show bgp l2vpn evpn",
            "show bgp l2vpn evpn | grep -i mac",
            "show bgp l2vpn evpn mac",
            "show bgp l2vpn evpn mac-ip"
        ]
        
        for command in evpn_commands:
            try:
                logger.info(f"Trying EVPN command: {command}")
                output = self.execute_command(connection, command)
                
                # Dump the output to a file for debugging
                with open(f"evpn_output_{time.strftime('%Y%m%d_%H%M%S')}.txt", "w") as f:
                    f.write(output)
                
                if len(output) > 100 and any(term in output.lower() 
                                           for term in ["mac", "evpn", "bgp"]):
                    logger.info(f"Successfully executed EVPN command: {command}")
                    return output
            except Exception as e:
                logger.warning(f"Error with EVPN command {command}: {str(e)}")
                continue
        
        logger.error("Could not retrieve EVPN MAC-IP bindings")
        return ""

    def parse_evpn_output(self, output):
        """Parse EVPN output to extract MAC-to-IP bindings."""
        bindings = {}
        
        # Basic parsing of EVPN output
        for line in output.splitlines():
            # Look for lines containing MAC and IP information
            if "mac-ip" in line.lower() or "mac" in line.lower():
                parts = line.split()
                for i, part in enumerate(parts):
                    # Look for MAC address format
                    if ':' in part or '.' in part:
                        mac = part.lower()
                        # Look for IP address in nearby fields
                        for j in range(max(0, i-3), min(len(parts), i+4)):
                            if self.is_valid_ip(parts[j]):
                                ip = parts[j]
                                bindings[mac] = ip
                                logger.debug(f"Found EVPN binding: MAC {mac} -> IP {ip}")
                                break
        
        return bindings

    def is_valid_ip(self, ip_str):
        """Check if a string is a valid IP address."""
        try:
            parts = ip_str.split('.')
            return len(parts) == 4 and all(0 <= int(part) <= 255 for part in parts)
        except (AttributeError, TypeError, ValueError):
            return False

    def collect_mac_addresses(self, hostnames):
        """Connect to L2 devices and collect MAC address table information."""
        mac_addresses = {}  # Changed from set to dict to store port and device info
        
        for hostname in hostnames:
            connection = self.connect(hostname)
            if not connection:
                continue
                
            # Use the helper method to get MAC address table
            output = self.get_mac_address_table(connection)
            
            if not output:
                logger.error(f"Failed to get MAC address table from {hostname}")
                continue
                
            # Parse the output using TextFSM
            parsed_data = self.parse_with_textfsm(output, "cisco_ios_show_mac_address_table.textfsm")
            
            logger.info(f"Parsed {len(parsed_data)} MAC address entries from {hostname}")
            
            # Extract MAC addresses and port information
            for entry in parsed_data:
                try:
                    # Handle both old and new template formats
                    mac = None
                    port = None
                    vlan = None
                    
                    # First, attempt to identify fields based on the template structure
                    if len(entry) >= 7:  # For new template: VLAN_ID, MAC_ADDRESS, TYPE, AGE, SECURE, NTFY, PORTS
                        vlan = entry[0]  # VLAN_ID
                        mac = entry[1]   # MAC_ADDRESS
                        port = entry[6]  # PORTS
                    
                    # If MAC address wasn't found, try to detect it
                    if not mac:
                        for i, field in enumerate(entry):
                            # MAC addresses typically contain : or . as separators
                            if field and (':' in field or '.' in field or 
                                         (len(field) in [12, 14, 17] and all(c in '0123456789abcdefABCDEF.:' for c in field))):
                                mac = field
                                logger.debug(f"Found MAC address at index {i}: {mac}")
                                
                                # Try to find port info in other fields
                                for j, port_field in enumerate(entry):
                                    if j != i and port_field and port_field.lower() not in ['dynamic', 'static', 'learned']:
                                        # Check if field looks like a port (contains common port prefixes)
                                        if any(prefix in port_field.lower() for prefix in ['gi', 'fa', 'eth', 'po', 'vlan', 'te', 'port']):
                                            port = port_field
                                            break
                                break
                    
                    if mac:
                        # Clean and normalize MAC address
                        mac = mac.lower()  # Convert to lowercase
                        
                        # Only store/update if we don't have this MAC yet or if we have a valid port
                        # This ensures we keep the first (L2) port we find and don't overwrite with L3 interface
                        if mac not in mac_addresses or (port and port != 'unknown'):
                            mac_addresses[mac] = {
                                'port': port or 'unknown',
                                'device': hostname,
                                'vlan': vlan or 'unknown'
                            }
                            logger.debug(f"Added/Updated MAC address: {mac} on port {port} of device {hostname}")
                except Exception as e:
                    logger.error(f"Error processing MAC entry: {str(e)}, Entry: {entry}")
                    
        # Disconnect from all devices
        self.disconnect_all()
        
        # Save MAC addresses to a file
        self.save_mac_addresses(mac_addresses)
        
        return mac_addresses
    
    def save_mac_addresses(self, mac_addresses, filename="mac_addresses.txt"):
        """Save collected MAC addresses to a file."""
        with open(filename, 'w') as f:
            for mac, info in mac_addresses.items():
                f.write(f"{mac},{info['device']},{info['port']},{info['vlan']}\n")
        logger.info(f"Saved {len(mac_addresses)} MAC addresses to {filename}")
    
    def get_arp_table(self, connection):
        """Try different variants of the show ip arp command for NX-OS."""
        # List of potential command variants, including NX-OS specific ones
        arp_commands = [
            "show ip arp",
            "show arp",
            "show ip arp | exclude Incomplete",
            # NX-OS specific commands
            "show ip arp vrf all",
            "show ip arp detail",
            "show arp"
        ]
        
        for command in arp_commands:
            try:
                logger.info(f"Trying command: {command}")
                output = self.execute_command(connection, command)
                
                # Dump the output to a file for debugging
                with open(f"arp_output_{time.strftime('%Y%m%d_%H%M%S')}.txt", "w") as f:
                    f.write(output)
                
                # Check if the output looks like an ARP table
                # Adjust criteria for NX-OS
                if len(output) > 100 and any(term in output.lower() 
                                           for term in ["ip", "address", "mac", "age", "interface"]):
                    logger.info(f"Successfully executed command: {command}")
                    return output
            except Exception as e:
                logger.warning(f"Error with command {command}: {str(e)}")
                continue
        
        logger.error("Could not retrieve ARP table with any command variant")
        return ""
    
    def map_mac_to_ip(self, hostnames, mac_addresses):
        """Connect to L3 devices and map MAC addresses to IP addresses."""
        mac_to_ip = {}
        
        if self.vxlan:
            # VXLAN mode: Use EVPN for MAC-to-IP mapping
            for hostname in hostnames:
                connection = self.connect(hostname)
                if not connection:
                    continue
                
                # Get EVPN MAC-IP bindings
                output = self.get_evpn_mac_ip_bindings(connection)
                if not output:
                    logger.error(f"Failed to get EVPN bindings from {hostname}")
                    continue
                
                # Parse EVPN output
                evpn_bindings = self.parse_evpn_output(output)
                
                # Match MAC addresses to IP addresses from EVPN
                for mac, ip in evpn_bindings.items():
                    # Normalize MAC address format
                    normalized_mac = mac.replace(':', '').replace('.', '')
                    
                    # Check both raw and normalized MAC formats
                    for stored_mac in mac_addresses.keys():
                        normalized_stored = stored_mac.replace(':', '').replace('.', '')
                        if mac == stored_mac or normalized_mac == normalized_stored:
                            # Get the existing L2 information
                            mac_info = mac_addresses[stored_mac].copy()
                            # Add the IP address but preserve the original L2 port info
                            mac_info['ip'] = ip
                            mac_to_ip[stored_mac] = mac_info
                            logger.info(f"Mapped MAC {stored_mac} to IP {ip} via EVPN (L2 port: {mac_info['port']})")
                            break
                
                connection.disconnect()
        else:
            # Standard mode: Use ARP table for MAC-to-IP mapping
            for hostname in hostnames:
                connection = self.connect(hostname)
                if not connection:
                    continue
                    
                # Use the helper method to get ARP table
                output = self.get_arp_table(connection)
                
                if not output:
                    logger.error(f"Failed to get ARP table from {hostname}")
                    continue
                    
                # Parse the output using TextFSM
                parsed_data = self.parse_with_textfsm(output, "cisco_ios_show_ip_arp.textfsm")
                
                if not parsed_data:
                    logger.error(f"Failed to parse ARP table from {hostname}")
                    continue
                    
                logger.info(f"Successfully parsed {len(parsed_data)} ARP entries from {hostname}")
                    
                # Match MAC addresses to IP addresses using updated field names
                for entry in parsed_data:
                    try:
                        # Handle potential different formats from the template
                        ip_address = None
                        mac_address = None
                        
                        # The entry should be a list with at least the IP and MAC values
                        if len(entry) >= 3:
                            ip_address = entry[0]  # IP_ADDRESS is first
                            
                            # Try to identify which field is the MAC address
                            mac_field = entry[2]  # Normally the third field is MAC_ADDRESS
                            
                            # Check if it looks like a MAC (contains : or .)
                            if ':' in mac_field or '.' in mac_field:
                                mac_address = mac_field.lower()
                            else:
                                # If not, try the second field
                                mac_field = entry[1]
                                if ':' in mac_field or '.' in mac_field:
                                    mac_address = mac_field.lower()
                        
                        if ip_address and mac_address:
                            # Normalize MAC address format (remove colons/dots if present)
                            normalized_mac = mac_address.replace(':', '').replace('.', '')
                            
                            # Check both the raw MAC and normalized format
                            matched = False
                            for stored_mac in mac_addresses.keys():
                                normalized_stored = stored_mac.replace(':', '').replace('.', '')
                                if mac_address == stored_mac or normalized_mac == normalized_stored:
                                    # Get the existing L2 information
                                    mac_info = mac_addresses[stored_mac].copy()
                                    # Add the IP address but preserve the original L2 port info
                                    mac_info['ip'] = ip_address
                                    mac_to_ip[stored_mac] = mac_info
                                    logger.info(f"Mapped MAC {stored_mac} to IP {ip_address} (L2 port: {mac_info['port']})")
                                    matched = True
                                    break
                            
                            if not matched:
                                logger.debug(f"MAC {mac_address} not found in collected L2 MAC addresses")
                        else:
                            logger.warning(f"Could not extract valid IP or MAC from entry: {entry}")
                            
                    except Exception as e:
                        logger.error(f"Error processing ARP entry: {str(e)}, Entry: {entry}")
        
        return mac_to_ip 