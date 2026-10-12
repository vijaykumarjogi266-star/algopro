#!/bin/bash
set -e
unset ANDROID_DATA ANDROID_ROOT
cd /data/data/com.termux/files/home/algopro
python3 run_hard_stress_test.py
