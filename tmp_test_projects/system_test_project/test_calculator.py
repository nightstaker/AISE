"""Tests for calculator module."""

from __future__ import annotations

import pytest
from calculator import add, subtract, multiply, divide


class TestAdd:
    """Tests for add function."""

    def test_add_positive_numbers(self) -> None:
        """Test adding positive numbers."""
        assert add(2, 3) == 5

    def test_add_negative_numbers(self) -> None:
        """Test adding negative numbers."""
        assert add(-2, -3) == -5

    def test_add_mixed_numbers(self) -> None:
        """Test adding mixed positive and negative numbers."""
        assert add(-2, 3) == 1


class TestSubtract:
    """Tests for subtract function."""

    def test_subtract_positive_numbers(self) -> None:
        """Test subtracting positive numbers."""
        assert subtract(5, 3) == 2

    def test_subtract_result_negative(self) -> None:
        """Test subtraction resulting in negative number."""
        assert subtract(3, 5) == -2


class TestMultiply:
    """Tests for multiply function."""

    def test_multiply_positive_numbers(self) -> None:
        """Test multiplying positive numbers."""
        assert multiply(2, 3) == 6

    def test_multiply_by_zero(self) -> None:
        """Test multiplication by zero."""
        assert multiply(5, 0) == 0


class TestDivide:
    """Tests for divide function."""

    def test_divide_positive_numbers(self) -> None:
        """Test dividing positive numbers."""
        assert divide(6, 2) == 3.0

    def test_divide_by_zero_raises_error(self) -> None:
        """Test that division by zero raises ValueError."""
        with pytest.raises(ValueError):
            divide(5, 0)


class TestEdgeCases:
    """Tests for edge cases."""

    def test_all_functions_with_zero(self) -> None:
        """Test all functions with zero."""
        assert add(0, 0) == 0
        assert subtract(0, 0) == 0
        assert multiply(0, 5) == 0
        assert divide(0, 5) == 0.0