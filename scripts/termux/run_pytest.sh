#!/bin/bash
unset ANDROID_DATA ANDROID_ROOT
cd /data/data/com.termux/files/home/algopro
pytest -p no:sugar tests -q
