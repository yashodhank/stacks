#!/usr/bin/env python3
"""
GlusterFS Volume Automation and Docker Stack Processing Script

This script automates the process of updating Docker stack YAML files to use
GlusterFS for volume management. It reads Docker stack files from a source
directory, modifies the volume configurations to use GlusterFS, preserves
existing comments and dynamic values, and writes the updated files to a
destination directory.

Dependencies:
    Python 3.x
    ruamel.yaml (Install using pip3 install ruamel.yaml)

Author:
    Yashodhan Kulkarni

Date:
    6th Oct 2024
"""
import os
import re
import logging
from datetime import datetime
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# Configuration variables
source_dir = '/mnt/glusterfs/stacks/stacks/'  # Directory containing the original Docker stack YAML files
destination_dir = '/mnt/glusterfs/prod/'  # Directory to store processed stack files
glusterfs_nodes = ['172.30.230.1', '172.30.230.2', '172.30.230.3']  # List of GlusterFS nodes
glusterfs_base_path = '/data/gluster'  # Base path for GlusterFS volume on all nodes
volume_pattern = re.compile(r'[A-Za-z0-9-_]+')  # Regex to match valid volume names

# Set up logging
log_filename = f'glusterfs_volume_update_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
logging.basicConfig(filename=log_filename, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Regex to identify dynamic values
env_var_pattern = re.compile(r'\$\{[A-Z0-9_:-]+\}')
secret_pattern = re.compile(r'secrets:')
config_pattern = re.compile(r'configs:')
volume_path_pattern = re.compile(r'\$\{VOLUME_PATH\}')

# Log the start of the process
logging.info("Starting GlusterFS volume and Docker stack automation script...")


def is_valid_volume(volume_name):
    """Check if the volume name is valid and should be processed."""
    return bool(volume_pattern.match(volume_name))


def convert_volume_to_glusterfs(volume_name, volume_config):
    """Modify volume_config to use GlusterFS."""
    voluri = ','.join([f"{node}:{glusterfs_base_path}" for node in glusterfs_nodes])
    logging.info(f"Converting volume '{volume_name}' to use GlusterFS with voluri '{voluri}'")

    if volume_config is None:
        volume_config = CommentedMap()

    # Ensure volume_config is a CommentedMap
    if not isinstance(volume_config, CommentedMap):
        volume_config = CommentedMap(volume_config)

    # Modify in place to preserve comments
    volume_config['driver'] = 'glusterfs'
    driver_opts = volume_config.get('driver_opts', CommentedMap())
    if not isinstance(driver_opts, CommentedMap):
        driver_opts = CommentedMap(driver_opts)

    # Add necessary GlusterFS options
    # driver_opts['servers'] = ','.join(glusterfs_nodes)
    driver_opts['voluri'] = voluri
    driver_opts['replicate'] = '3'
    driver_opts['read-only'] = 'false'
    volume_config['driver_opts'] = driver_opts

    return volume_config


def scan_for_dynamic_values(file_content):
    """Scan the file for dynamic values."""
    dynamic_values = set(re.findall(env_var_pattern, file_content))

    # Search for secrets and configs
    if re.search(secret_pattern, file_content):
        dynamic_values.add('secrets')
    if re.search(config_pattern, file_content):
        dynamic_values.add('configs')

    # Search for volume paths
    if re.search(volume_path_pattern, file_content):
        dynamic_values.add('${VOLUME_PATH}')

    return dynamic_values


def extract_existing_comments(file_content):
    """Extract existing comment lines at the top of the file."""
    existing_comments = []
    for line in file_content.splitlines():
        if line.strip().startswith('#'):
            existing_comments.append(line)
        else:
            break  # Stop at the first non-comment line
    return existing_comments


def rearrange_stack_content(stack):
    """Rearrange the stack content to ensure the proper order."""
    desired_order = ['version', 'services', 'volumes', 'networks']

    # Reorder the keys in the stack CommentedMap
    existing_keys = list(stack.keys())

    for key in reversed(desired_order):
        if key in stack:
            stack.move_to_end(key, last=False)

    return stack  # Modifications are in place


def copy_stack_file_with_comments(src_file, dest_file):
    """Copy the stack file to the destination and add comments for dynamic values."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096  # Increase the width to prevent line wrapping

    try:
        with open(src_file, 'r') as file:
            original_content = file.read()
            stack = yaml.load(original_content)
    except Exception as e:
        logging.error(f"Error reading or parsing {src_file}: {e}")
        return

    existing_comments = extract_existing_comments(original_content)

    # Scan for dynamic values in the original file content
    dynamic_values = scan_for_dynamic_values(original_content)

    # Create a comment with the list of dynamic values
    comment_block = "# Dynamic Values in this file:\n"
    if dynamic_values:
        for value in sorted(dynamic_values):
            comment_block += f"# - {value}\n"
    else:
        comment_block += "# None found\n"

    # Combine existing comments with the new dynamic value comments
    combined_comments = "\n".join(existing_comments) + "\n" + comment_block

    # Attach the combined comments to the root mapping
    stack.yaml_set_start_comment(combined_comments, indent=0)

    # Rearrange the stack content
    rearranged_stack = rearrange_stack_content(stack)

    # Write the final content to the destination file
    try:
        with open(dest_file, 'w') as dest_file_handle:
            yaml.dump(rearranged_stack, dest_file_handle)
            logging.info(f"Copied and processed file: {src_file} to {dest_file}")
    except IOError as e:
        logging.error(f"Error writing to {dest_file}: {e}")
        return


def process_stack_file(file_path):
    """Process and modify a Docker stack file to use GlusterFS for all volumes."""
    yaml = YAML()
    yaml.preserve_quotes = True  # Preserve quotes around values
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096  # Increase the width to prevent line wrapping

    try:
        with open(file_path, 'r') as file:
            original_content = file.read()
            stack = yaml.load(original_content)
    except Exception as e:
        logging.error(f"Error reading or parsing {file_path}: {e}")
        return

    # Process volumes for GlusterFS conversion
    if stack and 'volumes' in stack:
        volumes_section = stack['volumes']
        for volume_name in volumes_section:
            volume_config = volumes_section[volume_name]

            if is_valid_volume(volume_name):
                # Modify the volume_config in place
                updated_volume_config = convert_volume_to_glusterfs(volume_name, volume_config)
                volumes_section[volume_name] = updated_volume_config

    # Save the modified stack temporarily for further processing
    temp_stack_file = os.path.join(destination_dir, os.path.basename(file_path))
    try:
        with open(temp_stack_file, 'w') as temp_file:
            yaml.dump(stack, temp_file)
        logging.info(f"Processed volumes and saved temporarily for file: {file_path}")
    except IOError as e:
        logging.error(f"Error writing temp file {temp_stack_file}: {e}")
        return

    # Copy the file to the destination directory with dynamic value comments
    copy_stack_file_with_comments(temp_stack_file, temp_stack_file)


def create_destination_directory():
    """Create the destination directory if it doesn't exist."""
    if not os.path.exists(destination_dir):
        os.makedirs(destination_dir)
        logging.info(f"Created destination directory: {destination_dir}")
    else:
        logging.info(f"Destination directory already exists: {destination_dir}")


def process_all_stack_files(directory):
    """Process all Docker stack files in the given directory."""
    logging.info(f"Processing all stack files in directory: {directory}")

    for filename in os.listdir(directory):
        if filename.endswith('.yml'):
            file_path = os.path.join(directory, filename)
            logging.info(f"Processing file: {file_path}")
            process_stack_file(file_path)

    logging.info("Completed processing all stack files.")


# Run the script on all stack files
if __name__ == "__main__":
    # Step 1: Create the destination directory
    create_destination_directory()

    # Step 2: Process and copy all stack files
    process_all_stack_files(source_dir)

    logging.info("GlusterFS volume automation and Docker stack processing complete.")
    print(f"Processing complete. Logs saved to {log_filename}")
