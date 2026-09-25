#!/usr/bin/env python3
"""
Installer for de-workflow-pipeline Antigravity Plugin.
Usage:
  python install.py [--workspace] [--global] [--target-dir <path>]
"""
import os
import sys
import shutil
import argparse
import json

def install():
    parser = argparse.ArgumentParser(description="Install de-workflow-pipeline Antigravity Plugin")
    parser.add_argument("--global", dest="is_global", action="store_true", help="Install globally in ~/.agents/plugins/")
    parser.add_argument("--workspace", dest="is_workspace", action="store_true", help="Install in current workspace .agents/plugins/")
    parser.add_argument("--target-dir", dest="target_dir", help="Custom destination directory for the plugin")
    args = parser.parse_args()

    src_dir = os.path.abspath(os.path.dirname(__file__))
    plugin_name = "de-workflow-pipeline"

    if args.target_dir:
        dest_dir = os.path.abspath(args.target_dir)
    elif args.is_global:
        dest_dir = os.path.expanduser(f"~/.agents/plugins/{plugin_name}")
    else:
        # Default to workspace .agents/plugins
        cwd = os.getcwd()
        dest_dir = os.path.join(cwd, ".agents", "plugins", plugin_name)

    print(f"Installing {plugin_name} to: {dest_dir}")
    os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
    if os.path.exists(dest_dir):
        print(f"Replacing existing plugin directory at {dest_dir}...")
        shutil.rmtree(dest_dir)

    # Copy tree, excluding __pycache__ and git metadata
    def ignore_patterns(path, names):
        return [n for n in names if n in ["__pycache__", ".git", ".DS_Store"] or n.endswith(".pyc")]

    shutil.copytree(src_dir, dest_dir, ignore=ignore_patterns)
    print(f"[SUCCESS] Plugin {plugin_name} installed successfully!")
    print(f"Path: {dest_dir}")

if __name__ == "__main__":
    install()
