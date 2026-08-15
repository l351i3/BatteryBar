import sys
import os

# 将当前目录（BatteryBar）以及它的父目录添加到 sys.path 中，使得无论是 classifier 还是其他模块都能被正常 import 导入
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
