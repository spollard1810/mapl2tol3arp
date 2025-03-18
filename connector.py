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
from netmiko.ssh_exception import NetMikoTimeoutException, NetMikoAuthenticationException
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
            }
            
            connection = ConnectHandler(**device)
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
            output = connection.send_command(command)
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
    
    def collect_mac_addresses(self, hostnames):
        """Connect to L2 devices and collect MAC address table information."""
        mac_addresses = set()
        
        for hostname in hostnames:
            connection = self.connect(hostname)
            if not connection:
                continue
                
            # Execute "show mac address-table" command
            output = self.execute_command(connection, "show mac address-table")
            
            # Parse the output using TextFSM
            parsed_data = self.parse_with_textfsm(output, "cisco_ios_show_mac_address_table.textfsm")
            
            # Extract MAC addresses
            for entry in parsed_data:
                # Typically, MAC address would be in a specific index of the parsed result
                # Adjust the index based on your TextFSM template
                if len(entry) >= 2:  # Assuming MAC address is the second field
                    mac_addresses.add(entry[1].lower())  # Normalize MAC address format
                    
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
    
    def map_mac_to_ip(self, hostnames, mac_addresses):
        """Connect to L3 devices and map MAC addresses to IP addresses from ARP tables."""
        mac_to_ip = {}
        
        for hostname in hostnames:
            connection = self.connect(hostname)
            if not connection:
                continue
                
            # Execute "show ip arp" command
            output = self.execute_command(connection, "show ip arp")
            
            # Parse the output using TextFSM
            parsed_data = self.parse_with_textfsm(output, "cisco_ios_show_ip_arp.textfsm")
            
            # Match MAC addresses to IP addresses
            for entry in parsed_data:
                # Adjust indices based on your TextFSM template
                # Typically, IP is at index 0 and MAC is at index 2
                if len(entry) >= 3:
                    ip = entry[0]
                    mac = entry[2].lower()  # Normalize MAC address format
                    
                    if mac in mac_addresses and mac not in mac_to_ip:
                        mac_to_ip[mac] = ip
                        logger.info(f"Mapped MAC {mac} to IP {ip}")
        
        # Disconnect from all devices
        self.disconnect_all()
        
        return mac_to_ip 