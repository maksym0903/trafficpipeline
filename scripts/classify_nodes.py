#!/usr/bin/env python3
"""
Step 3: Classify nodes → stack txt files (nextjs.txt, nodejs.txt, docker.txt, …)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    os.chdir(ROOT)
    print('[*] Step 3: classify nodes → results/*.txt …')
    cmd = [sys.executable, 'tools/nextrce.py', '--export-stacks']
    raise SystemExit(subprocess.call(cmd))


if __name__ == '__main__':
    main()
