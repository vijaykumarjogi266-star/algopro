#!/bin/bash
unset ANDROID_DATA ANDROID_ROOT
cd /data/data/com.termux/files/home/algopro
python3 test_comprehensive_suite.py
