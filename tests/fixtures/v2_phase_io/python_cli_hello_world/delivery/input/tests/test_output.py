"""测试输出内容精确匹配。

工具的默认输出应该精确匹配 'hello, world'（区分大小写，无额外空格或引号）。
"""

import subprocess
import sys
import os


def test_exact_output():
    """默认输出精确匹配 'hello, world'。"""
    result = subprocess.run(
        [sys.executable, 'src/main.py'],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(__file__))
    )
    assert result.returncode == 0
    output = result.stdout.strip()
    assert output == 'hello, world'
    assert 'Hello, World' not in result.stdout
    assert '"hello, world"' not in result.stdout


def test_no_extra_whitespace():
    """输出不应有多余的空格或引号。"""
    result = subprocess.run(
        [sys.executable, 'src/main.py'],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(__file__))
    )
    assert result.returncode == 0
    output = result.stdout.strip()
    assert output.startswith('hello')
    assert output.endswith('world')
    assert len(output) == len('hello, world')
