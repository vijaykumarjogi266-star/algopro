#!/bin/bash
unset ANDROID_DATA ANDROID_ROOT
python3 -c "
import sys, os
from pip._vendor import platformdirs
print('sys.platform:', sys.platform)
print('is_android:', sys.platform == 'android' or bool(os.environ.get('ANDROID_DATA')))
"
pip3 --version
