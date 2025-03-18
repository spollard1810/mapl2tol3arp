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
    
    def __init__(self, username, password, templates_dir='templates', device_type='cisco_ios'):
        """Initialize the connector with login credentials."""
        self.username = username
        self.password = password
        self.device_type = device_type
        self.templates_dir = templates_dir
        self.mac_addresses = set()
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
            with open(template_path, 'r') as template_file:
                template = textfsm.TextFSM(template_file)
                result = template.ParseText(text_data)
                logger.info(f"Successfully parsed data with template: {template_name}")
                return result
        except FileNotFoundError:
            logger.error(f"Template file not found: {template_path}")
        except Exception as e:
            logger.error(f"Error parsing with TextFSM: {str(e)}")
            
        return []
    
    def get_mac_address_table(self, connection):
        """Try different variants of the show mac address-table command based on device type."""
        # List of potential command variants for different Cisco platforms
        mac_commands = [
            "show mac address-table",
            "show mac-address-table",
            "show mac addr",
            "show mac address-table dynamic"
        ]
        
        for command in mac_commands:
            try:
                logger.info(f"Trying command: {command}")
                output = self.execute_command(connection, command)
                
                # Check if the output looks like a MAC address table
                if "mac" in output.lower() and "address" in output.lower() and len(output) > 100:
                    logger.info(f"Successfully executed command: {command}")
                    return output
            except Exception as e:
                logger.warning(f"Error with command {command}: {str(e)}")
                continue
        
        logger.error("Could not retrieve MAC address table with any command variant")
        return ""
    
    def collect_mac_addresses(self, hostnames):
        """Connect to L2 devices and collect MAC address table information."""
        mac_addresses = set()
        
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
            
            # Extract MAC addresses - using the updated field name DESTINATION_ADDRESS
            for entry in parsed_data:
                # Get the MAC address using the updated field name
                mac = entry[0]  # DESTINATION_ADDRESS is the first field in the updated template
                if mac:
                    mac_addresses.add(mac.lower())  # Normalize MAC address format
                    
        # Disconnect from all devices
        self.disconnect_all()
        
        # Save MAC addresses to a file
        self.save_mac_addresses(mac_addresses)
        
        return mac_addresses
    
    def save_mac_addresses(self, mac_addresses, filename="mac_addresses.txt"):
        """Save collected MAC addresses to a file."""
        with open(filename, 'w') as f:
            for mac in mac_addresses:
                f.write(f"{mac}\n")
        logger.info(f"Saved {len(mac_addresses)} MAC addresses to {filename}")
    
    def get_arp_table(self, connection):
        """Try different variants of the show ip arp command."""
        # List of potential command variants
        arp_commands = [
            "show ip arp",
            "show arp",
            "show ip arp | exclude Incomplete"
        ]
        
        for command in arp_commands:
            try:
                logger.info(f"Trying command: {command}")
                output = self.execute_command(connection, command)
                
                # Check if the output looks like an ARP table
                if "ip" in output.lower() and "address" in output.lower() and len(output) > 100:
                    logger.info(f"Successfully executed command: {command}")
                    return output
            except Exception as e:
                logger.warning(f"Error with command {command}: {str(e)}")
                continue
        
        logger.error("Could not retrieve ARP table with any command variant")
        return ""
    
    def map_mac_to_ip(self, hostnames, mac_addresses):
        """Connect to L3 devices and map MAC addresses to IP addresses from ARP tables."""
        mac_to_ip = {}
        
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
                    # Using the updated field names - IP_ADDRESS and MAC_ADDRESS
                    if len(entry) >= 4:  # Ensure we have enough elements
                        ip = entry[1]     # IP_ADDRESS is the second field in the updated template
                        mac = entry[3].lower()  # MAC_ADDRESS is the fourth field, normalize to lowercase
                        
                        if mac in mac_addresses and mac not in mac_to_ip:
                            mac_to_ip[mac] = ip
                            logger.info(f"Mapped MAC {mac} to IP {ip}")
                except Exception as e:
                    logger.error(f"Error processing ARP entry: {str(e)}, Entry: {entry}")
        
        # Disconnect from all devices
        self.disconnect_all()
        
        return mac_to_ip 